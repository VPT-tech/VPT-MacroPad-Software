# action_executor.py
import os
import json
import time
import threading
import webbrowser
import subprocess
import ctypes
import pyautogui

from comtypes import CLSCTX_ALL, CoInitialize, CoUninitialize
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
from utils import (win_key_event, win_hotkey, win_hotkey_down, win_hotkey_up,
                   send_unicode_text, move_mouse_abs, set_monitor_brightness)

class ActionExecutor:
    def __init__(self, main_app):
        self.app = main_app
        self.running_macros = {}

        # Стан для Multi-Tap (Tap / Double Tap / Hold)
        self._btn_press_time = {}
        self._btn_hold_timers = {}
        self._btn_dtap_timers = {}
        self._btn_tap_counts = {}
        self._btn_hold_fired = set()
        self._btn_fast_path = set()

        # Стан для Temporary Layer Hold (Shift-режим профілів)
        self._temp_profile_holds = {}  # key -> previous_profile_idx

        # Таймінги обертання енкодерів для Encoder Acceleration
        self._enc_last_tick = {}

        # Асинхронна черга для миттєвої зміни гучності програм без фрізів UI
        self._pending_app_vols = {}
        self._vol_lock = threading.Lock()
        self._vol_event = threading.Event()
        self._vol_worker_thread = threading.Thread(target=self._app_vol_worker, daemon=True)
        self._vol_worker_thread.start()

        # Асинхронний воркер для плавного регулювання яскравості монітора
        self._pending_brightness = None
        self._br_lock = threading.Lock()
        self._br_event = threading.Event()
        self._br_worker_thread = threading.Thread(target=self._brightness_worker, daemon=True)
        self._br_worker_thread.start()

    def _app_vol_worker(self):
        CoInitialize()
        try:
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
                    except Exception:
                        pass
        finally:
            try:
                CoUninitialize()
            except Exception:
                pass

    def _brightness_worker(self):
        while True:
            self._br_event.wait()
            self._br_event.clear()
            while True:
                with self._br_lock:
                    if self._pending_brightness is None:
                        break
                    val = self._pending_brightness
                    self._pending_brightness = None
                try:
                    set_monitor_brightness(val)
                except Exception:
                    pass
                # Контролери моніторів по шині DDC/CI (I2C) потребують ~45 мс між пакетами
                time.sleep(0.045)

    def _get_enc_accel_multiplier(self, base_enc):
        """Розраховує множник прискорення крутилки залежно від швидкості обертання."""
        now = time.time()
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
            current_vol = self.app.volume_states.get("sys", 0.5) if hasattr(self.app, 'volume_states') else 0.5
            new_vol = min(1.0, current_vol + step) if is_r else max(0.0, current_vol - step)

            if hasattr(self.app, 'update_instant_vol'):
                self.app.update_instant_vol("sys", new_vol)

            for _ in range(extra_steps):
                win_key_event("volumeup" if is_r else "volumedown", "tap")

            if hasattr(self.app, 'trigger_osd'):
                self.app.trigger_osd("volume", "Гучність системи", new_vol, icon_text="🔊")

        elif act == "ENC:SCROLL":
            if extra_steps > 0:
                pyautogui.scroll(-140 * extra_steps if is_r else 140 * extra_steps)

        elif act == "ENC:BRIGHTNESS":
            step = 0.03 * accel
            current_br = self.app.volume_states.get("brightness", 0.7) if hasattr(self.app, 'volume_states') else 0.7
            new_br = min(1.0, current_br + step) if is_r else max(0.0, current_br - step)

            if hasattr(self.app, 'update_instant_vol'):
                self.app.update_instant_vol("brightness", new_br)

            with self._br_lock:
                self._pending_brightness = new_br
            self._br_event.set()

            if hasattr(self.app, 'trigger_osd'):
                self.app.trigger_osd("volume", "Яскравість монітора", new_br, icon_text="☀️")

        elif act == "ENC:ZOOM":
            combo = "ctrl+=" if is_r else "ctrl+-"
            steps = min(extra_steps, 2) if hw_already_fired else min(accel, 3)
            for _ in range(steps):
                win_hotkey(combo)

        elif act == "ENC:TIMELINE":
            k = "right" if is_r else "left"
            for _ in range(extra_steps):
                win_key_event(k, "tap")

        elif act == "ENC:BRUSH":
            k = "]" if is_r else "["
            for _ in range(extra_steps):
                win_key_event(k, "tap")

        elif act == "ENC:UNDO_REDO":
            if not hw_already_fired:
                win_hotkey("ctrl+y" if is_r else "ctrl+z")

        elif act.startswith("ENC:APP:"):
            step = 0.03 * accel
            target = act.split(":")[-1].lower()

            if not hasattr(self.app, 'volume_states'):
                return
            current_vol = self.app.volume_states.get("apps", {}).get(target, 0.5)
            new_vol = min(1.0, current_vol + step) if is_r else max(0.0, current_vol - step)

            if hasattr(self.app, 'update_instant_vol'):
                self.app.update_instant_vol(target, new_vol, is_app=True)

            with self._vol_lock:
                self._pending_app_vols[target] = new_vol
            self._vol_event.set()

            if hasattr(self.app, 'trigger_osd'):
                clean_app = target.replace(".exe", "").capitalize()
                self.app.trigger_osd("volume", f"Гучність: {clean_app}", new_vol, icon_text="🎚", app_exe=target)

    def execute(self, raw):
        try:
            is_pressed = "_PRESSED" in raw
            is_released = "_RELEASED" in raw

            if "RIGHT" in raw or "LEFT" in raw:
                is_r = "RIGHT" in raw
                base_enc = raw.replace("_RIGHT", "").replace("_LEFT", "").strip()
                rot_key = f"{base_enc}_R" if is_r else f"{base_enc}_L"
                accel = self._get_enc_accel_multiplier(base_enc)

                rot_act = self.app.get_action(rot_key)
                center_act = self.app.get_enc_active_action(base_enc) if hasattr(self.app, 'get_enc_active_action') else self.app.get_action(base_enc)
                hw_handled_dir = self.app.is_enc_dir_hw_handled(base_enc, is_r) if hasattr(self.app, 'is_enc_dir_hw_handled') else False

                # 1. Виконуємо дію бокової стрілки (якщо призначена)
                if rot_act and rot_act != "NONE":
                    if rot_act.startswith("ENC:"):
                        self.execute_rotation_action(rot_act, is_r, accel, hw_already_fired=hw_handled_dir)
                    elif not hw_handled_dir:
                        self.execute_btn_action(rot_act, rot_key, is_pressed=True, is_released=True)

                # 2. Виконуємо дію центра крутилки (з підтримкою Smart Dial режимів)
                if center_act and center_act != "NONE":
                    if center_act.startswith("ENC:"):
                        self.execute_rotation_action(center_act, is_r, accel, hw_already_fired=hw_handled_dir)
                    elif not hw_handled_dir:
                        self.execute_btn_action(center_act, base_enc, is_pressed=True, is_released=True)
                return

            if is_pressed or is_released:
                key = raw.replace("_PRESSED", "").replace("_RELEASED", "").strip()
                self._handle_button_event(key, is_pressed, is_released)

        except Exception:
            pass

    def _handle_button_event(self, key, is_pressed, is_released):
        """Машина станів Tap / Double-Tap / Hold (>300 мс) + Temporary Layer Hold."""
        if is_released and key in self._temp_profile_holds:
            prev_idx = self._temp_profile_holds.pop(key)
            profiles = self.app.config.get("PROFILES", [])
            if 0 <= prev_idx < len(profiles):
                self.app.request_profile_switch(prev_idx, from_hotkey=True, is_temp_hold=False)
            self._btn_hold_fired.discard(key)
            self._btn_fast_path.discard(key)
            return

        triggers = self.app.get_button_triggers(key) if hasattr(self.app, 'get_button_triggers') else {
            "tap": self.app.get_action(key), "dtap": "NONE", "hold": "NONE"
        }
        tap_act = triggers.get("tap", "NONE")
        dtap_act = triggers.get("dtap", "NONE")
        hold_act = triggers.get("hold", "NONE")

        # Якщо всі слоти кнопки виконуються апаратно на RP2040 — показуємо лише OSD для MED:MUTE
        if self.app.is_button_fully_hw(key):
            if is_pressed and tap_act == "MED:MUTE" and dtap_act == "NONE" and hold_act == "NONE":
                self._show_sys_mute_osd()
            return

        has_multi = (dtap_act != "NONE") or (hold_act != "NONE")

        if not has_multi:
            if tap_act != "NONE":
                if is_pressed:
                    self._btn_fast_path.add(key)
                elif is_released:
                    self._btn_fast_path.discard(key)
                self.execute_btn_action(tap_act, key, is_pressed=is_pressed, is_released=is_released)
            return

        if is_pressed:
            self._btn_press_time[key] = time.time()
            self._btn_hold_fired.discard(key)

            old_ht = self._btn_hold_timers.pop(key, None)
            if old_ht:
                old_ht.cancel()

            if hold_act != "NONE":
                ht = threading.Timer(0.30, self._on_hold_timeout, args=(key, hold_act))
                ht.daemon = True
                self._btn_hold_timers[key] = ht
                ht.start()

        elif is_released:
            ht = self._btn_hold_timers.pop(key, None)
            if ht:
                ht.cancel()

            if key in self._btn_fast_path:
                self._btn_fast_path.discard(key)
                self.execute_btn_action(tap_act, key, is_pressed=False, is_released=True)
                return

            if key in self._btn_hold_fired:
                self._btn_hold_fired.discard(key)
                self.execute_btn_action(hold_act, key, is_pressed=False, is_released=True)
                return

            # Короткий клік (< 300 мс)
            if dtap_act == "NONE":
                if tap_act != "NONE":
                    self._fire_instant_tap(tap_act, key)
            else:
                cnt = self._btn_tap_counts.get(key, 0) + 1
                self._btn_tap_counts[key] = cnt
                old_dt = self._btn_dtap_timers.pop(key, None)
                if old_dt:
                    old_dt.cancel()

                if cnt >= 2:
                    self._btn_tap_counts[key] = 0
                    self._fire_instant_tap(dtap_act, key)
                else:
                    dt = threading.Timer(0.22, self._on_dtap_timeout, args=(key, tap_act))
                    dt.daemon = True
                    self._btn_dtap_timers[key] = dt
                    dt.start()

    def _show_sys_mute_osd(self):
        new_mute = not self.app.mute_states.get("sys", False)
        self.app.mute_states["sys"] = new_mute
        if hasattr(self.app, 'trigger_osd'):
            self.app.trigger_osd("status", "Звук вимкнено" if new_mute else "Звук увімкнено", is_danger=new_mute, icon_text="🔇" if new_mute else "🔊")

    def _on_hold_timeout(self, key, hold_act):
        self._btn_hold_fired.add(key)
        self._btn_tap_counts[key] = 0
        old_dt = self._btn_dtap_timers.pop(key, None)
        if old_dt:
            old_dt.cancel()
        self.execute_btn_action(hold_act, key, is_pressed=True, is_released=False)

    def _on_dtap_timeout(self, key, tap_act):
        if self._btn_tap_counts.get(key, 0) == 1:
            self._btn_tap_counts[key] = 0
            if tap_act != "NONE":
                self._fire_instant_tap(tap_act, key)

    def _fire_instant_tap(self, act, key):
        self.execute_btn_action(act, key, is_pressed=True, is_released=False)
        if act.startswith("HOTKEY:") or act.startswith("MACRO:") or act.startswith("SYS:PROFILE_HOLD:"):
            time.sleep(0.015)
            self.execute_btn_action(act, key, is_pressed=False, is_released=True)

    def execute_btn_action(self, act, key, is_pressed=True, is_released=False):
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

                mode = m_data.get("mode", "One Shot")
                events = m_data.get("events", [])
                c_delay = m_data.get("cycle_delay", 100)

                active_event = self.running_macros.get(key)
                is_running = active_event is not None and not active_event.is_set()

                if is_pressed:
                    if mode == "One Shot":
                        if not is_running:
                            stop_ev = threading.Event()
                            self.running_macros[key] = stop_ev
                            threading.Thread(target=self.play_macro, args=(events, key, stop_ev, False, c_delay), daemon=True).start()
                    elif mode == "Repeat while held":
                        if not is_running:
                            stop_ev = threading.Event()
                            self.running_macros[key] = stop_ev
                            threading.Thread(target=self.play_macro, args=(events, key, stop_ev, True, c_delay), daemon=True).start()
                    elif mode == "Toggle":
                        if is_running:
                            active_event.set()
                            self.running_macros.pop(key, None)
                        else:
                            stop_ev = threading.Event()
                            self.running_macros[key] = stop_ev
                            threading.Thread(target=self.play_macro, args=(events, key, stop_ev, True, c_delay), daemon=True).start()
                if is_released:
                    if mode == "Repeat while held" and active_event is not None:
                        active_event.set()
                        self.running_macros.pop(key, None)

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
                    win_hotkey(combo)
                elif is_pressed:
                    win_hotkey_down(combo)
                elif is_released:
                    win_hotkey_up(combo)

            # 4. РАЗОВІ СИСТЕМНІ / МЕДІА / ЗАПУСКНІ ДІЇ
            elif is_pressed:
                if act == "ENC:MODE_TOGGLE":
                    base_enc = key.replace("_SW", "") if key.startswith("ENC_") else "ENC_1"
                    if hasattr(self.app, 'cycle_enc_mode'):
                        self.app.cycle_enc_mode(base_enc)

                elif act.startswith("MULTI:"):
                    g_name = act.split(":", 1)[1]
                    items = self.app.config.get("MULTI_LAUNCH", {}).get(g_name, [])

                    def launch_items(item_list):
                        for idx, item_data in enumerate(item_list):
                            action_str = item_data if isinstance(item_data, str) else item_data.get("action", "")
                            delay_val = 0.5 if isinstance(item_data, str) else item_data.get("delay", 0.5)
                            try:
                                if action_str.startswith("URL:"):
                                    url = action_str.split(":", 1)[1].strip()
                                    if not url.startswith("http"):
                                        url = "https://" + url
                                    webbrowser.open(url)
                                elif action_str.startswith("EXE:"):
                                    exe_path = action_str.split(":", 1)[1]
                                    if os.path.exists(exe_path):
                                        os.startfile(exe_path)
                            except Exception:
                                pass
                            if idx < len(item_list) - 1:
                                time.sleep(delay_val)

                    threading.Thread(target=launch_items, args=(items,), daemon=True).start()

                elif act.startswith("SYS:"):
                    parts = act.split(":")
                    code = parts[1]
                    if code == "TASK": win_hotkey('ctrl+shift+esc')
                    elif code == "DESKTOP": win_hotkey('win+d')
                    elif code == "SNIP": win_hotkey('win+shift+s')
                    elif code == "LOCK": win_hotkey('win+l')
                    elif code == "SLEEP": ctypes.windll.powrprof.SetSuspendState(False, False, False)
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
                    if code == "PLAY": win_key_event("playpause", "tap")
                    elif code == "NEXT": win_key_event("nexttrack", "tap")
                    elif code == "PREV": win_key_event("prevtrack", "tap")
                    elif code == "MUTE":
                        win_key_event("volumemute", "tap")
                        self._show_sys_mute_osd()
                    elif code == "VOL_UP": win_key_event("volumeup", "tap")
                    elif code == "VOL_DOWN": win_key_event("volumedown", "tap")
                    elif code == "MIC_MUTE":
                        CoInitialize()
                        try:
                            from pycaw.pycaw import EDataFlow, ERole
                            e = AudioUtilities.GetDeviceEnumerator()
                            d = e.GetDefaultAudioEndpoint(EDataFlow.eCapture.value, ERole.eMultimedia.value)
                            i = d.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                            vc = ctypes.cast(i, ctypes.POINTER(IAudioEndpointVolume))
                            new_state = 0 if vc.GetMute() != 0 else 1
                            vc.SetMute(new_state, None)
                            is_muted = (new_state == 1)
                            self.app.mute_states["mic"] = is_muted
                            if hasattr(self.app, 'trigger_osd'):
                                self.app.trigger_osd(
                                    "status",
                                    "Мікрофон вимкнено" if is_muted else "Мікрофон увімкнено",
                                    is_danger=is_muted,
                                    icon_text="🔇" if is_muted else "🎙"
                                )
                        except Exception:
                            pass
                        finally:
                            try: CoUninitialize()
                            except Exception: pass

                elif act.startswith("APP_MUTE:"):
                    target = act.split(":")[-1].lower()
                    CoInitialize()
                    try:
                        for s in AudioUtilities.GetAllSessions():
                            if s.Process and s.Process.name() and s.Process.name().lower() == target:
                                v = s.SimpleAudioVolume
                                new_state = 0 if v.GetMute() != 0 else 1
                                v.SetMute(new_state, None)
                                is_muted = (new_state == 1)
                                self.app.mute_states["apps"][target] = is_muted
                                if hasattr(self.app, 'trigger_osd'):
                                    clean_app = target.replace(".exe", "").capitalize()
                                    self.app.trigger_osd(
                                        "status",
                                        f"{clean_app}: Звук вимкнено" if is_muted else f"{clean_app}: Звук увімкнено",
                                        is_danger=is_muted,
                                        icon_text="🔇" if is_muted else "🔊",
                                        app_exe=target
                                    )
                    except Exception:
                        pass
                    finally:
                        try: CoUninitialize()
                        except Exception: pass

                elif act.startswith("TEXT:"):
                    text_to_type = act.split(":", 1)[1]
                    threading.Thread(target=send_unicode_text, args=(text_to_type,), daemon=True).start()

                elif act.startswith("URL:"):
                    url = act.split(":", 1)[1].strip()
                    if not url.startswith("http"):
                        url = "https://" + url
                    webbrowser.open(url)

                elif act.startswith("EXE:"):
                    exe_path = act.split(":", 1)[1]
                    if os.path.exists(exe_path):
                        os.startfile(exe_path)

                elif act.startswith("CMD:"):
                    subprocess.Popen(act.split(":", 1)[1], shell=True)

                elif act.startswith("EXT:"):
                    parts = act.split(":")
                    if parts[1] == "YT_FWD":
                        sec = parts[2] if len(parts) > 2 else "10"
                        self.app.ws_thread.send_command(f"YT_FWD:{sec}")
                    elif parts[1] == "YT_BACK":
                        sec = parts[2] if len(parts) > 2 else "10"
                        self.app.ws_thread.send_command(f"YT_BACK:{sec}")
                    elif parts[1] == "YT_PLAYPAUSE":
                        self.app.ws_thread.send_command("YT_PLAYPAUSE")
        except Exception:
            pass

    def play_macro(self, events, key_id, stop_event, loop=False, cycle_delay=100):
        pressed_keys = set()
        try:
            while not stop_event.is_set():
                for e in events:
                    if stop_event.is_set():
                        return

                    if e["type"] == "delay":
                        val = float(e.get("val", 100))
                        delay_sec = val / 1000.0 if e.get("unit", "мс") == "мс" else val
                        delay_sec = max(0.001, delay_sec)
                        if stop_event.wait(timeout=delay_sec):
                            return

                    elif e["type"] == "tap":
                        win_key_event(e["val"], "tap")
                    elif e["type"] == "press":
                        win_key_event(e["val"], "press")
                        pressed_keys.add(e["val"])
                    elif e["type"] == "release":
                        win_key_event(e["val"], "release")
                        pressed_keys.discard(e["val"])
                    elif e["type"] == "hotkey":
                        win_hotkey(e["val"])
                    elif e["type"] == "text":
                        send_unicode_text(e["val"])
                    elif e["type"] == "move":
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
            if self.running_macros.get(key_id) is stop_event:
                self.running_macros.pop(key_id, None)