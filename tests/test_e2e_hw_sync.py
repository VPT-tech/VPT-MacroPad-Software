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
PIN_BTN1, PIN_BTN4, PIN_BTN7 = 20, 19, 18


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


def test_e2e_sync_and_no_double_execution(qapp, monkeypatch, firmware):
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
        if fw_kind == "current":
            assert (w.hw_proto, w.fw_version) == (2, "1.1.0")
        else:
            assert (w.hw_proto, w.fw_version) == (1, "")

        # 2. Повна синхронізація після підключення: 12 кнопок x 3 слоти + 3 енкодери x 2
        n_set = lambda: sum(1 for r in sim.rx if r.startswith("SET_KEY:"))
        assert wait_until(qapp, lambda: n_set() >= 42), sim.rx
        assert n_set() == 42
        assert "SET_KEY:BTN_1:TAP:HID_MEDIA:3" in sim.rx      # Мультимедіа: BTN_1 = MED:PREV
        assert "SET_KEY:BTN_7:TAP:SERIAL" in sim.rx           # MED:MIC_MUTE — тільки ПК

        # 3. Апаратна кнопка: виконує плата, ПК не дублює
        sim._ctl(f"#press {PIN_BTN1}"); pump(qapp, 80); sim._ctl(f"#release {PIN_BTN1}")
        assert wait_until(qapp, lambda: "+c182" in sim.hid)
        pump(qapp, 150)
        assert injected == []

        # 4. SERIAL-кнопка: виконує ПК, плата не шле HID
        hid_before = len(sim.hid)
        sim._ctl(f"#press {PIN_BTN7}"); pump(qapp, 80); sim._ctl(f"#release {PIN_BTN7}")
        assert wait_until(qapp, lambda: ("mic_mute",) in injected)
        assert len(sim.hid) == hid_before

        # 5. Перемикання профілю: відправляються лише змінені рядки
        before = n_set()
        w.switch_profile(1)  # Blender 3D
        assert wait_until(qapp, lambda: "SET_KEY:BTN_4:TAP:HID_KEY:0:103" in sim.rx)
        pump(qapp, 100)
        delta = n_set() - before
        assert 0 < delta < 42, delta

        # 6. Multi-tap на платі (tap=g, dtap=r, hold=s) — одинарний тап після вікна 2x
        injected.clear()
        sim._ctl(f"#press {PIN_BTN4}"); pump(qapp, 60); sim._ctl(f"#release {PIN_BTN4}")
        assert wait_until(qapp, lambda: "+103" in sim.hid)
        pump(qapp, 100)
        assert injected == []

        # 7. Енкодер: Blender ENC_1 = ENC:ZOOM -> плата шле Ctrl+'='
        sim._ctl("#enc 0 1")
        assert wait_until(qapp, lambda: "+61" in sim.hid)
        pump(qapp, 100)
        assert injected == []

        # 8. Зміни під час відключення не губляться: SAVE_EEPROM дійде після підключення
        proc.stdin.close()
        proc.wait(timeout=3)
        assert wait_until(qapp, lambda: not w.device_connected, 4.0)
        w.sync_hardware_bindings(save_eeprom=True)
        pump(qapp, 100)
        assert w._hw_save_pending is True
    finally:
        w.cleanup_threads()
        if proc.poll() is None:
            proc.kill()
