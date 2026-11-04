# action_executor.py
#
# Модель потоків:
#   * ActionExecutor — QObject, живе в GUI-потоці. Усі події з плати приходять сюди
#     через queued-сигнал, а таймери Tap/Double-Tap/Hold — це QTimer, тож уся машина
#     станів і всі звернення до Qt-віджетів виконуються лише в GUI-потоці.
#   * Емуляція клавіатури/миші та COM-виклики (мут мікрофона/програм) виконуються в
#     окремому послідовному воркері (_input_worker): GUI не блокується на time.sleep()
#     всередині win_hotkey(), а порядок натискань/відпускань зберігається (FIFO).
#   * Запуск програм/URL/CMD — короткоживучі daemon-потоки, щоб повільний os.startfile()
#     не затримував натискання клавіш.
import os
import json
import time
import queue
import threading
import webbrowser
import subprocess
import ctypes
import pyautogui

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from comtypes import CLSCTX_ALL, CoInitialize
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
from utils import (win_key_event, win_hotkey, win_hotkey_down, win_hotkey_up,
                   send_unicode_text, move_mouse_abs, set_monitor_brightness, get_monitor_brightness)

BUTTON_IDS = frozenset([f"BTN_{i}" for i in range(1, 10)] + [f"ENC_{i}_SW" for i in range(1, 4)])
ENC_IDS = frozenset(f"ENC_{i}" for i in range(1, 4))

HOLD_TIME_MS = 300     # мають збігатися з прошивкою (HOLD_TIME_MS / DTAP_WINDOW_MS)
DTAP_WINDOW_MS = 220


def _parse_event(raw):
    """'BTN_1_PRESSED:HW' -> ('BTN_1_PRESSED', {'HW'})"""
    base, _, rest = raw.strip().partition(":")
    flags = set(f for f in rest.split(":") if f) if rest else set()
    return base, flags


def _accel_from_flags(flags):
    """Множник прискорення, виміряний платою (':A3'), або None."""
    for f in flags:
        if len(f) >= 2 and f[0] == "A" and f[1:].isdigit():
            return max(1, min(5, int(f[1:])))
    return None


class ActionExecutor(QObject):
    # Фактична яскравість монітора (з воркера яскравості -> GUI-потік)
    brightness_synced = Signal(float)
    # Якщо яскравість довго не чіпали, перед наступною зміною її перечитуємо з монітора
    # (її могли змінити кнопками самого монітора чи іншою програмою)
    BRIGHTNESS_RESYNC_SEC = 20.0

    def __init__(self, main_app):
        super().__init__()
        self.app = main_app
        self.running_macros = {}
        self._macros_lock = threading.Lock()

        # Стан Multi-Tap (Tap / Double Tap / Hold). Контекст фіксується в момент натискання,
        # щоб відпускання завжди відпускало саме те, що було натиснуто (навіть якщо профіль
        # перемкнувся під час утримання) — інакше лишались "залиплі" Ctrl/Shift.
        self._press_ctx = {}       # key -> dict
        self._hold_timers = {}     # key -> QTimer
        self._dtap_timers = {}     # key -> QTimer
        self._tap_counts = {}

        # Стан для Temporary Layer Hold (Shift-режим профілів)
        self._temp_profile_holds = {}  # key -> previous_profile_idx

        # Таймінги обертання енкодерів для Encoder Acceleration
        self._enc_last_tick = {}

        # Послідовний воркер для емуляції вводу та COM
        self._input_q = queue.Queue()
        self._input_thread = threading.Thread(target=self._input_worker, name="vpt-input", daemon=True)
        self._input_thread.start()

        # Асинхронна черга для миттєвої зміни гучності програм без фрізів UI
        self._pending_app_vols = {}
        self._vol_lock = threading.Lock()
        self._vol_event = threading.Event()
        self._vol_worker_thread = threading.Thread(target=self._app_vol_worker, name="vpt-appvol", daemon=True)
        self._vol_worker_thread.start()

        # Асинхронний воркер для плавного регулювання яскравості монітора.
        # GUI передає лише відносні зміни (дельти), а абсолютне значення веде воркер,
        # спираючись на реально прочитану з монітора яскравість.
        self._pending_br_delta = 0.0
        self._br_base = None            # належить воркеру
        self._br_last_sync = 0.0        # належить воркеру
        self._br_osd_until = 0.0
        self._br_lock = threading.Lock()
        self._br_event = threading.Event()
        self.brightness_synced.connect(self._on_brightness_synced)
        self._br_worker_thread = threading.Thread(target=self._brightness_worker, name="vpt-brightness", daemon=True)
        self._br_worker_thread.start()

    # ------------------------------------------------------------------ воркери
    def _inject(self, fn, *args):
        self._input_q.put((fn, args))

    def _input_worker(self):
        try:
            CoInitialize()
        except Exception:
            pass
        while True:
            fn, args = self._input_q.get()
            if fn is None:
                break
            try:
                fn(*args)
            except Exception:
                pass

    @staticmethod
    def _launch(fn, *args):
        def _run():
            try:
                fn(*args)
            except Exception:
                pass
        threading.Thread(target=_run, daemon=True).start()

    def _app_vol_worker(self):
        CoInitialize()
        while True:
            self._vol_event.wait()
            self._vol_event.clear()

            while True:
                with self._vol_lock:
                    if not self._pending_app_vols:
                        break
                    items = dict(self._pending_app_vols)
                    self._pending_app_vols.clear()

                try:
                    sessions = AudioUtilities.GetAllSessions()
                    for s in sessions:
                        if s and s.Process and s.Process.name():
                            proc_name = s.Process.name().lower()
                            if proc_name in items:
                                s.SimpleAudioVolume.SetMasterVolume(items[proc_name], None)
                    s = None
                    sessions = None
                except Exception:
                    pass

    def _br_resync(self, allow_wmi):
        """Читає фактичну яскравість монітора (виконується у воркері яскравості)."""
        try:
            val = get_monitor_brightness(allow_wmi=allow_wmi)
        except Exception:
            val = None
        if val is not None:
            self._br_base = max(0.0, min(1.0, float(val)))
            self._br_last_sync = time.monotonic()
        return val

    def _brightness_worker(self):
        # Стартове зчитування (DDC/CI, для ноутбуків — WMI), щоб індикатор і перший крок
        # енкодера відповідали реальності, а не припущеним 70%
        if self._br_resync(allow_wmi=True) is not None:
            self.brightness_synced.emit(self._br_base)
        while True:
            self._br_event.wait()
            self._br_event.clear()
            while True:
                with self._br_lock:
                    delta = self._pending_br_delta
                    self._pending_br_delta = 0.0
                if abs(delta) < 1e-9:
                    break
                if self._br_base is None or (time.monotonic() - self._br_last_sync) > self.BRIGHTNESS_RESYNC_SEC:
                    # Лише швидкий DDC: повільний WMI (~1 с) тут дав би помітну затримку
                    self._br_resync(allow_wmi=False)
                base = self._br_base if self._br_base is not None else 0.7
                new_val = max(0.0, min(1.0, base + delta))
                try:
                    set_monitor_brightness(new_val)
                except Exception:
                    pass
                self._br_base = new_val
                self._br_last_sync = time.monotonic()
                with self._br_lock:
                    more_pending = abs(self._pending_br_delta) > 1e-9
                if not more_pending:
                    self.brightness_synced.emit(new_val)
                # Контролери моніторів по шині DDC/CI (I2C) потребують ~45 мс між пакетами
                time.sleep(0.045)

    @Slot(float)
    def _on_brightness_synced(self, val):
        prev = self.app.volume_states.get("brightness", val)
        self.app.update_instant_vol("brightness", val)
        # OSD ще на екрані і показує "передбачене" значення — уточнюємо реальним
        if time.monotonic() < self._br_osd_until and abs(prev - val) > 0.005:
            self.app.trigger_osd("volume", "Яскравість монітора", val, icon_text="brightness")

    # ------------------------------------------------------------------ енкодери
    def _get_enc_accel_multiplier(self, base_enc):
        """Розраховує множник прискорення крутилки залежно від швидкості обертання."""
        now = time.monotonic()
        last = self._enc_last_tick.get(base_enc, 0.0)
        self._enc_last_tick[base_enc] = now
        dt = now - last
        if dt < 0.025:
            return 5
        elif dt < 0.050:
            return 3
        elif dt < 0.085:
            return 2
        return 1

    def execute_rotation_action(self, act, is_r, accel=1, hw_already_fired=False):
        """Виконує дію обертання енкодера з урахуванням прискорення та апаратного HID."""
        if not act or act == "NONE":
            return

        # Якщо плата вже відправила 1 крок через апаратний HID, виконуємо лише (accel - 1) додаткових кроків
        extra_steps = max(0, accel - 1) if hw_already_fired else accel

        if act == "ENC:VOL":
            step = 0.02 * accel
            current_vol = self.app.volume_states.get("sys", 0.5)
            new_vol = min(1.0, current_vol + step) if is_r else max(0.0, current_vol - step)
            self.app.update_instant_vol("sys", new_vol)
            for _ in range(extra_steps):
                self._inject(win_key_event, "volumeup" if is_r else "volumedown", "tap")
            self.app.trigger_osd("volume", "Гучність системи", new_vol, icon_text="volume")

        elif act == "ENC:SCROLL":
            if extra_steps > 0:
                self._inject(pyautogui.scroll, -140 * extra_steps if is_r else 140 * extra_steps)

        elif act == "ENC:BRIGHTNESS":
            step = 0.03 * accel * (1 if is_r else -1)
            current_br = self.app.volume_states.get("brightness", 0.7)
            new_br = max(0.0, min(1.0, current_br + step))
            self.app.update_instant_vol("brightness", new_br)
            with self._br_lock:
                self._pending_br_delta += step
            self._br_event.set()
            self._br_osd_until = time.monotonic() + 1.5
            self.app.trigger_osd("volume", "Яскравість монітора", new_br, icon_text="brightness")

        elif act == "ENC:ZOOM":
            combo = "ctrl+=" if is_r else "ctrl+-"
            steps = min(extra_steps, 2) if hw_already_fired else min(accel, 3)
            for _ in range(steps):
                self._inject(win_hotkey, combo)

        elif act == "ENC:TIMELINE":
            k = "right" if is_r else "left"
            for _ in range(extra_steps):
                self._inject(win_key_event, k, "tap")

        elif act == "ENC:BRUSH":
            k = "]" if is_r else "["
            for _ in range(extra_steps):
                self._inject(win_key_event, k, "tap")

        elif act == "ENC:UNDO_REDO":
            if not hw_already_fired:
                self._inject(win_hotkey, "ctrl+y" if is_r else "ctrl+z")

        elif act.startswith("ENC:APP:"):
            step = 0.03 * accel
            target = act.split(":")[-1].lower()
            current_vol = self.app.volume_states.get("apps", {}).get(target, 0.5)
            new_vol = min(1.0, current_vol + step) if is_r else max(0.0, current_vol - step)
            self.app.update_instant_vol(target, new_vol, is_app=True)

            with self._vol_lock:
                self._pending_app_vols[target] = new_vol
            self._vol_event.set()

            clean_app = target.replace(".exe", "").capitalize()
            self.app.trigger_osd("volume", f"Гучність: {clean_app}", new_vol, icon_text="mixer", app_exe=target)

    def _handle_rotation(self, base_enc, is_r, hw, board_accel=None):
        rot_key = f"{base_enc}_R" if is_r else f"{base_enc}_L"
        # Прошивка ≥1.1 міряє інтервал між клацаннями сама (точно, без впливу пачок USB);
        # для старої прошивки — оцінка за часом приходу подій на ПК
        local_accel = self._get_enc_accel_multiplier(base_enc)
        accel = board_accel if board_accel is not None else local_accel

        rot_act = self.app.get_action(rot_key)
        center_act = self.app.get_enc_active_action(base_enc)
        # hw=None — стара прошивка (протокол v1): вгадуємо за поточною конфігурацією
        hw_handled = hw if hw is not None else self.app.is_enc_dir_hw_handled(base_enc, is_r)

        # 1. Дія бокової стрілки (якщо призначена)
        if rot_act and rot_act != "NONE":
            if rot_act.startswith("ENC:"):
                self.execute_rotation_action(rot_act, is_r, accel, hw_already_fired=hw_handled)
            elif not hw_handled:
                self.execute_btn_action(rot_act, rot_key, is_pressed=True, is_released=True)

        # 2. Дія центра крутилки (з підтримкою Smart Dial режимів)
        if center_act and center_act != "NONE":
            if center_act.startswith("ENC:"):
                self.execute_rotation_action(center_act, is_r, accel, hw_already_fired=hw_handled)
            elif not hw_handled:
                self.execute_btn_action(center_act, base_enc, is_pressed=True, is_released=True)

    # ------------------------------------------------------------------ вхідні події
    @Slot(str, int)
    def execute(self, raw, proto=1):
        try:
            base, flags = _parse_event(raw)
            # v2: прошивка явно каже, чи виконала подію апаратно. v1: невідомо (None).
            hw = ("HW" in flags) if proto >= 2 else None

            if base.endswith("_FIRED"):
                key = base[:-len("_FIRED")]
                if key in BUTTON_IDS:
                    slot = next((f.lower() for f in flags if f in ("TAP", "DTAP", "HOLD")), "tap")
                    self._on_hw_fired(key, slot)
                return

            for sfx, is_r in (("_RIGHT", True), ("_LEFT", False)):
                if base.endswith(sfx):
                    enc = base[:-len(sfx)]
                    if enc in ENC_IDS:
                        self._handle_rotation(enc, is_r, hw, _accel_from_flags(flags) if proto >= 2 else None)
                    return

            if base.endswith("_PRESSED"):
                key, is_pressed = base[:-len("_PRESSED")], True
            elif base.endswith("_RELEASED"):
                key, is_pressed = base[:-len("_RELEASED")], False
            else:
                return
            if key in BUTTON_IDS:
                self._handle_button_event(key, is_pressed, not is_pressed, hw)
        except Exception:
            pass

    def _on_hw_fired(self, key, slot):
        """Плата апаратно виконала слот кнопки — показуємо OSD там, де це має сенс."""
        ctx = self._press_ctx.get(key)
        triggers = ctx["triggers"] if ctx else self.app.get_button_triggers(key)
        if triggers.get(slot, "NONE") == "MED:MUTE":
            self._show_sys_mute_osd()

    def _stop_timer(self, timers, key):
        t = timers.pop(key, None)
        if t is not None:
            t.stop()
            t.deleteLater()

    def _start_timer(self, timers, key, ms, callback):
        self._stop_timer(timers, key)
        t = QTimer(self)
        t.setSingleShot(True)
        t.timeout.connect(callback)
        timers[key] = t
        t.start(ms)

    def _handle_button_event(self, key, is_pressed, is_released, hw=None):
        """Машина станів Tap / Double-Tap / Hold (>300 мс) + Temporary Layer Hold."""
        if is_released and key in self._temp_profile_holds:
            prev_idx = self._temp_profile_holds.pop(key)
            self._press_ctx.pop(key, None)
            self._stop_timer(self._hold_timers, key)
            profiles = self.app.config.get("PROFILES", [])
            if 0 <= prev_idx < len(profiles):
                self.app.request_profile_switch(prev_idx, from_hotkey=True, is_temp_hold=False)
            return

        if is_pressed:
            triggers = self.app.get_button_triggers(key)
            hw_mode = hw if hw is not None else self.app.is_button_fully_hw(key)
            tap_act = triggers.get("tap", "NONE")
            dtap_act = triggers.get("dtap", "NONE")
            hold_act = triggers.get("hold", "NONE")
            ctx = {
                "triggers": triggers,
                "hw": hw_mode,
                "multi": (dtap_act != "NONE") or (hold_act != "NONE"),
                "fast": False,
                "hold_fired": False,
            }
            self._press_ctx[key] = ctx

            if hw_mode:
                # Стара прошивка не повідомляє про спрацювання слоту — показуємо OSD як раніше
                if hw is None and tap_act == "MED:MUTE" and not ctx["multi"]:
                    self._show_sys_mute_osd()
                return

            if not ctx["multi"]:
                if tap_act != "NONE":
                    ctx["fast"] = True
                    self.execute_btn_action(tap_act, key, is_pressed=True, is_released=False)
                return

            if hold_act != "NONE":
                self._start_timer(self._hold_timers, key, HOLD_TIME_MS,
                                  lambda k=key, c=ctx: self._on_hold_timeout(k, c))
            return

        # --- відпускання
        ctx = self._press_ctx.pop(key, None)
        self._stop_timer(self._hold_timers, key)
        if ctx is None or ctx["hw"]:
            # Відпускання без відомого натискання (напр. кнопку затиснули до підключення) — ігноруємо
            return

        tap_act = ctx["triggers"].get("tap", "NONE")
        dtap_act = ctx["triggers"].get("dtap", "NONE")
        hold_act = ctx["triggers"].get("hold", "NONE")

        if ctx["fast"]:
            self.execute_btn_action(tap_act, key, is_pressed=False, is_released=True)
            return

        if ctx["hold_fired"]:
            self.execute_btn_action(hold_act, key, is_pressed=False, is_released=True)
            return

        # Короткий клік (< 300 мс)
        if dtap_act == "NONE":
            if tap_act != "NONE":
                self._fire_instant_tap(tap_act, key)
            return

        cnt = self._tap_counts.get(key, 0) + 1
        self._tap_counts[key] = cnt
        self._stop_timer(self._dtap_timers, key)
        if cnt >= 2:
            self._tap_counts[key] = 0
            self._fire_instant_tap(dtap_act, key)
        else:
            self._start_timer(self._dtap_timers, key, DTAP_WINDOW_MS,
                              lambda k=key, a=tap_act: self._on_dtap_timeout(k, a))

    def _on_hold_timeout(self, key, ctx):
        self._hold_timers.pop(key, None)
        if self._press_ctx.get(key) is not ctx:
            return  # кнопку вже відпустили / натиснули знову
        ctx["hold_fired"] = True
        self._tap_counts[key] = 0
        self._stop_timer(self._dtap_timers, key)
        self.execute_btn_action(ctx["triggers"].get("hold", "NONE"), key, is_pressed=True, is_released=False)

    def _on_dtap_timeout(self, key, tap_act):
        self._dtap_timers.pop(key, None)
        if self._tap_counts.get(key, 0) == 1:
            self._tap_counts[key] = 0
            if tap_act != "NONE":
                self._fire_instant_tap(tap_act, key)

    def _fire_instant_tap(self, act, key):
        if act.startswith("HOTKEY:"):
            self._inject(win_hotkey, act.split(":", 1)[1])
        elif act.startswith("MACRO:"):
            self.execute_btn_action(act, key, is_pressed=True, is_released=True)
        elif act.startswith("SYS:PROFILE_HOLD:"):
            self.execute_btn_action(act, key, is_pressed=True, is_released=False)
            self.execute_btn_action(act, key, is_pressed=False, is_released=True)
        else:
            self.execute_btn_action(act, key, is_pressed=True, is_released=False)

    def release_all(self):
        """Відпускає все, що ПК тримає натиснутим (втрата зв'язку з платою, вихід з програми)."""
        for key, ctx in list(self._press_ctx.items()):
            try:
                self._handle_button_event(key, False, True, hw=ctx["hw"])
            except Exception:
                pass
        self._press_ctx.clear()
        for timers in (self._hold_timers, self._dtap_timers):
            for key in list(timers):
                self._stop_timer(timers, key)
        self._tap_counts.clear()

    def on_device_disconnected(self):
        self.release_all()

    def shutdown(self):
        self.release_all()
        with self._macros_lock:
            events = list(self.running_macros.values())
            self.running_macros.clear()
        for ev in events:
            ev.set()

    # ------------------------------------------------------------------ OSD / COM
    def _show_sys_mute_osd(self):
        new_mute = not self.app.mute_states.get("sys", False)
        self.app.mute_states["sys"] = new_mute
        self.app.trigger_osd("status", "Звук вимкнено" if new_mute else "Звук увімкнено",
                             is_danger=new_mute, icon_text="volume-x" if new_mute else "volume")

    def _toggle_mic_mute(self):
        """Виконується у воркері вводу (COM вже ініціалізовано)."""
        from pycaw.pycaw import EDataFlow, ERole
        e = d = i = vc = None
        try:
            e = AudioUtilities.GetDeviceEnumerator()
            d = e.GetDefaultAudioEndpoint(EDataFlow.eCapture.value, ERole.eMultimedia.value)
            i = d.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            vc = ctypes.cast(i, ctypes.POINTER(IAudioEndpointVolume))
            new_state = 0 if vc.GetMute() != 0 else 1
            vc.SetMute(new_state, None)
            is_muted = (new_state == 1)
            self.app.mute_states["mic"] = is_muted
            self.app.trigger_osd("status", "Мікрофон вимкнено" if is_muted else "Мікрофон увімкнено",
                                 is_danger=is_muted, icon_text="mic-off" if is_muted else "mic")
        finally:
            e = d = i = vc = None

    def _toggle_app_mute(self, target):
        sessions = None
        try:
            sessions = AudioUtilities.GetAllSessions()
            for s in sessions:
                if s.Process and s.Process.name() and s.Process.name().lower() == target:
                    v = s.SimpleAudioVolume
                    new_state = 0 if v.GetMute() != 0 else 1
                    v.SetMute(new_state, None)
                    is_muted = (new_state == 1)
                    self.app.mute_states.setdefault("apps", {})[target] = is_muted
                    clean_app = target.replace(".exe", "").capitalize()
                    self.app.trigger_osd(
                        "status",
                        f"{clean_app}: Звук вимкнено" if is_muted else f"{clean_app}: Звук увімкнено",
                        is_danger=is_muted,
                        icon_text="volume-x" if is_muted else "volume",
                        app_exe=target
                    )
                    v = None
            s = None
        finally:
            sessions = None

    # ------------------------------------------------------------------ дії
    def _start_macro(self, key, events, loop, c_delay):
        stop_ev = threading.Event()
        with self._macros_lock:
            self.running_macros[key] = stop_ev
        threading.Thread(target=self.play_macro, args=(events, key, stop_ev, loop, c_delay), daemon=True).start()

    def _stop_macro(self, key):
        with self._macros_lock:
            ev = self.running_macros.pop(key, None)
        if ev is not None:
            ev.set()

    def _is_macro_running(self, key):
        with self._macros_lock:
            ev = self.running_macros.get(key)
        return ev is not None and not ev.is_set()

    def execute_btn_action(self, act, key, is_pressed=True, is_released=False):
        if not act or act == "NONE":
            return
        try:
            # 1. ОБРОБКА МАКРОСІВ
            if act.startswith("MACRO:"):
                m_name = act.split(":", 1)[1]
                m_json = self.app.config.get("MACROS", {}).get(m_name)
                if not m_json:
                    return

                m_data = m_json
                if isinstance(m_data, str):
                    try:
                        m_data = json.loads(m_data)
                    except Exception:
                        m_data = []
                if isinstance(m_data, list):
                    m_data = {"mode": "One Shot", "events": m_data}
                if not isinstance(m_data, dict):
                    return

                mode = m_data.get("mode", "One Shot")
                events = m_data.get("events", [])
                try:
                    c_delay = max(1, int(m_data.get("cycle_delay", 100)))
                except (TypeError, ValueError):
                    c_delay = 100
                # Одночасні press+release — це "тап" (обертання енкодера, multi-tap слот)
                is_tap = is_pressed and is_released
                running = self._is_macro_running(key)

                if is_pressed:
                    if mode == "Toggle":
                        if running:
                            self._stop_macro(key)
                        else:
                            self._start_macro(key, events, True, c_delay)
                    elif mode == "Repeat while held" and not is_tap:
                        if not running:
                            self._start_macro(key, events, True, c_delay)
                    else:
                        # One Shot, або "Repeat while held" на тапі — один прохід
                        # (раніше на енкодері такий макрос крутився нескінченно).
                        if not running:
                            self._start_macro(key, events, False, c_delay)
                if is_released and not is_tap and mode == "Repeat while held":
                    self._stop_macro(key)

            # 2. ТИМЧАСОВЕ УТРИМАННЯ ПРОФІЛЮ (Shift-кнопка / Momentary Layer)
            elif act.startswith("SYS:PROFILE_HOLD:"):
                target_idx = int(act.split(":")[-1])
                profiles = self.app.config.get("PROFILES", [])
                if is_pressed and 0 <= target_idx < len(profiles):
                    if key not in self._temp_profile_holds:
                        self._temp_profile_holds[key] = self.app.active_profile_idx
                    self.app.request_profile_switch(target_idx, from_hotkey=True, is_temp_hold=True)
                if is_released and key in self._temp_profile_holds:
                    prev_idx = self._temp_profile_holds.pop(key)
                    if 0 <= prev_idx < len(profiles):
                        self.app.request_profile_switch(prev_idx, from_hotkey=True, is_temp_hold=False)

            # 3. ЗВИЧАЙНІ КЛАВІШІ ТА КОМБІНАЦІЇ
            elif act.startswith("HOTKEY:"):
                combo = act.split(":", 1)[1]
                if is_pressed and is_released:
                    self._inject(win_hotkey, combo)
                elif is_pressed:
                    self._inject(win_hotkey_down, combo)
                elif is_released:
                    self._inject(win_hotkey_up, combo)

            # 4. РАЗОВІ СИСТЕМНІ / МЕДІА / ЗАПУСКНІ ДІЇ
            elif is_pressed:
                self._execute_oneshot(act, key)
        except Exception:
            pass

    def _execute_oneshot(self, act, key):
        if act == "ENC:MODE_TOGGLE":
            base_enc = key.replace("_SW", "") if key.startswith("ENC_") else "ENC_1"
            self.app.cycle_enc_mode(base_enc)

        elif act.startswith("MULTI:"):
            g_name = act.split(":", 1)[1]
            items = list(self.app.config.get("MULTI_LAUNCH", {}).get(g_name, []))

            def launch_items(item_list):
                for idx, item_data in enumerate(item_list):
                    if isinstance(item_data, str):
                        action_str, delay_val = item_data, 0.5
                    elif isinstance(item_data, dict):
                        action_str = item_data.get("action", "")
                        delay_val = item_data.get("delay", 0.5)
                    else:
                        continue
                    try:
                        if action_str.startswith("URL:"):
                            webbrowser.open(self._normalize_url(action_str.split(":", 1)[1]))
                        elif action_str.startswith("EXE:"):
                            exe_path = action_str.split(":", 1)[1]
                            if os.path.exists(exe_path):
                                os.startfile(exe_path)
                    except Exception:
                        pass
                    if idx < len(item_list) - 1:
                        try:
                            time.sleep(max(0.0, min(60.0, float(delay_val))))
                        except (TypeError, ValueError):
                            time.sleep(0.5)

            self._launch(launch_items, items)

        elif act.startswith("SYS:"):
            parts = act.split(":")
            code = parts[1]
            if code == "TASK": self._inject(win_hotkey, 'ctrl+shift+esc')
            elif code == "DESKTOP": self._inject(win_hotkey, 'win+d')
            elif code == "SNIP": self._inject(win_hotkey, 'win+shift+s')
            elif code == "LOCK": self._inject(win_hotkey, 'win+l')
            elif code == "SLEEP": self._launch(ctypes.windll.powrprof.SetSuspendState, False, False, False)
            elif code == "PROFILE_NEXT":
                profiles = self.app.config.get("PROFILES", [])
                if profiles:
                    next_idx = (self.app.active_profile_idx + 1) % len(profiles)
                    self.app.request_profile_switch(next_idx, from_hotkey=True, is_temp_hold=False)
            elif code == "PROFILE_PREV":
                profiles = self.app.config.get("PROFILES", [])
                if profiles:
                    prev_idx = (self.app.active_profile_idx - 1) % len(profiles)
                    self.app.request_profile_switch(prev_idx, from_hotkey=True, is_temp_hold=False)
            elif code == "PROFILE_GOTO" and len(parts) > 2:
                target_idx = int(parts[2])
                profiles = self.app.config.get("PROFILES", [])
                if 0 <= target_idx < len(profiles):
                    self.app.request_profile_switch(target_idx, from_hotkey=True, is_temp_hold=False)

        elif act.startswith("MED:"):
            code = act.split(":")[1]
            if code == "PLAY": self._inject(win_key_event, "playpause", "tap")
            elif code == "NEXT": self._inject(win_key_event, "nexttrack", "tap")
            elif code == "PREV": self._inject(win_key_event, "prevtrack", "tap")
            elif code == "MUTE":
                self._inject(win_key_event, "volumemute", "tap")
                self._show_sys_mute_osd()
            elif code == "VOL_UP": self._inject(win_key_event, "volumeup", "tap")
            elif code == "VOL_DOWN": self._inject(win_key_event, "volumedown", "tap")
            elif code == "MIC_MUTE": self._inject(self._toggle_mic_mute)

        elif act.startswith("APP_MUTE:"):
            self._inject(self._toggle_app_mute, act.split(":")[-1].lower())

        elif act.startswith("TEXT:"):
            self._inject(send_unicode_text, act.split(":", 1)[1])

        elif act.startswith("URL:"):
            self._launch(webbrowser.open, self._normalize_url(act.split(":", 1)[1]))

        elif act.startswith("EXE:"):
            exe_path = act.split(":", 1)[1]
            if os.path.exists(exe_path):
                self._launch(os.startfile, exe_path)

        elif act.startswith("CMD:"):
            self._launch(subprocess.Popen, act.split(":", 1)[1], shell=True)

        elif act.startswith("EXT:"):
            parts = act.split(":")
            ws = getattr(self.app, "ws_thread", None)
            if ws is None:
                return
            if parts[1] == "YT_FWD":
                ws.send_command(f"YT_FWD:{parts[2] if len(parts) > 2 else '10'}")
            elif parts[1] == "YT_BACK":
                ws.send_command(f"YT_BACK:{parts[2] if len(parts) > 2 else '10'}")
            elif parts[1] == "YT_PLAYPAUSE":
                ws.send_command("YT_PLAYPAUSE")

    @staticmethod
    def _normalize_url(url):
        url = url.strip()
        if not url.lower().startswith(("http://", "https://")):
            url = "https://" + url
        return url

    def play_macro(self, events, key_id, stop_event, loop=False, cycle_delay=100):
        pressed_keys = set()
        try:
            while not stop_event.is_set():
                for e in events:
                    if stop_event.is_set():
                        return
                    if not isinstance(e, dict):
                        continue
                    etype = e.get("type")

                    if etype == "delay":
                        try:
                            val = float(e.get("val", 100))
                        except (TypeError, ValueError):
                            val = 100.0
                        delay_sec = val / 1000.0 if e.get("unit", "мс") == "мс" else val
                        delay_sec = max(0.001, delay_sec)
                        if stop_event.wait(timeout=delay_sec):
                            return

                    elif etype == "tap":
                        win_key_event(e["val"], "tap")
                    elif etype == "press":
                        win_key_event(e["val"], "press")
                        pressed_keys.add(e["val"])
                    elif etype == "release":
                        win_key_event(e["val"], "release")
                        pressed_keys.discard(e["val"])
                    elif etype == "hotkey":
                        win_hotkey(e["val"])
                    elif etype == "text":
                        send_unicode_text(e["val"])
                    elif etype == "move":
                        move_mouse_abs(e.get("x", 0), e.get("y", 0))

                if not loop:
                    break

                if cycle_delay > 0:
                    c_sec = max(0.001, cycle_delay / 1000.0)
                    if stop_event.wait(timeout=c_sec):
                        return

        except Exception:
            pass
        finally:
            for k in list(pressed_keys):
                win_key_event(k, "release")
            stop_event.set()
            with self._macros_lock:
                if self.running_macros.get(key_id) is stop_event:
                    self.running_macros.pop(key_id, None)
