"""Наскрізний тест HW <-> SW: справжні MacroPadPro + SerialThread + ActionExecutor,
підключені до прошивки, зібраної під хост (tests/firmware_sim/fw_stdio), яка працює
окремим процесом у реальному часі. Перевіряє рукостискання v2, повну/диференційну
синхронізацію, відсутність дублювання дій і реакцію на зникнення плати."""
import os
import queue
import shutil
import subprocess
import threading
import time

import pytest
import serial

import action_executor as ae
import threads as th
from conftest import ROOT

SIM_DIR = os.path.join(ROOT, "tests", "firmware_sim")
SIM_BINS = {
    "current": "fw_stdio",          # прошивка з firmware/ (протокол v2)
    "legacy": "fw_stdio_legacy",    # прошивка v1.0, як у ще не оновлених платах (протокол v1)
}

# Піни з прошивки
PIN_BTN1, PIN_BTN5, PIN_ENC2_SW = 20, 27, 6

ENC_TARGETS = {f"ENC_{i}_{d}" for i in (1, 2, 3) for d in "LR"}


def board_state(rx):
    """Відтворює стан плати з прийнятих нею команд: (пам'ять, вміст флешу)."""
    ram, saved = {}, None
    for line in rx:
        if line.startswith("SET_KEY:"):
            parts = line[len("SET_KEY:"):].split(":")
            if parts[0] in ENC_TARGETS:
                ram[parts[0]] = ":".join(parts[1:])
            else:
                ram[f"{parts[0]}:{parts[1]}"] = ":".join(parts[2:])
        elif line == "SAVE_EEPROM":
            saved = dict(ram)
        elif line == "LOAD_EEPROM" and saved is not None:
            ram = dict(saved)
    return ram, saved


class SimSerial:
    """pyserial-подібний порт поверх stdin/stdout процесу-симулятора прошивки."""

    def __init__(self, proc):
        self.proc = proc
        self.lines = queue.Queue()
        self.hid = []
        self.rx = []
        self._eof = False
        self._closed = False
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        for raw in iter(self.proc.stdout.readline, b""):
            s = raw.decode("utf-8", errors="ignore").rstrip("\r\n")
            if s.startswith("@HID "):
                self.hid.append(s[5:])
            elif s.startswith("@RX "):
                self.rx.append(s[4:])
            else:
                self.lines.put(raw)
        self._eof = True

    @property
    def is_open(self):
        return not self._closed and not self._eof

    def _ctl(self, line):
        self.write((line + "\n").encode())

    @property
    def dtr(self):
        return True

    @dtr.setter
    def dtr(self, v):
        self._ctl(f"#dtr {int(bool(v))}")

    @property
    def rts(self):
        return True

    @rts.setter
    def rts(self, v):
        pass

    def write(self, data):
        if not self.is_open:
            raise serial.SerialException("device gone")
        try:
            self.proc.stdin.write(data)
            self.proc.stdin.flush()
        except (BrokenPipeError, ValueError, OSError) as e:
            raise serial.SerialException(str(e))
        return len(data)

    def flush(self):
        pass

    def reset_input_buffer(self):
        while not self.lines.empty():
            self.lines.get_nowait()

    def reset_output_buffer(self):
        pass

    @property
    def in_waiting(self):
        if self._eof and self.lines.empty():
            raise serial.SerialException("device gone")
        return self.lines.qsize()

    def readline(self, size=-1):
        try:
            return self.lines.get(timeout=0.35)
        except queue.Empty:
            if self._eof:
                raise serial.SerialException("device gone")
            return b""

    def close(self):
        self._closed = True


class FakePort:
    device = "SIM0"
    product = "VPT MacroPad"
    vid = 0x2E8A


def wait_until(qapp, cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        qapp.processEvents()
        if cond():
            return True
        time.sleep(0.005)
    qapp.processEvents()
    return cond()


def pump(qapp, ms):
    wait_until(qapp, lambda: False, ms / 1000.0)


@pytest.fixture(params=sorted(SIM_BINS))
def firmware(request):
    if shutil.which(os.environ.get("CXX", "g++")) is None or shutil.which("make") is None:
        pytest.skip("немає C++ компілятора/make для збірки симулятора прошивки")
    target = SIM_BINS[request.param]
    subprocess.run(["make", "-s", "-C", SIM_DIR, target], check=True)
    return request.param, os.path.join(SIM_DIR, target)


def test_e2e_sync_and_no_double_execution(qapp, monkeypatch, firmware, fresh_config):
    fw_kind, sim_bin = firmware
    proc = subprocess.Popen([sim_bin], stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    sim = SimSerial(proc)
    monkeypatch.setattr(th.serial, "Serial", lambda *a, **k: sim)
    monkeypatch.setattr(th.serial.tools.list_ports, "comports", lambda: [FakePort()])

    import updater
    monkeypatch.setattr(updater, "get_latest_release_data", lambda: {})
    injected = []
    lock = threading.Lock()

    def rec(name):
        def _f(*args):
            with lock:
                injected.append((name,) + args)
        return _f

    for fn in ("win_hotkey", "win_hotkey_down", "win_hotkey_up", "win_key_event", "send_unicode_text"):
        monkeypatch.setattr(ae, fn, rec(fn))

    import main_window
    w = main_window.MacroPadPro()
    w.executor._toggle_mic_mute = lambda: injected.append(("mic_mute",))
    try:
        # 1. Рукостискання: протокол v2 і версія прошивки; стара прошивка -> v1
        assert wait_until(qapp, lambda: w.device_connected, 6.0), "плата не підключилась"
        n_set = lambda: sum(1 for r in sim.rx if r.startswith("SET_KEY:"))
        if fw_kind == "current":
            assert (w.hw_proto, w.fw_version) == (2, "1.2.0")
        else:
            assert (w.hw_proto, w.fw_version) == (1, "")

        # 2. Після підключення: у флеш плати записано профіль "без програми", а в пам'ять — активний
        assert wait_until(qapp, lambda: "SAVE_EEPROM" in sim.rx and board_state(sim.rx)[0] == w.compute_hw_specs()), sim.rx
        ram, saved = board_state(sim.rx)
        assert len(ram) == 42                                   # 12 кнопок x 3 слоти + 3 енкодери x 2
        assert saved == w.compute_standalone_specs()
        assert ram["BTN_1:TAP"] == "HID_MEDIA:3"                # Медіа: BTN_1 = попередній трек
        assert ram["BTN_5:TAP"] == "SERIAL"                     # мут мікрофона — лише через програму
        assert saved["BTN_5:TAP"] == "NONE"                     # ...тому без програми кнопка порожня
        assert saved["ENC_3_SW:TAP"] == "HID_MEDIA:4"           # а мут звуку плата вміє сама
        assert ram["ENC_3_SW:TAP"] == "SERIAL"                  # (з програмою — ще й утримання = профіль)

        # 3. Апаратна кнопка: виконує плата, ПК не дублює
        sim._ctl(f"#press {PIN_BTN1}"); pump(qapp, 80); sim._ctl(f"#release {PIN_BTN1}")
        assert wait_until(qapp, lambda: "+c182" in sim.hid)
        pump(qapp, 150)
        assert injected == []

        # 4. Кнопка, якій потрібна програма: виконує ПК, плата не шле HID
        hid_before = len(sim.hid)
        sim._ctl(f"#press {PIN_BTN5}"); pump(qapp, 80); sim._ctl(f"#release {PIN_BTN5}")
        assert wait_until(qapp, lambda: ("mic_mute",) in injected)
        assert len(sim.hid) == hid_before

        # 5. Перемикання профілю: лише змінені рядки і без запису у флеш
        saves = sim.rx.count("SAVE_EEPROM")
        before = n_set()
        w.switch_profile(2)  # Офіс і браузер
        assert wait_until(qapp, lambda: board_state(sim.rx)[0] == w.compute_hw_specs())
        pump(qapp, 100)
        assert 0 < n_set() - before < 42
        assert sim.rx.count("SAVE_EEPROM") == saves

        # 6. Tap/Hold на платі: ENC_2_SW натискання = нова вкладка (Ctrl+T)
        injected.clear()
        sim._ctl(f"#press {PIN_ENC2_SW}"); pump(qapp, 60); sim._ctl(f"#release {PIN_ENC2_SW}")
        assert wait_until(qapp, lambda: "+116" in sim.hid and "+128" in sim.hid)
        pump(qapp, 100)
        assert injected == []

        # 7. Енкодер: ENC_2 праворуч = наступна вкладка (Ctrl+Tab)
        sim._ctl("#enc 1 1")
        assert wait_until(qapp, lambda: "+179" in sim.hid)
        pump(qapp, 100)
        assert injected == []

        # 8. Інший профіль "без програми" (NumPad): записується у флеш, активний лишається
        w.set_standalone_profile(1)
        assert wait_until(qapp, lambda: sim.rx.count("SAVE_EEPROM") == saves + 1
                          and board_state(sim.rx)[0] == w.compute_hw_specs())
        ram, saved = board_state(sim.rx)
        assert saved == w.compute_standalone_specs()
        assert saved["BTN_1:TAP"] == "HID_KEY:0:231"           # num 7
        assert ram["BTN_1:TAP"] == "HID_KEY:1:99"              # активний профіль: Ctrl+C

        # 9. Вихід з програми: плата переходить на профіль "без програми", як після перепідключення
        w.restore_board_standalone()
        assert wait_until(qapp, lambda: board_state(sim.rx)[0] == w.compute_standalone_specs())
        hid_before = len(sim.hid)
        sim._ctl(f"#press {PIN_BTN1}"); pump(qapp, 80); sim._ctl(f"#release {PIN_BTN1}")
        assert wait_until(qapp, lambda: "+231" in sim.hid[hid_before:])

        # 10. Плата зникла — програма це бачить
        proc.stdin.close()
        proc.wait(timeout=3)
        assert wait_until(qapp, lambda: not w.device_connected, 4.0)
    finally:
        w.cleanup_threads()
        if proc.poll() is None:
            proc.kill()
