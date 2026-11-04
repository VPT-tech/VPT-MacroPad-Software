# utils.py
import os
import glob
import subprocess
import time
import ctypes
import pyautogui
from config import APP_PATH_CACHE, VK_MAP, split_hotkey_tokens

pyautogui.PAUSE = 0

PUL = ctypes.POINTER(ctypes.c_ulong)
_WMI_BRIGHTNESS_SUPPORTED = True

class KeyBdInput(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", PUL)
    ]

class HardwareInput(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_ushort),
        ("wParamH", ctypes.c_ushort)
    ]

class MouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", PUL)
    ]

class Input_I(ctypes.Union):
    _fields_ = [
        ("ki", KeyBdInput),
        ("mi", MouseInput),
        ("hi", HardwareInput)
    ]

class Input(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("ii", Input_I)
    ]

def send_vk(vk, press=True, force_extended=False):
    scan = ctypes.windll.user32.MapVirtualKeyA(vk, 0)
    flags = 0
    extended_keys = {
        0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5B, 0x5C, 0xA3, 0xA5,
        0xAD, 0xAE, 0xAF, 0xB0, 0xB1, 0xB2, 0xB3, 0x6F
    }

    if vk in extended_keys or force_extended:
        flags |= 0x0001
    if not press:
        flags |= 0x0002

    extra = ctypes.pointer(ctypes.c_ulong(0))
    ii_ = Input_I()
    ii_.ki = KeyBdInput(vk, scan, flags, 0, extra)
    x = Input(ctypes.c_ulong(1), ii_)
    ctypes.windll.user32.SendInput(1, ctypes.pointer(x), ctypes.sizeof(x))

def send_mouse_input(flags, data=0):
    data_ulong = data & 0xFFFFFFFF
    extra = ctypes.pointer(ctypes.c_ulong(0))
    ii_ = Input_I()
    ii_.mi = MouseInput(0, 0, ctypes.c_ulong(data_ulong), ctypes.c_ulong(flags), 0, extra)
    x = Input(ctypes.c_ulong(0), ii_)
    ctypes.windll.user32.SendInput(1, ctypes.pointer(x), ctypes.sizeof(x))

def win_key_event(key_name, event_type="tap"):
    key_name = key_name.lower().strip()
    if key_name in ("windows", "left windows", "right windows"):
        key_name = "win"

    if key_name.startswith("mouse_"):
        btn = key_name.replace("mouse_", "")
        try:
            if btn in ("wheel_up", "scroll_up"):
                if event_type in ("tap", "press"):
                    send_mouse_input(0x0800, 120)
            elif btn in ("wheel_down", "scroll_down"):
                if event_type in ("tap", "press"):
                    send_mouse_input(0x0800, -120)
            elif btn == "left":
                if event_type in ("tap", "press"): send_mouse_input(0x0002)
                if event_type in ("tap", "release"): send_mouse_input(0x0004)
            elif btn == "right":
                if event_type in ("tap", "press"): send_mouse_input(0x0008)
                if event_type in ("tap", "release"): send_mouse_input(0x0010)
            elif btn == "middle":
                if event_type in ("tap", "press"): send_mouse_input(0x0020)
                if event_type in ("tap", "release"): send_mouse_input(0x0040)
            elif btn == "x1":
                if event_type in ("tap", "press"): send_mouse_input(0x0080, 0x0001)
                if event_type in ("tap", "release"): send_mouse_input(0x0100, 0x0001)
            elif btn == "x2":
                if event_type in ("tap", "press"): send_mouse_input(0x0080, 0x0002)
                if event_type in ("tap", "release"): send_mouse_input(0x0100, 0x0002)
        except Exception:
            pass
        return

    vk = VK_MAP.get(key_name)
    is_num_enter = (key_name == "num enter")
    if vk:
        if event_type in ("tap", "press"): send_vk(vk, True, force_extended=is_num_enter)
        if event_type in ("tap", "release"): send_vk(vk, False, force_extended=is_num_enter)
    else:
        try:
            if event_type == "tap": pyautogui.press(key_name)
            elif event_type == "press": pyautogui.keyDown(key_name)
            elif event_type == "release": pyautogui.keyUp(key_name)
        except Exception:
            pass

def win_hotkey_down(combo):
    """Затискає всі клавіші комбінації без відпускання"""
    try:
        keys = split_hotkey_tokens(combo)
        for k in keys:
            win_key_event(k, "press")
            time.sleep(0.005)
    except Exception:
        pass

def win_hotkey_up(combo):
    """Відпускає всі клавіші комбінації у зворотному порядку"""
    try:
        keys = split_hotkey_tokens(combo)
        for k in reversed(keys):
            win_key_event(k, "release")
            time.sleep(0.005)
    except Exception:
        pass

def win_hotkey(combo):
    """Повний цикл натискання та відпускання гарячих клавіш"""
    try:
        keys = split_hotkey_tokens(combo)
        for k in keys:
            if not k.startswith("mouse_"):
                win_key_event(k, "press")
                time.sleep(0.015)

        for k in keys:
            if k.startswith("mouse_"):
                win_key_event(k, "tap")
                time.sleep(0.015)

        for k in reversed(keys):
            if not k.startswith("mouse_"):
                win_key_event(k, "release")
                time.sleep(0.01)
    except Exception:
        pass

def send_unicode_text(text):
    """Вводить текст через WinAPI KEYEVENTF_UNICODE незалежно від розкладки клавіатури"""
    if not text:
        return
    KEYEVENTF_UNICODE = 0x0004
    KEYEVENTF_KEYUP = 0x0002
    extra = ctypes.pointer(ctypes.c_ulong(0))

    for ch in text:
        if ch == '\r':
            continue
        if ch == '\n':
            win_key_event('enter', 'tap')
            time.sleep(0.005)
            continue

        utf16_units = ch.encode('utf-16-le')
        for i in range(0, len(utf16_units), 2):
            unit = int.from_bytes(utf16_units[i:i+2], 'little')

            ii_down = Input_I()
            ii_down.ki = KeyBdInput(0, unit, KEYEVENTF_UNICODE, 0, extra)
            x_down = Input(ctypes.c_ulong(1), ii_down)
            ctypes.windll.user32.SendInput(1, ctypes.pointer(x_down), ctypes.sizeof(x_down))

            ii_up = Input_I()
            ii_up.ki = KeyBdInput(0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, extra)
            x_up = Input(ctypes.c_ulong(1), ii_up)
            ctypes.windll.user32.SendInput(1, ctypes.pointer(x_up), ctypes.sizeof(x_up))
        time.sleep(0.002)

_WINAPI = None

def _winapi():
    """Приватні екземпляри kernel32/user32 з явними сигнатурами.
    Без argtypes/restype HANDLE/HWND повертаються як 32-бітний int (обрізання на x64).
    Окремі WinDLL-об'єкти, щоб не змінювати сигнатури в спільному ctypes.windll,
    яким користуються сторонні бібліотеки (pyautogui, pygetwindow)."""
    global _WINAPI
    if _WINAPI is not None:
        return _WINAPI
    import ctypes.wintypes as wt
    k32 = ctypes.WinDLL("kernel32")
    u32 = ctypes.WinDLL("user32")
    k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    k32.OpenProcess.restype = wt.HANDLE
    k32.CloseHandle.argtypes = [wt.HANDLE]
    k32.CloseHandle.restype = wt.BOOL
    k32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
    k32.QueryFullProcessImageNameW.restype = wt.BOOL
    u32.GetForegroundWindow.argtypes = []
    u32.GetForegroundWindow.restype = wt.HWND
    u32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    u32.GetWindowThreadProcessId.restype = wt.DWORD
    _WINAPI = (k32, u32)
    return _WINAPI

def get_process_path_by_pid(pid):
    """Миттєво отримує повний шлях до .exe за PID через WinAPI.
    PROCESS_QUERY_LIMITED_INFORMATION працює і для процесів, запущених від адміністратора."""
    if not pid:
        return ""
    try:
        import ctypes.wintypes as wt
        kernel32, _ = _winapi()
    except Exception:
        return ""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h_proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h_proc:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h_proc, 0, buf, ctypes.byref(size)):
            return buf.value
    except Exception:
        pass
    finally:
        kernel32.CloseHandle(h_proc)
    return ""

def get_process_exe_name(pid):
    path = get_process_path_by_pid(pid)
    return os.path.basename(path).lower() if path else ""

def get_foreground_exe():
    """Повертає (ім'я .exe у нижньому регістрі, pid) активного вікна або ("", 0)."""
    try:
        import ctypes.wintypes as wt
        _, user32 = _winapi()
    except Exception:
        return "", 0
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return "", 0
    pid = wt.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return "", 0
    return get_process_exe_name(pid.value), pid.value

def get_app_path(app_name, pid=None):
    if app_name in APP_PATH_CACHE and APP_PATH_CACHE[app_name]:
        return APP_PATH_CACHE[app_name]

    if pid:
        path = get_process_path_by_pid(pid)
        if path and os.path.exists(path):
            APP_PATH_CACHE[app_name] = path
            return path

    local_appdata = os.getenv("LOCALAPPDATA", "")
    appdata = os.getenv("APPDATA", "")
    prog_files = os.getenv("ProgramFiles", "C:\\Program Files")
    prog_files_x86 = os.getenv("ProgramFiles(x86)", "C:\\Program Files (x86)")
    common_paths = [
        f"{appdata}\\Spotify\\{app_name}",
        f"{local_appdata}\\Discord\\app-*\\{app_name}",
        f"{appdata}\\Telegram Desktop\\{app_name}",
        f"{prog_files}\\Google\\Chrome\\Application\\{app_name}",
        f"{prog_files_x86}\\Google\\Chrome\\Application\\{app_name}",
        f"{prog_files}\\obs-studio\\bin\\64bit\\{app_name}"
    ]
    for p in common_paths:
        if '*' in p:
            matches = glob.glob(p)
            if matches:
                APP_PATH_CACHE[app_name] = matches[0]
                return matches[0]
        elif os.path.exists(p):
            APP_PATH_CACHE[app_name] = p
            return p
    return ""

def move_mouse_abs(x, y):
    """Миттєво переміщує курсор миші у вказані екранні координати (X, Y)"""
    try:
        ctypes.windll.user32.SetCursorPos(int(x), int(y))
    except Exception:
        pass

class _PHYSICAL_MONITOR(ctypes.Structure):
    _fields_ = [
        ("hPhysicalMonitor", ctypes.c_void_p),
        ("szPhysicalMonitorDescription", ctypes.c_wchar * 128)
    ]

def _set_ddc_brightness_winapi(lvl):
    """Нативне регулювання яскравості зовнішніх моніторів через системний dxva2.dll (DDC/CI VCP 0x10)."""
    any_success = False
    try:
        user32 = ctypes.windll.user32
        dxva2 = ctypes.windll.dxva2
        hmonitors = []

        MONITORENUMPROC = ctypes.WINFUNCTYPE(
            ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_long * 4), ctypes.c_long
        )

        def _enum_cb(hMonitor, hdcMonitor, lprcMonitor, dwData):
            hmonitors.append(hMonitor)
            return 1

        user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(_enum_cb), 0)

        for hmon in hmonitors:
            num_phys = ctypes.c_ulong(0)
            if dxva2.GetNumberOfPhysicalMonitorsFromHMONITOR(ctypes.c_void_p(hmon), ctypes.byref(num_phys)):
                count = num_phys.value
                if count > 0:
                    phys_arr = (_PHYSICAL_MONITOR * count)()
                    if dxva2.GetPhysicalMonitorsFromHMONITOR(ctypes.c_void_p(hmon), count, phys_arr):
                        for i in range(count):
                            h_phys = ctypes.c_void_p(phys_arr[i].hPhysicalMonitor)
                            # 0x10 — стандартний VCP-код яскравості (Luminance) у специфікації DDC/CI MCCS
                            # SetMonitorBrightness — лише запасний варіант: дві DDC-команди
                            # поспіль на кожен крок перевантажують шину I2C деяких моніторів.
                            ok = dxva2.SetVCPFeature(h_phys, ctypes.c_ubyte(0x10), ctypes.c_ulong(lvl))
                            if not ok:
                                ok = dxva2.SetMonitorBrightness(h_phys, ctypes.c_ulong(lvl))
                            if ok:
                                any_success = True
                        dxva2.DestroyPhysicalMonitors(count, phys_arr)
    except Exception:
        pass
    return any_success

def set_monitor_brightness(val_percent):
    """Встановлює яскравість зовнішніх моніторів (WinAPI DDC/CI) та екранів ноутбуків (WMI) від 0 до 100."""
    global _WMI_BRIGHTNESS_SUPPORTED
    lvl = max(0, min(100, int(round(val_percent * 100))))

    # 1. Нативний WinAPI DDC/CI (dxva2.dll) для всіх підключених моніторів
    ddc_ok = _set_ddc_brightness_winapi(lvl)

    # 2. Фолбек через monitorcontrol (якщо встановлено)
    if not ddc_ok:
        try:
            import monitorcontrol
            for monitor in monitorcontrol.get_monitors():
                try:
                    with monitor:
                        monitor.set_luminance(lvl)
                        ddc_ok = True
                except Exception:
                    pass
        except Exception:
            pass

    # 3. WMI для матриць ноутбуків та моноблоків
    if _WMI_BRIGHTNESS_SUPPORTED:
        try:
            cmd = f'powershell -NoProfile -WindowStyle Hidden -Command "(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods -ErrorAction Stop).WmiSetBrightness(1, {lvl})"'
            res = subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=0x08000000, timeout=1.5)
            if res.returncode != 0:
                _WMI_BRIGHTNESS_SUPPORTED = False
        except Exception:
            pass