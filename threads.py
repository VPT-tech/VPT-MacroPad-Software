# threads.py
import gc
import os
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
from utils import get_app_path, get_foreground_exe

# Версія протоколу, яку запитує програма (прошивка відповідає PROTO_OK:<n>:FW=<версія>).
# v2: прошивка позначає апаратно виконані події суфіксом ":HW".
HOST_PROTO_VERSION = 2

# Браузер дозволяє БУДЬ-ЯКОМУ сайту відкрити WebSocket на localhost, тому сервер приймає
# лише розширення браузера та сторінки YouTube (якщо розширення підключається з content script).
WS_ALLOWED_ORIGINS = frozenset({
    "https://www.youtube.com",
    "https://youtube.com",
    "https://m.youtube.com",
    "https://music.youtube.com",
})
WS_ALLOWED_ORIGIN_PREFIXES = ("chrome-extension://", "moz-extension://")


def is_allowed_ws_origin(origin):
    """Origin відсутній лише у не-браузерних клієнтів (локальні програми), їх дозволяємо."""
    if origin is None:
        return True
    o = str(origin).strip().lower().rstrip("/")
    if not o or o == "null":
        return False
    return o in WS_ALLOWED_ORIGINS or o.startswith(WS_ALLOWED_ORIGIN_PREFIXES)


def _ws_request_origin(websocket):
    """Origin з рукостискання (підтримка старого і нового API бібліотеки websockets)."""
    req = getattr(websocket, "request", None)
    headers = getattr(req, "headers", None) if req is not None else None
    if headers is None:
        headers = getattr(websocket, "request_headers", None)
    if headers is None:
        return None
    try:
        return headers.get("Origin")
    except Exception:
        return None


class WebSocketServerThread(QThread):
    def __init__(self, host="localhost", port=8765):
        super().__init__()
        self.host = host
        self.port = port
        self.clients = set()
        self.loop = None
        self.server = None
        self.is_running = True
        self.rejected_origins = []

    async def start_server(self):
        self.loop = asyncio.get_running_loop()
        try:
            async with websockets.serve(self.handler, self.host, self.port) as server:
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
        origin = _ws_request_origin(websocket)
        if not is_allowed_ws_origin(origin):
            self.rejected_origins.append(origin)
            try:
                await websocket.close(code=1008, reason="origin not allowed")
            except Exception:
                pass
            return
        self.clients.add(websocket)
        try:
            await websocket.wait_closed()
        finally:
            self.clients.discard(websocket)

    def send_command(self, cmd):
        loop = self.loop
        if not loop or not self.clients or not loop.is_running():
            return

        async def send_to_all():
            for ws in list(self.clients):
                try:
                    await ws.send(cmd)
                except Exception:
                    pass
        try:
            asyncio.run_coroutine_threadsafe(send_to_all(), loop)
        except RuntimeError:
            pass

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
            sessions = AudioUtilities.GetAllSessions()
            for s in sessions:
                try:
                    if s.Process and s.Process.name():
                        name = s.Process.name().lower()
                        apps_pids[name] = s.Process.pid
                except Exception:
                    pass
            # COM-об'єкти мають бути звільнені ДО CoUninitialize, інакше Release()
            # викличеться вже на деініціалізованому COM і процес може впасти.
            s = None
            sessions = None
            gc.collect()
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
    # (рядок події, версія протоколу, на якій її отримано)
    macro_signal = Signal(str, int)
    status_signal = Signal(str, str)
    # (підключено, версія протоколу, версія прошивки, причина останнього ресету плати: "" | "WDT")
    link_signal = Signal(bool, int, str, str)

    # Службові відповіді прошивки, які не є подіями кнопок
    _CONTROL_PREFIXES = ("PONG_VPT_MACROPAD", "EEPROM_SAVED", "PROTO_OK:")

    def __init__(self):
        super().__init__()
        self.cmd_queue = []
        self.queue_lock = threading.Lock()
        self.is_running = True
        self._force_reconnect = False
        self._connected = False
        self.proto = 1
        self.fw_version = ""
        self.reset_reason = ""

    @property
    def is_connected(self):
        return self._connected

    def send_command(self, cmd):
        self.send_commands([cmd])

    def send_commands(self, cmds):
        # Поки плата відключена, команди не накопичуються: після підключення
        # програма все одно робить повну синхронізацію. Раніше черга росла без меж
        # (кожне автоперемикання профілю додавало ~45 команд) і потім вивантажувалась на плату.
        if not cmds or not self._connected:
            return
        with self.queue_lock:
            self.cmd_queue.extend(cmds)

    def clear_queue(self):
        with self.queue_lock:
            self.cmd_queue.clear()

    def force_reconnect(self):
        """Примусово скидає COM-з'єднання (викликається після виходу ПК зі сну/гібернації)."""
        self._force_reconnect = True

    def stop(self):
        self.is_running = False

    def _set_disconnected(self, conn):
        if conn:
            try: conn.close()
            except Exception: pass
        was = self._connected
        self._connected = False
        self.clear_queue()
        if was:
            self.link_signal.emit(False, self.proto, self.fw_version, "")

    @staticmethod
    def _readline(conn):
        return conn.readline(256).decode('utf-8', errors='ignore').strip()

    def _handshake(self, port_device):
        """Відкриває порт і перевіряє, що це саме VPT MacroPad.
        Повертає (conn, proto, fw, reset_reason, early_lines)."""
        temp_conn = serial.Serial(port_device, 115200, timeout=0.35, write_timeout=0.5)
        try:
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
                line = self._readline(temp_conn)
                if line == "PONG_VPT_MACROPAD_V1":
                    found_pong = True
                    break
                if not line:
                    break
            if not found_pong:
                temp_conn.close()
                return None, 1, "", "", []

            # Узгодження версії протоколу. Стара прошивка мовчки ігнорує PROTO:x → лишаємось на v1.
            proto, fw, rst, early = 1, "", "", []
            temp_conn.write(f"PROTO:{HOST_PROTO_VERSION}\n".encode())
            temp_conn.flush()
            deadline = time.time() + 0.4
            while time.time() < deadline:
                line = self._readline(temp_conn)
                if not line:
                    break
                if line.startswith("PROTO_OK:"):
                    parts = line.split(":")
                    try:
                        proto = max(1, min(HOST_PROTO_VERSION, int(parts[1])))
                    except (IndexError, ValueError):
                        proto = 1
                    for p in parts[2:]:
                        if p.startswith("FW="):
                            fw = p[3:]
                        elif p.startswith("RST="):
                            rst = p[4:]
                    break
                if not line.startswith(self._CONTROL_PREFIXES):
                    early.append(line)
            return temp_conn, proto, fw, rst, early
        except Exception:
            try: temp_conn.close()
            except Exception: pass
            raise

    def run(self):
        conn = None
        last_rx_or_ping = 0.0
        awaiting_pong = False
        ping_sent_at = 0.0

        while self.is_running:
            if self._force_reconnect and conn:
                self._force_reconnect = False
                self._set_disconnected(conn)
                conn = None
                time.sleep(0.5)

            if not conn or not conn.is_open:
                if conn is not None:
                    self._set_disconnected(conn)
                    conn = None
                self._force_reconnect = False
                ports = list(serial.tools.list_ports.comports())
                # Спершу порти з нашою назвою продукту, потім інші RP2040
                ports.sort(key=lambda p: 0 if (p.product and "VPT MacroPad" in p.product) else 1)
                for port in ports:
                    is_vpt = bool(port.product and "VPT MacroPad" in port.product)
                    is_rp2040 = (port.vid == 0x2E8A)
                    if not (is_vpt or is_rp2040):
                        continue
                    try:
                        c, proto, fw, rst, early = self._handshake(port.device)
                    except Exception:
                        continue
                    if c is None:
                        continue
                    conn = c
                    self.proto = proto
                    self.fw_version = fw
                    self.reset_reason = rst
                    last_rx_or_ping = time.time()
                    awaiting_pong = False
                    self.clear_queue()
                    self._connected = True
                    self.link_signal.emit(True, proto, fw, rst)
                    self.status_signal.emit("<font color='#00ff66'>⬤</font> Підключено", "#00ff66")
                    for line in early:
                        self.macro_signal.emit(line, proto)
                    break

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

            if pending_cmds:
                try:
                    payload = "".join(f"{c}\n" for c in pending_cmds).encode('utf-8')
                    conn.write(payload)
                    conn.flush()
                except Exception:
                    self._set_disconnected(conn)
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
                    self._set_disconnected(conn)
                    conn = None
                    continue
            elif awaiting_pong and (now - ping_sent_at) > 1.2:
                # Плата не відповіла на PING (зомбі-порт після гібернації) — перепідключаємось
                self._set_disconnected(conn)
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
                        if msg and not msg.startswith(self._CONTROL_PREFIXES):
                            self.macro_signal.emit(msg, self.proto)
                else:
                    time.sleep(0.005)
            except Exception:
                self._set_disconnected(conn)
                conn = None
                awaiting_pong = False
                time.sleep(0.5)

        if conn:
            try: conn.close()
            except Exception: pass
        self._connected = False


class MutePollerThread(QThread):
    states_updated = Signal(dict, dict, dict, dict)

    # Як часто перевідкривати аудіо-ендпоінти (зміна пристрою за замовчуванням,
    # підключення навушників тощо). Раніше вони перевідкривались лише після помилки.
    ENDPOINT_REFRESH_SEC = 3.0

    def __init__(self):
        super().__init__()
        self.is_running = True

    def stop(self):
        self.is_running = False

    @staticmethod
    def _open_endpoint(enumerator, flow, role, iface, clsctx):
        try:
            d = enumerator.GetDefaultAudioEndpoint(flow, role)
            i = d.Activate(iface._iid_, clsctx, None)
            return ctypes.cast(i, ctypes.POINTER(iface))
        except Exception:
            return None

    def run(self):
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import EDataFlow, ERole, IAudioEndpointVolume

        CoInitialize()
        vc = None
        vc_mic = None
        last_refresh = 0.0
        last_emitted = None
        last_emit_time = 0.0
        try:
            while self.is_running:
                sys_mute = {"sys": False, "mic": False}
                sys_vol = {"sys": 0.0, "mic": 0.0}
                apps_mute = {}
                apps_vol = {}
                try:
                    now = time.time()
                    if vc is None or vc_mic is None or (now - last_refresh) > self.ENDPOINT_REFRESH_SEC:
                        vc = vc_mic = None
                        e = AudioUtilities.GetDeviceEnumerator()
                        vc = self._open_endpoint(e, EDataFlow.eRender.value, ERole.eMultimedia.value, IAudioEndpointVolume, CLSCTX_ALL)
                        vc_mic = self._open_endpoint(e, EDataFlow.eCapture.value, ERole.eMultimedia.value, IAudioEndpointVolume, CLSCTX_ALL)
                        e = None
                        last_refresh = now

                    if vc is not None:
                        sys_mute["sys"] = (vc.GetMute() != 0)
                        sys_vol["sys"] = round(vc.GetMasterVolumeLevelScalar(), 3)
                    if vc_mic is not None:
                        sys_mute["mic"] = (vc_mic.GetMute() != 0)
                        sys_vol["mic"] = round(vc_mic.GetMasterVolumeLevelScalar(), 3)

                    sessions = AudioUtilities.GetAllSessions()
                    for s in sessions:
                        try:
                            if s and s.Process and s.Process.name():
                                name = s.Process.name().lower()
                                apps_mute[name] = (s.SimpleAudioVolume.GetMute() != 0)
                                apps_vol[name] = round(s.SimpleAudioVolume.GetMasterVolume(), 3)
                        except Exception:
                            pass
                    s = None
                    sessions = None

                except Exception:
                    vc = None
                    vc_mic = None

                snapshot = (sys_mute, apps_mute, sys_vol, apps_vol)
                # Оновлюємо UI, коли щось змінилось (і не рідше ніж раз на 2 с —
                # щоб скоригувати локально "передбачену" гучність після обертання енкодера)
                now = time.time()
                if snapshot != last_emitted or (now - last_emit_time) > 2.0:
                    last_emitted = snapshot
                    last_emit_time = now
                    self.states_updated.emit(sys_mute, apps_mute, sys_vol, apps_vol)

                for _ in range(10):
                    if not self.is_running: break
                    time.sleep(0.1)
        finally:
            vc = None
            vc_mic = None
            gc.collect()
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
        own_pid = os.getpid()
        last_app = ""

        while self.is_running:
            try:
                exe, pid = get_foreground_exe()
                # Власне вікно налаштувань ігноруємо: інакше при відкритті програми
                # з Photoshop профіль одразу "відкочувався" на базовий.
                if exe and pid != own_pid and exe != last_app:
                    last_app = exe
                    self.app_changed.emit(exe)
            except Exception:
                pass
            for _ in range(5):
                if not self.is_running: break
                time.sleep(0.1)
