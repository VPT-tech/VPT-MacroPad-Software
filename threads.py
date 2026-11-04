# threads.py
import time
import threading
import serial
import serial.tools.list_ports
import asyncio
import websockets
import ctypes
from PySide6.QtCore import QThread, Signal
from comtypes import CoInitialize, CoUninitialize
from pycaw.pycaw import AudioUtilities
from utils import get_app_path

class WebSocketServerThread(QThread):
    def __init__(self):
        super().__init__()
        self.clients = set()
        self.loop = None
        self.server = None
        self.is_running = True

    async def start_server(self):
        self.loop = asyncio.get_running_loop()
        try:
            async with websockets.serve(self.handler, "localhost", 8765) as server:
                self.server = server
                while self.is_running:
                    await asyncio.sleep(0.2)
        except Exception:
            pass

    def run(self):
        try:
            asyncio.run(self.start_server())
        except Exception:
            pass

    async def handler(self, websocket, *args):
        self.clients.add(websocket)
        try:
            await websocket.wait_closed()
        finally:
            self.clients.discard(websocket)

    def send_command(self, cmd):
        if not self.loop or not self.clients or not self.loop.is_running():
            return
        async def send_to_all():
            for ws in list(self.clients):
                try:
                    await ws.send(cmd)
                except Exception:
                    pass
        asyncio.run_coroutine_threadsafe(send_to_all(), self.loop)

    def stop(self):
        self.is_running = False

class AudioScannerThread(QThread):
    apps_found = Signal(list)
    def run(self):
        apps_pids = {
            "discord.exe": None,
            "spotify.exe": None,
            "chrome.exe": None,
            "telegram.exe": None,
            "obs64.exe": None
        }
        try:
            CoInitialize()
            for s in AudioUtilities.GetAllSessions():
                try:
                    if s.Process and s.Process.name():
                        name = s.Process.name().lower()
                        apps_pids[name] = s.Process.pid
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            try: CoUninitialize()
            except Exception: pass

        results = []
        for app in sorted(apps_pids.keys()):
            results.append({"app": app, "path": get_app_path(app, apps_pids[app])})

        self.apps_found.emit(results)

class SerialThread(QThread):
    macro_signal = Signal(str)
    status_signal = Signal(str, str)

    def __init__(self):
        super().__init__()
        self.cmd_queue = []
        self.queue_lock = threading.Lock()
        self.is_running = True
        self._force_reconnect = False

    def send_command(self, cmd):
        with self.queue_lock:
            self.cmd_queue.append(cmd)

    def clear_queue(self):
        with self.queue_lock:
            self.cmd_queue.clear()

    def force_reconnect(self):
        """Примусово скидає COM-з'єднання (викликається після виходу ПК зі сну/гібернації)."""
        self._force_reconnect = True

    def stop(self):
        self.is_running = False

    def run(self):
        conn = None
        last_rx_or_ping = 0.0
        awaiting_pong = False
        ping_sent_at = 0.0

        while self.is_running:
            if self._force_reconnect and conn:
                self._force_reconnect = False
                try:
                    conn.close()
                except Exception:
                    pass
                conn = None
                time.sleep(0.5)

            if not conn or not conn.is_open:
                self._force_reconnect = False
                for port in serial.tools.list_ports.comports():
                    is_vpt = (port.product and "VPT MacroPad" in port.product)
                    is_rp2040 = (port.vid == 0x2E8A)
                    if is_vpt or is_rp2040:
                        try:
                            temp_conn = serial.Serial(port.device, 115200, timeout=0.35, write_timeout=0.5)
                            temp_conn.dtr = False
                            temp_conn.rts = False
                            time.sleep(0.05)
                            temp_conn.dtr = True
                            temp_conn.rts = True
                            time.sleep(0.08)

                            temp_conn.reset_input_buffer()
                            temp_conn.reset_output_buffer()
                            temp_conn.write(b"PING_VPT_MACROPAD\n")
                            temp_conn.flush()

                            # Читаємо кілька рядків на випадок, якщо в буфері була подія кнопки
                            found_pong = False
                            deadline = time.time() + 0.45
                            while time.time() < deadline:
                                line = temp_conn.readline().decode('utf-8', errors='ignore').strip()
                                if line == "PONG_VPT_MACROPAD_V1":
                                    found_pong = True
                                    break
                                if not line:
                                    break

                            if found_pong:
                                conn = temp_conn
                                last_rx_or_ping = time.time()
                                awaiting_pong = False
                                self.status_signal.emit("<font color='#00ff66'>⬤</font> Підключено", "#00ff66")
                                break
                            else:
                                temp_conn.close()
                        except Exception:
                            pass

                if not conn:
                    self.status_signal.emit("<font color='#ff3366'>⬤</font> Відключено", "#ff3366")
                    for _ in range(15):
                        if not self.is_running or self._force_reconnect:
                            break
                        time.sleep(0.1)
                    continue

            # Пакетне вивантаження черги команд
            with self.queue_lock:
                pending_cmds = list(self.cmd_queue)
                self.cmd_queue.clear()

            if pending_cmds and conn and conn.is_open:
                try:
                    payload = "".join(f"{c}\n" for c in pending_cmds).encode('utf-8')
                    conn.write(payload)
                    conn.flush()
                except Exception:
                    try: conn.close()
                    except Exception: pass
                    conn = None
                    continue

            # Watchdog перевірки живого порту після гібернації / сну
            now = time.time()
            if not awaiting_pong and (now - last_rx_or_ping) > 2.5:
                try:
                    conn.write(b"PING_VPT_MACROPAD\n")
                    conn.flush()
                    awaiting_pong = True
                    ping_sent_at = now
                except Exception:
                    try: conn.close()
                    except Exception: pass
                    conn = None
                    continue
            elif awaiting_pong and (now - ping_sent_at) > 1.2:
                # Плата не відповіла на PING (зомбі-порт після гібернації) — перепідключаємось
                try: conn.close()
                except Exception: pass
                conn = None
                awaiting_pong = False
                continue

            try:
                if conn.in_waiting > 0:
                    line = conn.readline(256)
                    if line:
                        last_rx_or_ping = time.time()
                        awaiting_pong = False
                        msg = line.decode('utf-8', errors='ignore').strip()
                        if msg and msg not in ("EEPROM_SAVED", "PONG_VPT_MACROPAD_V1"):
                            self.macro_signal.emit(msg)
                else:
                    time.sleep(0.005)
            except Exception:
                if conn:
                    try: conn.close()
                    except Exception: pass
                conn = None
                awaiting_pong = False
                time.sleep(0.5)

        if conn:
            try: conn.close()
            except Exception: pass

class MutePollerThread(QThread):
    states_updated = Signal(dict, dict, dict, dict)

    def __init__(self):
        super().__init__()
        self.is_running = True

    def stop(self):
        self.is_running = False

    def run(self):
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import EDataFlow, ERole, IAudioEndpointVolume

        CoInitialize()
        vc = None
        vc_mic = None
        try:
            while self.is_running:
                sys_mute = {"sys": False, "mic": False}
                sys_vol = {"sys": 0.0, "mic": 0.0}
                apps_mute = {}
                apps_vol = {}
                try:
                    if vc is None or vc_mic is None:
                        e = AudioUtilities.GetDeviceEnumerator()
                        try:
                            d = e.GetDefaultAudioEndpoint(EDataFlow.eRender.value, ERole.eMultimedia.value)
                            i = d.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                            vc = ctypes.cast(i, ctypes.POINTER(IAudioEndpointVolume))
                        except Exception:
                            vc = None

                        try:
                            d_mic = e.GetDefaultAudioEndpoint(EDataFlow.eCapture.value, ERole.eMultimedia.value)
                            i_mic = d_mic.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                            vc_mic = ctypes.cast(i_mic, ctypes.POINTER(IAudioEndpointVolume))
                        except Exception:
                            vc_mic = None

                    if vc is not None:
                        sys_mute["sys"] = (vc.GetMute() != 0)
                        sys_vol["sys"] = vc.GetMasterVolumeLevelScalar()
                    if vc_mic is not None:
                        sys_mute["mic"] = (vc_mic.GetMute() != 0)
                        sys_vol["mic"] = vc_mic.GetMasterVolumeLevelScalar()

                    sessions = AudioUtilities.GetAllSessions()
                    for s in sessions:
                        if s and s.Process and s.Process.name():
                            name = s.Process.name().lower()
                            apps_mute[name] = (s.SimpleAudioVolume.GetMute() != 0)
                            apps_vol[name] = s.SimpleAudioVolume.GetMasterVolume()

                except Exception:
                    vc = None
                    vc_mic = None

                self.states_updated.emit(sys_mute, apps_mute, sys_vol, apps_vol)

                for _ in range(10):
                    if not self.is_running: break
                    time.sleep(0.1)
        finally:
            try: CoUninitialize()
            except Exception: pass

class ActiveWindowThread(QThread):
    app_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.is_running = True

    def stop(self):
        self.is_running = False

    def run(self):
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi
        last_app = ""

        while self.is_running:
            hwnd = user32.GetForegroundWindow()
            if hwnd:
                pid = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                h_proc = kernel32.OpenProcess(0x0410, False, pid)
                if h_proc:
                    buf = ctypes.create_unicode_buffer(260)
                    if psapi.GetModuleBaseNameW(h_proc, None, buf, ctypes.sizeof(buf)):
                        exe = buf.value.lower()
                        if exe != last_app:
                            last_app = exe
                            self.app_changed.emit(exe)
                    kernel32.CloseHandle(h_proc)
            for _ in range(5):
                if not self.is_running: break
                time.sleep(0.1)