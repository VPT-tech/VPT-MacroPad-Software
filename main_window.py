import os
import json
import time
import copy
import shutil
import threading
import webbrowser
import subprocess
import ctypes
import ctypes.wintypes
import pyautogui, keyboard

from PySide6.QtWidgets import (QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLabel, QStackedWidget, QScrollArea,
                             QFrame, QLineEdit, QFileDialog, QFileIconProvider,
                             QSystemTrayIcon, QMenu, QStyle, QMessageBox, QComboBox)
from PySide6.QtCore import Qt, Signal, QTimer, QFileInfo, QVariantAnimation, QEasingCurve, QEvent, QSize, QPoint
from PySide6.QtGui import QFont, QCursor, QIcon, QAction

from comtypes import CLSCTX_ALL, CoInitialize
from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

from updater import UpdaterThread, CheckUpdateThread
import updater as updater_mod

from config import *
from utils import win_key_event, win_hotkey, get_app_path
from threads import AudioScannerThread, SerialThread, WebSocketServerThread, MutePollerThread, ActiveWindowThread
from widgets import *
from action_executor import ActionExecutor
import icons
from icons import ICON_COLOR, ICON_MUTED, ICON_ACCENT, ICON_DANGER
import html

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

HW_BUTTON_IDS = [f"BTN_{i}" for i in range(1, 10)] + [f"ENC_{i}_SW" for i in range(1, 4)]
HW_SLOTS = (("tap", "TAP"), ("dtap", "DTAP"), ("hold", "HOLD"))


def sanitize_profile(prof, fallback_name="Профіль"):
    """Приводить профіль (з конфігу чи імпорту) до очікуваної структури.
    Повертає None, якщо це взагалі не профіль."""
    if not isinstance(prof, dict):
        return None
    name = prof.get("name")
    out = dict(prof)
    out["name"] = name.strip() if isinstance(name, str) and name.strip() else fallback_name
    out["app_bind"] = prof.get("app_bind", "") if isinstance(prof.get("app_bind", ""), str) else ""
    actions = {}
    raw_actions = prof.get("actions", {})
    if isinstance(raw_actions, dict):
        for k, v in raw_actions.items():
            if not isinstance(k, str):
                continue
            if isinstance(v, str):
                actions[k] = v
            elif isinstance(v, dict):
                slots = {sl: (v.get(sl) if isinstance(v.get(sl), str) else "NONE") for sl in ("tap", "dtap", "hold")}
                if any(x != "NONE" for x in slots.values()):
                    actions[k] = slots
    out["actions"] = actions
    enc_modes = {}
    raw_modes = prof.get("enc_modes", {})
    if isinstance(raw_modes, dict):
        for k, v in raw_modes.items():
            if isinstance(k, str) and isinstance(v, list):
                lst = [m for m in v if isinstance(m, str) and m and m != "NONE"]
                if lst:
                    enc_modes[k] = lst
    if enc_modes:
        out["enc_modes"] = enc_modes
    else:
        out.pop("enc_modes", None)
    return out

class RightPanel(QFrame):
    def __init__(self, main_app):
        super().__init__()
        self.main_app = main_app
        self.setStyleSheet("background: transparent;")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self.main_app, 'vkb_container') and self.main_app.vkb_container is not None:
            self.main_app.update_dynamic_layout()

class MacroPadPro(QMainWindow):
    osd_signal = Signal(str, str, float, str, bool, str)
    profile_switch_signal = Signal(int, bool, bool)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("VPT | Pad")
        try:
            CoInitialize()
        except Exception:
            pass

        self.resize(1200, 750)
        self.setMinimumSize(1000, 650)

        self.active_profile_idx = 0
        self.ui_profiles = []
        self._enc_mode_by_prof = {}

        # Синхронізація з платою: що вже відправлено (тіньова копія) + відкладений flush
        self._hw_shadow = {}
        self._hw_save_pending = False
        self.device_connected = False
        self.hw_proto = 1
        self.fw_version = ""
        self._flashing = False
        self._hw_sync_timer = QTimer(self)
        self._hw_sync_timer.setSingleShot(True)
        self._hw_sync_timer.setInterval(40)
        self._hw_sync_timer.timeout.connect(self._flush_hw_sync)

        self.config = self.load_config()
        self.selected_btn = None
        self.staged_val = None
        self.staged_name = None
        self.ui_pad_btns = {}
        self.all_action_btns = []
        self.scrolls = []
        self.icon_provider = QFileIconProvider()

        self.executor = ActionExecutor(self)
        self.active_vkb_keys = []
        self.listening_action = None

        self.tooltip = AnimatedToolTip()
        self.osd = OSDOverlay(self)
        self.osd_signal.connect(self._show_osd_slot)
        self.profile_switch_signal.connect(self.switch_profile)
        self.current_trigger_type = "tap"  # "tap", "dtap", "hold"
        self.volume_states = {"sys": 0.5, "mic": 0.5, "brightness": 0.7, "apps": {}}
        self.mute_states = {"sys": False, "mic": False, "apps": {}}

        self.build_ui()
        self.drag_overlay = FloatingDragOverlay(self)
        self.centralWidget().installEventFilter(self)
        self.left_panel.installEventFilter(self)
        self.right_panel.installEventFilter(self)

        for s in self.scrolls:
            s.viewport().installEventFilter(self)

        self.win_tracker = ActiveWindowThread()
        self.win_tracker.app_changed.connect(self.handle_app_changed)
        self.win_tracker.start()

        self.mute_poller = MutePollerThread()
        self.mute_poller.states_updated.connect(self.update_mute_states)
        self.mute_poller.start()

        self.ws_thread = WebSocketServerThread()
        self.ws_thread.start()

        self.serial_thread = SerialThread()
        self.serial_thread.status_signal.connect(self.update_status)
        self.serial_thread.link_signal.connect(self.on_link_changed)
        # executor — QObject у GUI-потоці, тож з'єднання автоматично queued:
        # уся обробка подій відбувається в GUI-потоці
        self.serial_thread.macro_signal.connect(self.executor.execute)
        self.serial_thread.start()

        self.setup_tray()
        self.run_silent_update_check()

        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.run_silent_update_check)
        self.update_timer.start(86400000)

    def request_profile_switch(self, idx, from_hotkey=False, is_temp_hold=False):
        """Потокобезпечний запит на перемикання профілю з будь-якого потоку."""
        self.profile_switch_signal.emit(int(idx), bool(from_hotkey), bool(is_temp_hold))

    def trigger_osd(self, mode, title, val=0.0, icon_text="volume", is_danger=False, app_exe=""):
        self.osd_signal.emit(mode, title, float(val), icon_text, bool(is_danger), app_exe or "")

    def _show_osd_slot(self, mode, title, val, icon_text, is_danger, app_exe):
        app_icon = None
        if app_exe:
            path = get_app_path(app_exe)
            if path and os.path.exists(path):
                app_icon = self.icon_provider.icon(QFileInfo(path))
        self.osd.show_osd(mode, title, val, icon_text, is_danger, app_icon)

    def is_hw_handled(self, act_str):
        return action_to_hid_spec(act_str).startswith("HID_")

    def is_button_fully_hw(self, bid):
        triggers = self.get_button_triggers(bid)
        vals = [v for v in triggers.values() if v != "NONE"]
        if not vals:
            return False
        return all(self.is_hw_handled(v) for v in vals)

    def _get_enc_dir_hid_spec(self, base_enc, is_right):
        """Визначає HID-специфікацію для напрямку обертання енкодера (бокова дія або центр)."""
        sfx = "_R" if is_right else "_L"
        side_act = self.get_action(f"{base_enc}{sfx}")
        center_act = self.get_enc_active_action(base_enc)

        # Якщо одночасно задані і бокова дія, і центральна — обробляємо через ПК (SERIAL)
        if side_act != "NONE" and center_act != "NONE":
            return "SERIAL"
        if side_act != "NONE":
            return encoder_action_to_hid_spec(side_act, is_right)
        if center_act != "NONE":
            return encoder_action_to_hid_spec(center_act, is_right)
        return "NONE"

    def is_enc_dir_hw_handled(self, base_enc, is_right):
        return self._get_enc_dir_hid_spec(base_enc, is_right).startswith("HID_")

    def compute_hw_specs(self):
        """Повна апаратна конфігурація поточного профілю: {ціль SET_KEY: spec}."""
        specs = {}
        for bid in HW_BUTTON_IDS:
            tr = self.get_button_triggers(bid)
            # Прошивка не вміє змішувати HID і SERIAL в одній кнопці: якщо хоч один слот
            # потребує ПК — кнопку повністю обробляє ПК.
            any_serial = any(action_to_hid_spec(v) == "SERIAL" for v in tr.values() if v != "NONE")
            for slot_key, slot_name in HW_SLOTS:
                val = tr.get(slot_key, "NONE")
                specs[f"{bid}:{slot_name}"] = "SERIAL" if (any_serial and val != "NONE") else action_to_hid_spec(val)
        for i in range(1, 4):
            base_enc = f"ENC_{i}"
            specs[f"{base_enc}_L"] = self._get_enc_dir_hid_spec(base_enc, False)
            specs[f"{base_enc}_R"] = self._get_enc_dir_hid_spec(base_enc, True)
        return specs

    def sync_hardware_bindings(self, save_eeprom=False, immediate=False):
        """Планує відправку конфігурації поточного профілю на плату RP2040.
        Кілька змін поспіль зливаються в одну відправку; надсилаються лише змінені рядки."""
        if save_eeprom:
            self._hw_save_pending = True
        if immediate:
            self._hw_sync_timer.stop()
            self._flush_hw_sync()
        else:
            self._hw_sync_timer.start()

    def _flush_hw_sync(self, force=False):
        st = getattr(self, 'serial_thread', None)
        if st is None or not self.device_connected:
            return  # після підключення буде повна синхронізація (і SAVE_EEPROM, якщо він очікує)
        cmds = []
        for target, spec in self.compute_hw_specs().items():
            if force or self._hw_shadow.get(target) != spec:
                cmds.append(f"SET_KEY:{target}:{spec}")
                self._hw_shadow[target] = spec
        if self._hw_save_pending:
            cmds.append("SAVE_EEPROM")
            self._hw_save_pending = False
        st.send_commands(cmds)

    def on_link_changed(self, connected, proto, fw_version, reset_reason=""):
        self.device_connected = bool(connected)
        self.hw_proto = proto
        self.fw_version = fw_version
        if connected:
            self._hw_shadow.clear()
            self._hw_sync_timer.stop()
            self._flush_hw_sync(force=True)
            fw = fw_version or "≤ 1.0"
            tip = f"Прошивка: {fw}  •  протокол v{proto}"
            if reset_reason == "WDT":
                # Апаратний watchdog перезапустив плату після зависання. Прив'язки вже
                # відновлено повною синхронізацією вище — лише повідомляємо користувача.
                self.last_board_reset = time.strftime("%H:%M:%S")
                tip += f"\nПлата перезапускалась після зависання (watchdog), {self.last_board_reset}"
                msg = "Макропад перезапустився після зависання (watchdog). Налаштування відновлено."
                try:
                    self.tray_icon.showMessage("VPT | Pad", msg, QSystemTrayIcon.MessageIcon.Warning, 6000)
                except Exception:
                    pass
                self.trigger_osd("status", "Плату перезапущено (watchdog)", is_danger=True, icon_text="warning")
            self.lbl_status.setToolTip(tip)
        else:
            self._hw_shadow.clear()
            self.lbl_status.setToolTip("")
            # Плата зникла під час утримання кнопки — відпускаємо все, що тримає ПК
            self.executor.on_device_disconnected()

    def run_silent_update_check(self):
        if getattr(self, 'bg_updater', None) is not None and self.bg_updater.isRunning():
            return
        self.bg_updater = CheckUpdateThread()
        self.bg_updater.update_found_signal.connect(self.show_update_button)
        self.bg_updater.start()

    def _set_update_btn(self, text, icon_name=None, color=ICON_MUTED):
        self.btn_update.setText(text)
        self.btn_update.setIcon(icons.icon(icon_name, color) if icon_name else QIcon())
        self.btn_update.setIconSize(QSize(18, 18))

    def show_update_button(self, version):
        self._set_update_btn(f"Доступна версія {version}", "download", ICON_ACCENT)
        self.btn_update.setStyleSheet(f"""
            QPushButton {{ background-color: {BG_HOVER}; color: {ACCENT}; border: 1px solid {ACCENT}; border-radius: 5px; font-weight: bold; padding: 5px; }}
            QPushButton:hover {{ background-color: {ACCENT}; color: {BG_MAIN}; }}
        """)
        self.btn_update.show()
        self.update_dynamic_layout()

    def check_for_updates(self):
        if hasattr(self, 'updater') and self.updater.isRunning():
            return

        self._set_update_btn("Завантаження...", "clock")
        self.btn_update.setDisabled(True)

        self.updater = UpdaterThread()
        self.updater.status_signal.connect(self.update_btn_status)
        self.updater.update_ready_signal.connect(self.prompt_update)
        self.updater.start()

    def update_btn_status(self, text):
        self.btn_update.setText(text)
        if "Немає" in text or "Помилка" in text or "остання" in text or "підключено" in text:
            QTimer.singleShot(3000, lambda: self.reset_update_btn())

    def reset_update_btn(self):
        self._set_update_btn("Оновити ПЗ", "refresh")
        self.btn_update.setDisabled(False)

    def prompt_update(self, exe_path, uf2_path):
        self._set_update_btn("Оновлення готове", "check", "#00ff66")

        msg = QMessageBox(self)
        msg.setWindowTitle("Оновлення доступне")

        if exe_path and uf2_path:
            text = "Знайдено нову версію програми та прошивки.\nМакропад буде автоматично перезавантажено.\nОновити зараз?"
        elif exe_path:
            text = "Знайдено нову версію програми.\nОновити зараз?"
        elif uf2_path:
            text = "Знайдено нову версію прошивки.\nМакропад буде автоматично перезавантажено.\nОновити зараз?"
        else:
            self.reset_update_btn()
            return

        msg.setText(text)
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setStyleSheet(f"background-color: {BG_MAIN}; color: {TEXT_MAIN};")

        if msg.exec() == QMessageBox.StandardButton.Yes:
            self.apply_update(exe_path, uf2_path)
        else:
            self.reset_update_btn()

    def apply_update(self, exe_path, uf2_path):
        if uf2_path and not updater_mod.is_verified(uf2_path):
            self.lbl_status.setText("Прошивка не пройшла перевірку SHA-256")
            uf2_path = ""
        if uf2_path:
            self._flashing = True
            self.lbl_status.setText("Прошивка плати...")
            self.serial_thread.send_command("ENTER_BOOTLOADER")

            self.pico_attempts = 0
            self.pico_flash_timer = QTimer(self)

            def check_drive():
                self.pico_attempts += 1
                pico_drive = None
                for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                    drive = f"{letter}:\\"
                    if os.path.exists(os.path.join(drive, "INFO_UF2.TXT")):
                        pico_drive = drive
                        break

                if pico_drive:
                    self.pico_flash_timer.stop()
                    self._flashing = False
                    flashed = False
                    try:
                        dest_file = os.path.join(pico_drive, os.path.basename(uf2_path))
                        with open(uf2_path, 'rb') as f_src:
                            content = f_src.read()
                        # Перевіряємо саме ті байти, які пишемо на плату (без вікна для підміни файлу)
                        expected = updater_mod.expected_sha256_for_path(uf2_path)
                        if expected and updater_mod.sha256_bytes(content) == expected:
                            with open(dest_file, 'wb') as f_dst:
                                f_dst.write(content)
                                f_dst.flush()
                            flashed = True
                    except Exception:
                        pass

                    self.lbl_status.setText("Прошивку оновлено!" if flashed else "Прошивку не записано")
                    if exe_path and os.path.exists(exe_path):
                        QTimer.singleShot(2000, lambda: self.run_exe_update(exe_path))

                elif self.pico_attempts >= 30:
                    self.pico_flash_timer.stop()
                    self._flashing = False
                    self.serial_thread.clear_queue()
                    self.lbl_status.setText("Помилка: плату не знайдено")
                    if exe_path and os.path.exists(exe_path):
                        self.run_exe_update(exe_path)

            self.pico_flash_timer.timeout.connect(check_drive)
            self.pico_flash_timer.start(1000)

        elif exe_path and os.path.exists(exe_path):
            self.run_exe_update(exe_path)

    def run_exe_update(self, exe_path):
        from PySide6.QtWidgets import QApplication
        if not updater_mod.is_verified(exe_path):
            # Файл змінився після завантаження (або не мав контрольної суми) — з правами
            # адміністратора такий файл не запускаємо
            self._set_update_btn("Інсталятор не пройшов перевірку", "warning", ICON_DANGER)
            QTimer.singleShot(4000, self.reset_update_btn)
            return
        params = "/VERYSILENT /SUPPRESSMSGBOXES /FORCECLOSEAPPLICATIONS"
        res = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe_path, params, None, 1)
        if int(res) <= 32:
            # Користувач відхилив UAC або запуск не вдався — програма НЕ закривається
            self._set_update_btn("Оновлення скасовано", "warning", ICON_DANGER)
            QTimer.singleShot(3000, self.reset_update_btn)
            return
        self.quit_app()

    def handle_app_changed(self, exe_name):
        if not self.config.get("auto_profile_switch", True):
            return

        profiles = self.config.get("PROFILES", [])
        target_idx = -1
        for i, prof in enumerate(profiles):
            bind = prof.get("app_bind", "").lower()
            if bind and bind == exe_name:
                target_idx = i
                break

        if target_idx != -1:
            if self.active_profile_idx != target_idx:
                if not getattr(self, 'is_in_auto_profile', False):
                    self.fallback_profile_idx = self.active_profile_idx

                self.is_in_auto_profile = True
                self.switch_profile(target_idx, from_hotkey=True)
        else:
            if getattr(self, 'is_in_auto_profile', False):
                fallback = getattr(self, 'fallback_profile_idx', 0)
                if fallback < len(profiles) and fallback != self.active_profile_idx:
                    self.switch_profile(fallback, from_hotkey=True)
                self.is_in_auto_profile = False

    def cleanup_threads(self):
        try:
            self.executor.shutdown()
        except Exception:
            pass
        thread_attrs = ('win_tracker', 'mute_poller', 'serial_thread', 'ws_thread', 'scanner', 'bg_updater', 'updater')
        for attr in thread_attrs:
            t = getattr(self, attr, None)
            if t is not None and hasattr(t, 'stop'):
                try:
                    t.stop()
                except Exception:
                    pass
        # 400 мс не вистачало (readline з таймаутом 0.35 с + sleep 0.5 с у SerialThread):
        # QThread, знищений під час роботи, аварійно завершує процес при виході.
        deadline = time.monotonic() + 2.5
        for attr in thread_attrs:
            t = getattr(self, attr, None)
            if t is None:
                continue
            try:
                left_ms = max(50, int((deadline - time.monotonic()) * 1000))
                if not t.wait(left_ms):
                    t.terminate()
                    t.wait(200)
            except Exception:
                pass

    def update_mute_states(self, sys_mic_mute, apps_mute, sys_mic_vol, apps_vol):
        self.mute_states["sys"] = sys_mic_mute.get("sys", False)
        self.mute_states["mic"] = sys_mic_mute.get("mic", False)
        self.mute_states["apps"] = apps_mute

        if not hasattr(self, 'volume_states'):
            self.volume_states = {"sys": 0.0, "mic": 0.0, "brightness": 0.7, "apps": {}}

        if time.time() - getattr(self, 'last_local_vol_time', 0) > 0.5:
            self.volume_states["sys"] = sys_mic_vol.get("sys", 0.0)
            self.volume_states["mic"] = sys_mic_vol.get("mic", 0.0)
            self.volume_states["apps"] = apps_vol

        for btn in self.ui_pad_btns.values():
            btn.update()

    def update_instant_vol(self, target, vol, is_app=False):
        if not hasattr(self, 'volume_states'):
            self.volume_states = {"sys": 0.0, "mic": 0.0, "brightness": 0.7, "apps": {}}

        self.last_local_vol_time = time.time()

        if is_app:
            self.volume_states["apps"][target] = vol
        else:
            self.volume_states[target] = vol

        for btn in self.ui_pad_btns.values():
            btn.update()

    def load_config(self):
        config_data = None

        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    config_data = json.load(f)
            except Exception:
                pass

        backup_file = CONFIG_FILE + ".bak"
        if not config_data and os.path.exists(backup_file):
            try:
                with open(backup_file, "r", encoding="utf-8") as f:
                    config_data = json.load(f)
            except Exception:
                pass

        if not config_data:
            default_profiles = [copy.deepcopy(p) for p in BUILTIN_PRESETS.values()]
            config_data = {
                "RECENTS": {"EXE": [], "URL": [], "TEXT": []},
                "MACROS": {},
                "MULTI_LAUNCH": {},
                "PROFILES": default_profiles,
                "show_osd": True,
                "auto_profile_switch": True
            }

        if "RECENTS" not in config_data: config_data["RECENTS"] = {"EXE": [], "URL": [], "TEXT": []}
        if "TEXT" not in config_data["RECENTS"]: config_data["RECENTS"]["TEXT"] = []
        if "MACROS" not in config_data: config_data["MACROS"] = {}
        if "MULTI_LAUNCH" not in config_data: config_data["MULTI_LAUNCH"] = {}
        if not isinstance(config_data.get("RECENTS"), dict): config_data["RECENTS"] = {}
        for rk in ("EXE", "URL", "TEXT"):
            if not isinstance(config_data["RECENTS"].get(rk), list):
                config_data["RECENTS"][rk] = []
        if not isinstance(config_data.get("MACROS"), dict): config_data["MACROS"] = {}
        if not isinstance(config_data.get("MULTI_LAUNCH"), dict): config_data["MULTI_LAUNCH"] = {}
        # Пошкоджений профіль (без name/actions) раніше валив програму на старті (KeyError)
        raw_profiles = config_data.get("PROFILES")
        profiles = []
        if isinstance(raw_profiles, list):
            for i, p in enumerate(raw_profiles):
                sp = sanitize_profile(p, f"Профіль {i + 1}")
                if sp is not None:
                    profiles.append(sp)
        if not profiles:
            profiles = [copy.deepcopy(p) for p in BUILTIN_PRESETS.values()]
        config_data["PROFILES"] = profiles
        if "show_osd" not in config_data: config_data["show_osd"] = True

        return config_data

    def save_config(self):
        temp_file = CONFIG_FILE + ".tmp"
        backup_file = CONFIG_FILE + ".bak"
        try:
            if os.path.exists(CONFIG_FILE):
                shutil.copy(CONFIG_FILE, backup_file)

            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=4, ensure_ascii=False)
            os.replace(temp_file, CONFIG_FILE)
        except Exception:
            pass
        self.refresh_pad_dots()

    def get_button_triggers(self, bid):
        profiles = self.config.get("PROFILES", [])
        if not profiles or self.active_profile_idx >= len(profiles):
            return {"tap": "NONE", "dtap": "NONE", "hold": "NONE"}
        raw = profiles[self.active_profile_idx].get("actions", {}).get(bid, "NONE")
        if isinstance(raw, dict):
            return {
                "tap": raw.get("tap", "NONE"),
                "dtap": raw.get("dtap", "NONE"),
                "hold": raw.get("hold", "NONE")
            }
        return {"tap": raw if raw else "NONE", "dtap": "NONE", "hold": "NONE"}

    def get_action(self, bid, trigger=None):
        profiles = self.config.get("PROFILES", [])
        if not profiles or self.active_profile_idx >= len(profiles):
            return "NONE"
        raw = profiles[self.active_profile_idx].get("actions", {}).get(bid, "NONE")
        if isinstance(raw, dict):
            t = trigger if trigger else "tap"
            return raw.get(t, "NONE")
        if trigger in ("dtap", "hold"):
            return "NONE"
        return raw if raw else "NONE"

    def set_action(self, bid, val, trigger=None, commit=True):
        profiles = self.config.get("PROFILES", [])
        if not profiles or self.active_profile_idx >= len(profiles):
            return

        prof = profiles[self.active_profile_idx]
        is_multi_btn = bid.startswith("BTN_") or bid.endswith("_SW")
        is_center_enc = bid in ("ENC_1", "ENC_2", "ENC_3")
        t_slot = trigger if trigger else getattr(self, 'current_trigger_type', 'tap')

        if is_multi_btn:
            cur = self.get_button_triggers(bid)
            cur[t_slot] = val
            if all(v == "NONE" for v in cur.values()):
                prof.get("actions", {}).pop(bid, None)
            else:
                prof.setdefault("actions", {})[bid] = cur
        else:
            if val != "NONE":
                prof.setdefault("actions", {})[bid] = val
            else:
                prof.get("actions", {}).pop(bid, None)

            # Пряме призначення на центр крутилки оновлює список Smart Dial
            if is_center_enc:
                self.enc_mode_indices[bid] = 0
                if "enc_modes" in prof and bid in prof["enc_modes"]:
                    if val == "NONE":
                        del prof["enc_modes"][bid]
                    else:
                        prof["enc_modes"][bid] = [val]

        if commit:
            self.save_config()
            self.sync_hardware_bindings(save_eeprom=True)
            self.refresh_pad_dots()
            if self.selected_btn == bid:
                self.update_assign_ui()

    @property
    def enc_mode_indices(self):
        """Поточні режими Smart Dial — окремо для кожного профілю
        (раніше індекс з одного профілю переносився в інший)."""
        profiles = self.config.get("PROFILES", [])
        if not profiles or self.active_profile_idx >= len(profiles):
            return {}
        return self._enc_mode_by_prof.setdefault(id(profiles[self.active_profile_idx]), {})

    def get_enc_modes(self, base_enc):
        profiles = self.config.get("PROFILES", [])
        if not profiles or self.active_profile_idx >= len(profiles):
            return []
        prof = profiles[self.active_profile_idx]
        modes = prof.get("enc_modes", {}).get(base_enc, [])
        primary = self.get_action(base_enc)
        if not modes and primary != "NONE":
            return [primary]
        return modes

    def get_enc_active_action(self, base_enc):
        modes = self.get_enc_modes(base_enc)
        if not modes:
            return self.get_action(base_enc)
        idx = self.enc_mode_indices.get(base_enc, 0) % len(modes)
        return modes[idx]

    def add_enc_smart_mode(self, base_enc, act_val):
        profiles = self.config.get("PROFILES", [])
        if not profiles or self.active_profile_idx >= len(profiles):
            return
        prof = profiles[self.active_profile_idx]
        if "enc_modes" not in prof:
            prof["enc_modes"] = {}
        modes = list(self.get_enc_modes(base_enc))
        if act_val not in modes:
            modes.append(act_val)
        prof["enc_modes"][base_enc] = modes
        if self.get_action(base_enc) == "NONE":
            prof.setdefault("actions", {})[base_enc] = modes[0]
        if self.get_action(f"{base_enc}_SW", "tap") == "NONE":
            self.set_action(f"{base_enc}_SW", "ENC:MODE_TOGGLE", "tap", commit=False)
        self.save_config()
        self.sync_hardware_bindings(save_eeprom=True)
        self.refresh_pad_dots()

    def clear_enc_smart_modes(self, base_enc):
        profiles = self.config.get("PROFILES", [])
        if not profiles or self.active_profile_idx >= len(profiles):
            return
        prof = profiles[self.active_profile_idx]
        if "enc_modes" in prof and base_enc in prof["enc_modes"]:
            del prof["enc_modes"][base_enc]
        self.enc_mode_indices[base_enc] = 0
        self.save_config()
        # Активна дія центру могла змінитись — плата має про це дізнатись
        self.sync_hardware_bindings(save_eeprom=True)
        self.refresh_pad_dots()

    def cycle_enc_mode(self, base_enc):
        modes = self.get_enc_modes(base_enc)
        if not modes:
            return
        new_idx = (self.enc_mode_indices.get(base_enc, 0) + 1) % len(modes)
        self.enc_mode_indices[base_enc] = new_idx
        active_act = modes[new_idx]
        enc_num = base_enc.replace("ENC_", "")
        self.trigger_osd("profile", f"Крутилка {enc_num}: {self.get_fname(active_act)}", icon_text="dial")
        self.sync_hardware_bindings(save_eeprom=False, immediate=True)
        if base_enc in self.ui_pad_btns:
            self.ui_pad_btns[base_enc].update()

    def get_btn_tooltip(self, bid):
        tr = self.get_button_triggers(bid)
        parts = []
        # Кольори маркерів збігаються з точками на кнопках макета та кнопками режимів
        for slot, label, color in (("tap", "Клік", "#ffffff"), ("dtap", "2x Клік", "#ffaa00"), ("hold", "Утримання", "#b366ff")):
            if tr[slot] != "NONE":
                parts.append(f"<span style='color:{color}'>●</span>&nbsp;{label}: {html.escape(self.get_fname(tr[slot]))}")
        return "&nbsp;&nbsp;&nbsp;".join(parts)

    def get_enc_tooltip(self, base_enc):
        modes = self.get_enc_modes(base_enc)
        if len(modes) > 1:
            idx = self.enc_mode_indices.get(base_enc, 0) % len(modes)
            names = [f"<b style='color:{ACCENT}'>{html.escape(self.get_fname(m))}</b>" if i == idx
                     else html.escape(self.get_fname(m)) for i, m in enumerate(modes)]
            return "Smart Dial: " + " ➔ ".join(names)
        val = self.get_action(base_enc)
        return self.get_fname(val) if val != "NONE" else ""

    def refresh_pad_dots(self):
        for bid, btn in self.ui_pad_btns.items():
            if isinstance(btn, EncoderCompoundWidget):
                btn.update()
            else:
                tr = self.get_button_triggers(bid)
                btn.set_has_action(any(v != "NONE" for v in tr.values()))

    def refresh_profiles_ui(self):
        while self.profiles_layout.count():
            item = self.profiles_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        self.ui_profiles = []
        profiles = self.config.get("PROFILES", [])

        for i, prof in enumerate(profiles):
            from widgets import ProfileWidget
            w = ProfileWidget(i, prof["name"], self, self.profiles_container)
            w.clicked.connect(self.switch_profile)
            self.profiles_layout.addWidget(w, alignment=Qt.AlignmentFlag.AlignRight)
            self.ui_profiles.append(w)
            if i == self.active_profile_idx:
                w.set_active(True)

        self.btn_add_profile = QPushButton("+")
        self.btn_add_profile.setObjectName("addProfileBtn")
        self.btn_add_profile.setFixedSize(40, 40)
        self.btn_add_profile.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_add_profile.clicked.connect(self.add_profile)
        self.profiles_layout.addWidget(self.btn_add_profile, alignment=Qt.AlignmentFlag.AlignRight)

        self.profiles_layout.addStretch()
        if hasattr(self, 'refresh_profile_combos'):
            self.refresh_profile_combos()
        self.update_dynamic_layout()

    def add_profile(self):
        profiles = self.config.get("PROFILES", [])
        new_name = f"Профіль {len(profiles) + 1}"
        profiles.append({"name": new_name, "actions": {}})
        self.config["PROFILES"] = profiles
        self.save_config()
        self.refresh_profiles_ui()
        self.switch_profile(len(profiles) - 1)

    def export_profile(self, idx):
        profiles = self.config.get("PROFILES", [])
        if not (0 <= idx < len(profiles)):
            return
        prof = profiles[idx]
        safe_name = "".join(c for c in prof.get("name", "profile") if c.isalnum() or c in (" ", "_", "-")).strip()
        path, _ = QFileDialog.getSaveFileName(self, "Експорт профілю", f"{safe_name}.json", "JSON Profile (*.json)")
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(prof, f, indent=4, ensure_ascii=False)
            except Exception:
                pass

    def import_profile(self):
        path, _ = QFileDialog.getOpenFileName(self, "Імпорт профілю", "", "JSON Profile (*.json)")
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    prof = json.load(f)
                prof = sanitize_profile(prof) if isinstance(prof, dict) and "actions" in prof else None
                if prof is not None:
                    self.config.setdefault("PROFILES", []).append(prof)
                    self.save_config()
                    self.refresh_profiles_ui()
                    self.switch_profile(len(self.config["PROFILES"]) - 1)
            except Exception:
                pass

    def rename_profile(self, idx, new_name):
        self.config["PROFILES"][idx]["name"] = new_name
        self.save_config()
        if hasattr(self, 'refresh_profile_combos'):
            self.refresh_profile_combos()

    def clear_profile(self, idx):
        profiles = self.config.get("PROFILES", [])
        if not profiles or idx >= len(profiles):
            return

        actions = profiles[idx].get("actions", {})
        new_actions = {}
        # Залишаємо дії навігації між профілями (у будь-якому слоті), щоб з профілю можна було вийти
        is_nav = lambda a: isinstance(a, str) and a.startswith("SYS:PROFILE_")
        for k, v in actions.items():
            if is_nav(v):
                new_actions[k] = v
            elif isinstance(v, dict):
                kept = {sl: (v.get(sl) if is_nav(v.get(sl)) else "NONE") for sl in ("tap", "dtap", "hold")}
                if any(x != "NONE" for x in kept.values()):
                    new_actions[k] = kept

        profiles[idx]["actions"] = new_actions
        profiles[idx].pop("enc_modes", None)
        self.save_config()
        self.sync_hardware_bindings(save_eeprom=True)

        if idx == self.active_profile_idx:
            self.refresh_pad_dots()
            self.update_assign_ui()

    def delete_profile(self, idx):
        profiles = self.config.get("PROFILES", [])
        if len(profiles) <= 1 or not (0 <= idx < len(profiles)):
            return
        profiles.pop(idx)

        # Коригуємо індекси в SYS:PROFILE_GOTO:X та SYS:PROFILE_HOLD:X у всіх профілях
        def fix_prof_ref(val_str):
            if not isinstance(val_str, str):
                return val_str
            for prefix in ("SYS:PROFILE_GOTO:", "SYS:PROFILE_HOLD:"):
                if val_str.startswith(prefix):
                    try:
                        t_idx = int(val_str.split(":")[-1])
                        if t_idx == idx:
                            return "NONE"
                        elif t_idx > idx:
                            return f"{prefix}{t_idx - 1}"
                    except ValueError:
                        pass
            return val_str

        for prof in profiles:
            actions = prof.get("actions", {})
            for k, v in list(actions.items()):
                if isinstance(v, dict):
                    for slot in ("tap", "dtap", "hold"):
                        v[slot] = fix_prof_ref(v.get(slot, "NONE"))
                    if all(sv == "NONE" for sv in v.values()):
                        del actions[k]
                else:
                    new_v = fix_prof_ref(v)
                    if new_v == "NONE":
                        del actions[k]
                    else:
                        actions[k] = new_v

        self.config["PROFILES"] = profiles
        if self.active_profile_idx > idx:
            self.active_profile_idx -= 1
        elif self.active_profile_idx == idx:
            self.active_profile_idx = max(0, idx - 1)
        self.active_profile_idx = min(self.active_profile_idx, len(profiles) - 1)
        # Збережені індекси "повернення" теж зсуваються
        fb = getattr(self, 'fallback_profile_idx', 0)
        self.fallback_profile_idx = fb - 1 if fb > idx else (0 if fb == idx else fb)
        self.executor._temp_profile_holds = {
            k: (v - 1 if v > idx else v) for k, v in self.executor._temp_profile_holds.items() if v != idx
        }
        self.save_config()
        self.refresh_profiles_ui()
        self.switch_profile(self.active_profile_idx)

    def apply_preset_to_profile(self, idx, preset_name):
        if preset_name not in BUILTIN_PRESETS:
            return
        profiles = self.config.get("PROFILES", [])
        if 0 <= idx < len(profiles):
            profiles[idx] = copy.deepcopy(BUILTIN_PRESETS[preset_name])
            self.save_config()
            self.refresh_profiles_ui()
            self.switch_profile(idx)

    def switch_profile(self, idx, from_hotkey=False, is_temp_hold=False):
        profiles = self.config.get("PROFILES", [])
        if not (0 <= idx < len(profiles)):
            return
        self.active_profile_idx = idx
        for i, w in enumerate(self.ui_profiles):
            w.set_active(i == idx)
        self.refresh_pad_dots()
        # Перемикання профілю — без затримки, щоб вікно розсинхрону з платою було мінімальним
        self.sync_hardware_bindings(save_eeprom=False, immediate=True)
        if self.selected_btn:
            self.update_assign_ui()
        for btn in self.ui_pad_btns.values():
            btn.update()
        if from_hotkey:
            prof_name = profiles[idx].get("name", f"Профіль {idx + 1}")
            prefix = "Утримання шару" if is_temp_hold else "Профіль"
            self.trigger_osd("profile", f"{prefix}: {prof_name}", icon_text="layers" if is_temp_hold else "profile-goto")

    def get_fname(self, val):
        if not val or val == "NONE": return "НЕ ПРИЗНАЧЕНО"
        if val in FRIENDLY_NAMES: return FRIENDLY_NAMES[val]
        if val == "HOTKEY:mouse_wheel_up": return "Скрол миші ⬆"
        if val == "HOTKEY:mouse_wheel_down": return "Скрол миші ⬇"
        if val.startswith("SYS:PROFILE_GOTO:") or val.startswith("SYS:PROFILE_HOLD:"):
            try:
                idx = int(val.split(":")[-1])
            except ValueError:
                return val
            profs = self.config.get("PROFILES", [])
            pname = profs[idx].get("name", f"#{idx+1}") if 0 <= idx < len(profs) else f"#{idx+1}"
            return f"Перейти: {pname}" if val.startswith("SYS:PROFILE_GOTO:") else f"Утримувати: {pname}"
        if val.startswith("EXT:YT_FWD:"): return f"Ютуб: Вперед ({val.split(':')[-1]}с)"
        if val.startswith("EXT:YT_BACK:"): return f"Ютуб: Назад ({val.split(':')[-1]}с)"
        if val.startswith("ENC:APP:"): return f"Гучність: {val.split(':')[-1].replace('.exe', '').capitalize()}"
        if val.startswith("APP_MUTE:"): return f"Мут: {val.split(':')[-1].replace('.exe', '').capitalize()}"
        if val.startswith("HOTKEY:"): return val.split(":", 1)[1].upper()
        if val.startswith("TEXT:"): return f"Текст: {val.split(':', 1)[1][:10]}..."
        if val.startswith("MACRO:"): return f"Макрос: {val.split(':', 1)[1]}"
        if val.startswith("MULTI:"): return f"Мульти: {val.split(':', 1)[1]}"
        if val.startswith("URL:"): return val.split(":", 1)[1]
        if val.startswith("EXE:"): return os.path.basename(val.split(":", 1)[1]).replace(".exe", "")
        return val

    def show_main_info(self):
        if hasattr(self, 'tutorial_overlay') and self.tutorial_overlay:
            self.close_tutorial()
            return

        def open_pdf():
            pdf_path = os.path.join(ASSETS_DIR, "manual.pdf")
            if os.path.exists(pdf_path):
                os.startfile(pdf_path)

        from widgets import NativeTutorialOverlay, TutorialControls
        self.tutorial_overlay = NativeTutorialOverlay(self)
        self.tutorial_overlay.show()

        self.tut_controls = TutorialControls(self.centralWidget(), self.close_tutorial, open_pdf)
        self.tut_controls.resize(230, 130)
        self.update_tutorial_controls_pos()
        self.tut_controls.show()

    def close_tutorial(self):
        if hasattr(self, 'tutorial_overlay') and self.tutorial_overlay:
            self.tutorial_overlay.deleteLater()
            self.tutorial_overlay = None
        if hasattr(self, 'tut_controls') and self.tut_controls:
            self.tut_controls.deleteLater()
            self.tut_controls = None

    def update_tutorial_controls_pos(self):
        if hasattr(self, 'tut_controls') and self.tut_controls:
            pad = self.pad_frame
            pad_pos = pad.mapTo(self.centralWidget(), QPoint(0, 0))
            ctrl_w = self.tut_controls.width()

            tut_x = pad_pos.x() + (pad.width() - ctrl_w) // 2
            tut_y = pad_pos.y() + pad.height() + 20
            self.tut_controls.move(tut_x, tut_y)

    def show_yt_info(self):
        btn = self.sender()
        pos = btn.mapToGlobal(QPoint(25, -10)) if btn else QCursor.pos()

        def open_store():
            webbrowser.open("https://chromewebstore.google.com/detail/macropad-yt-control/deihndpelcbeahgbambapfmaaidhonni?hl=ru&utm_source=ext_sidebar")

        self.yt_popup = InfoPopup(
            "Для керування YouTube потрібно встановити\nнаше розширення для браузера.",
            "Скачати розширення",
            open_store,
            icon_name="download"
        )
        self.yt_popup.move(pos)
        self.yt_popup.show()

    def eventFilter(self, obj, event):
        is_recording = hasattr(self, 'macro_editor') and getattr(self.macro_editor, 'is_recording', False)

        if is_recording:
            if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease, QEvent.Type.MouseButtonDblClick):
                return True

        if event.type() == QEvent.Type.MouseButtonPress:
            from PySide6.QtWidgets import QApplication, QAbstractItemView, QScrollBar
            from widgets import EncoderCompoundWidget
            global_pos = QCursor.pos()
            w = QApplication.widgetAt(global_pos)

            if hasattr(self, 'multi_editor') and self.multi_editor.maximumWidth() > 0:
                if w and (self.multi_editor.isAncestorOf(w) or w == self.multi_editor):
                    return super().eventFilter(obj, event)

            interactive_types = (QPushButton, QComboBox, QLineEdit, QAbstractItemView, QScrollBar, EncoderCompoundWidget)
            if not w or not isinstance(w, interactive_types):
                local_pos = self.centralWidget().mapFromGlobal(global_pos)

                if 0 <= local_pos.x() < 460:
                    self.deselect_action()

                elif 460 <= local_pos.x() <= self.width():
                    if getattr(self, 'macro_editor', None) and self.macro_editor.maximumHeight() == 0 and \
                       getattr(self, 'vkb_container', None) and self.vkb_container.maximumHeight() == 0:
                        self.deselect_pad()

        return super().eventFilter(obj, event)

    def deselect_action(self):
        self.staged_val = None
        self.staged_name = None
        for b in self.findChildren(QPushButton, "actionBtn"):
            b.setProperty("staged", "false")
            b.style().unpolish(b)
            b.style().polish(b)
        self.macro_editor.hide_editor()
        self.set_vkb_visible(False)
        self.update_assign_ui()

    def clear_layout(self, layout):
        if layout is not None:
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget:
                    widget.deleteLater()
                elif item.layout():
                    self.clear_layout(item.layout())
                    item.layout().deleteLater()

    def update_dynamic_layout(self):
        if not hasattr(self, 'right_panel') or not hasattr(self, 'pad_frame') or not hasattr(self, 'vkb_container'):
            return
        w = self.right_panel.width()
        h = self.right_panel.height()

        M_W = self.multi_editor.width() if hasattr(self, 'multi_editor') else 0

        MAX_ED = 140
        MAX_VKB = 360
        H_ed = self.macro_editor.height()
        H_pad = self.pad_frame.height()
        H_vkb = self.vkb_container.height()
        p1 = float(H_ed) / MAX_ED if MAX_ED > 0 else 0
        p2 = float(H_vkb) / MAX_VKB if MAX_VKB > 0 else 0
        N = 2.0 + p1 + p2
        C = H_ed + H_pad + H_vkb
        G = max(0.0, (h - C) / N)
        Y_ed = int(G)
        Y_pad = int(G + H_ed + (p1 * G))
        Y_vkb = int(Y_pad + H_pad + (p2 * G))

        rem_w = w - (30 + M_W)
        available_w_for_center = w - 60 - M_W
        pad_x = (30 + M_W) + (available_w_for_center - self.pad_frame.width()) // 2 + 12
        if pad_x < (30 + M_W):
            pad_x = 30 + M_W

        current_container_width = 40
        if hasattr(self, 'ui_profiles'):
            for prof in self.ui_profiles:
                if prof.width() > current_container_width:
                    current_container_width = prof.width()

        if hasattr(self, 'profiles_scroll'):
            self.profiles_scroll.setGeometry(w - current_container_width - 22, Y_pad, current_container_width + 12, H_pad)
            self.profiles_scroll.raise_()

        if hasattr(self, 'multi_editor'):
            self.multi_editor.setGeometry(30, 30, M_W, h - 60)
            self.multi_editor.raise_()

        self.macro_editor.setGeometry(30 + M_W, Y_ed, max(10, w - 60 - M_W), H_ed)
        self.pad_frame.setGeometry(pad_x, Y_pad, self.pad_frame.width(), H_pad)
        self.vkb_container.setGeometry(30 + M_W, Y_vkb, max(10, w - 60 - M_W), H_vkb)

        if hasattr(self, 'btn_update'):
            bw = 180
            self.btn_update.setGeometry((30 + M_W) + (rem_w - bw) // 2, 10, bw, 40)
        if hasattr(self, 'btn_reset'):
            bw = self.btn_reset.width()
            bh = self.btn_reset.height()
            self.btn_reset.setGeometry(w - bw - 30, h - bh - 20, bw, bh)

        if hasattr(self, 'btn_main_help'):
            self.btn_main_help.setGeometry(15 + M_W, h - 35, 20, 20)
            self.btn_main_help.raise_()

        if hasattr(self, 'update_tutorial_controls_pos'):
            self.update_tutorial_controls_pos()

    def set_trigger_mode(self, mode_key):
        self.current_trigger_type = mode_key
        colors = {"tap": ACCENT, "dtap": "#ffaa00", "hold": "#b366ff"}
        trig_icons = {"tap": "tap", "dtap": "double-tap", "hold": "hold"}
        for k, btn in self.trigger_btns.items():
            is_act = (k == mode_key)
            col = colors[k]
            btn.setIcon(icons.icon(trig_icons[k], col if is_act else ICON_MUTED))
            if is_act:
                btn.setStyleSheet(f"QPushButton {{ background: rgba(0, 229, 255, 0.12); border: 1px solid {col}; color: {col}; font-size: 11px; font-weight: bold; border-radius: 5px; padding: 2px; }}")
            else:
                btn.setStyleSheet("QPushButton { background: #141414; border: 1px solid #333; color: #888; font-size: 11px; border-radius: 5px; padding: 2px; } QPushButton:hover { border: 1px solid #555; color: #ccc; }")
        if hasattr(self, 'lbl_assign_info') and hasattr(self, 'btn_assign'):
            self.update_assign_ui()

    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.left_panel = QFrame()
        self.left_panel.setObjectName("leftPanel")
        self.left_panel.setFixedWidth(460)

        left_layout = QVBoxLayout(self.left_panel)
        left_layout.setContentsMargins(20, 30, 20, 20)

        header_lay = QHBoxLayout()

        self.btn_settings = QPushButton("")
        self.btn_settings.setIcon(icons.icon("settings", ICON_MUTED))
        self.btn_settings.setIconSize(QSize(22, 22))
        self.btn_settings.setFixedSize(32, 32)
        self.btn_settings.setStyleSheet("QPushButton { background: transparent; border: none; } QPushButton:hover { background: #1f1f1f; border-radius: 5px; }")
        self.btn_settings.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_settings.clicked.connect(self.open_settings)
        header_lay.addWidget(self.btn_settings)

        header_lay.addSpacing(10)

        logo = QLabel("VPT | Pad")
        logo.setFont(QFont("Arial", 22, QFont.Weight.Bold))
        logo.setStyleSheet(f"color: {ACCENT};")
        header_lay.addWidget(logo)

        self.lbl_status = QLabel("<font color='#888888'>●</font> Пошук...")
        self.lbl_status.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header_lay.addWidget(self.lbl_status)
        left_layout.addLayout(header_lay)
        left_layout.addSpacing(15)

        tabs_layout = QHBoxLayout()
        self.tab_btns = {}
        for t in ["Система", "Медіа", "Клавіатура", "Запуск", "Макроси"]:
            b = QPushButton(t)
            b.setObjectName("tabBtn")
            b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            b.clicked.connect(lambda checked, name=t: self.switch_tab(name))
            tabs_layout.addWidget(b)
            self.tab_btns[t] = b
        left_layout.addLayout(tabs_layout)
        left_layout.addSpacing(10)

        self.stacked = QStackedWidget()
        left_layout.addWidget(self.stacked)
        self.build_tabs()

        assign_frame = QFrame()
        assign_layout = QVBoxLayout(assign_frame)
        assign_layout.setContentsMargins(0, 5, 0, 0)
        assign_layout.setSpacing(6)

        self.trigger_selector_widget = QWidget()
        trig_lay = QHBoxLayout(self.trigger_selector_widget)
        trig_lay.setContentsMargins(0, 0, 0, 0)
        trig_lay.setSpacing(6)
        self.trigger_btns = {}
        for t_key, t_label in [("tap", "Клік"), ("dtap", "Подвійний"), ("hold", "Утримання")]:
            tb = QPushButton(t_label)
            tb.setIconSize(QSize(16, 16))
            tb.setFixedHeight(32)
            tb.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            tb.clicked.connect(lambda checked, k=t_key: self.set_trigger_mode(k))
            trig_lay.addWidget(tb)
            self.trigger_btns[t_key] = tb
        assign_layout.addWidget(self.trigger_selector_widget)

        self.lbl_assign_info = QLabel(" ")
        self.lbl_assign_info.setStyleSheet(f"color: {TEXT_MAIN};")
        self.lbl_assign_info.setMinimumHeight(20)
        self.btn_assign = QPushButton("ПРИЗНАЧИТИ")
        self.btn_assign.setObjectName("assignBtn")
        self.btn_assign.setFixedHeight(50)
        self.btn_assign.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        self.btn_assign.setDisabled(True)
        self.btn_assign.clicked.connect(self.commit_assignment)
        assign_layout.addWidget(self.lbl_assign_info)
        assign_layout.addWidget(self.btn_assign)
        left_layout.addWidget(assign_frame)

        self.set_trigger_mode("tap")

        self.right_panel = RightPanel(self)
        self.macro_editor = MacroEditor(self, self.right_panel)
        self.multi_editor = MultiLaunchEditor(self, self.right_panel)

        self.pad_frame = QFrame(self.right_panel)
        self.pad_frame.setFixedSize(450, 390)

        for r in range(3):
            for c in range(3):
                x = c * 110
                y = r * 120 + 30
                bid = f"BTN_{r*3+c+1}"
                b = PadButton("", bid, self, self.pad_frame)
                b.setObjectName("padBtn")
                b.setFixedSize(90, 90)
                b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
                b.move(x, y)
                b.leftClicked.connect(self.select_pad)
                b.rightClicked.connect(self.clear_btn_assignment)
                self.ui_pad_btns[bid] = b

            ex = 330
            ey = r * 120 + 30
            eid = f"ENC_{r+1}"

            enc_widget = EncoderCompoundWidget(eid, self, self.pad_frame)
            enc_widget.move(ex, ey)
            enc_widget.leftClicked.connect(self.select_pad)
            enc_widget.rightClicked.connect(self.clear_btn_assignment)
            self.ui_pad_btns[eid] = enc_widget

        self.profiles_scroll = QScrollArea(self.right_panel)
        self.profiles_scroll.setWidgetResizable(True)
        self.profiles_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.profiles_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.profiles_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        self.profiles_container = QFrame()
        self.profiles_layout = QVBoxLayout(self.profiles_container)
        self.profiles_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        self.profiles_layout.setContentsMargins(0, 0, 0, 0)
        self.profiles_layout.setSpacing(5)
        self.profiles_scroll.setWidget(self.profiles_container)

        self.vkb_container = QFrame(self.right_panel)
        self.vkb_container.setMinimumHeight(0)
        self.vkb_container.setMaximumHeight(0)
        vkb_layout = QVBoxLayout(self.vkb_container)
        vkb_layout.setContentsMargins(0, 0, 0, 10)
        vkb_layout.setSpacing(0)

        vkb_centered_widget = QWidget()
        vkb_centered_layout = QVBoxLayout(vkb_centered_widget)
        vkb_centered_layout.setContentsMargins(0, 0, 0, 0)
        vkb_centered_layout.setSpacing(10)

        self.combo_header_widget = QWidget()
        sp = self.combo_header_widget.sizePolicy()
        sp.setRetainSizeWhenHidden(True)
        self.combo_header_widget.setSizePolicy(sp)

        combo_header = QHBoxLayout(self.combo_header_widget)
        combo_header.setContentsMargins(0, 0, 0, 0)
        combo_header.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)

        self.lbl_vkb_combo = QLabel("Ваша комбінація: [ Порожньо ]")
        self.lbl_vkb_combo.setStyleSheet(f"color: {ACCENT}; font-size: 16px; font-weight: bold;")

        btn_vkb_clear = QPushButton("Очистити")
        btn_vkb_clear.setIcon(icons.icon("close", BTN_DANGER))
        btn_vkb_clear.setIconSize(QSize(12, 12))
        btn_vkb_clear.setFixedSize(110, 32)
        btn_vkb_clear.setStyleSheet(f"background: transparent; color: {BTN_DANGER}; border: 1px solid {BTN_DANGER}; border-radius: 5px;")
        btn_vkb_clear.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_vkb_clear.clicked.connect(self.clear_vkb_combo)

        combo_header.addWidget(self.lbl_vkb_combo)
        combo_header.addSpacing(20)
        combo_header.addWidget(btn_vkb_clear)
        combo_header.addStretch()

        vkb_centered_layout.addWidget(self.combo_header_widget)

        self.vkb = VirtualKeyboard()
        self.vkb.key_pressed.connect(self.handle_vkb_key)

        self.vkb_scroll = QScrollArea()
        self.vkb_scroll.setWidgetResizable(True)
        self.vkb_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.vkb_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.vkb_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        vkb_scroll_wrapper = QWidget()
        vkb_scroll_wrapper.setStyleSheet("background: transparent;")
        wrapper_lay = QHBoxLayout(vkb_scroll_wrapper)
        wrapper_lay.setContentsMargins(0, 0, 0, 0)
        wrapper_lay.addStretch()
        wrapper_lay.addWidget(self.vkb)
        wrapper_lay.addStretch()

        self.vkb_scroll.setWidget(vkb_scroll_wrapper)
        vkb_centered_layout.addWidget(self.vkb_scroll)
        vkb_layout.addWidget(vkb_centered_widget)

        self.vkb_anim = QVariantAnimation(self)
        self.vkb_anim.setDuration(400)
        self.vkb_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.vkb_anim.valueChanged.connect(self.set_vkb_height)

        self.btn_reset = QPushButton("Скинути налаштування", self.right_panel)
        self.btn_reset.setFixedSize(200, 40)
        self.btn_reset.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_reset.clicked.connect(self.confirm_reset)

        main_layout.addWidget(self.left_panel)
        main_layout.addWidget(self.right_panel)

        if hasattr(self, 'pad_frame'): self.pad_frame.lower()
        if hasattr(self, 'macro_editor'): self.macro_editor.raise_()
        if hasattr(self, 'multi_editor'): self.multi_editor.raise_()
        if hasattr(self, 'vkb_container'): self.vkb_container.raise_()
        if hasattr(self, 'profiles_scroll'): self.profiles_scroll.raise_()

        self.btn_update = QPushButton("Оновити ПЗ", self.right_panel)
        self.btn_update.setIcon(icons.icon("refresh", ICON_MUTED))
        self.btn_update.setIconSize(QSize(18, 18))
        self.btn_update.setFixedHeight(40)
        self.btn_update.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_update.setStyleSheet(f"""
            QPushButton {{ background-color: transparent; color: {TEXT_SUB}; border: 1px solid #333; border-radius: 5px; font-weight: bold; padding: 5px; }}
            QPushButton:hover {{ border: 1px solid {ACCENT}; color: {TEXT_MAIN}; background-color: {BG_HOVER}; }}
        """)
        self.btn_update.clicked.connect(self.check_for_updates)
        self.btn_update.hide()

        self.btn_main_help = InfoButton(self.right_panel)
        self.btn_main_help.clicked.connect(self.show_main_info)

        self.refresh_profiles_ui()
        self.switch_profile(0)
        self.switch_tab("Система")
        QTimer.singleShot(50, self.update_dynamic_layout)

    def open_settings(self):
        from widgets import SettingsDialog
        dialog = SettingsDialog(self)
        dialog.exec()

    def set_vkb_height(self, val):
        self.vkb_container.setMinimumHeight(val)
        self.vkb_container.setMaximumHeight(val)
        self.update_dynamic_layout()

    def create_scroll_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.scrolls.append(scroll)
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        lay.setContentsMargins(0, 0, 10, 0)
        scroll.setWidget(w)
        self.stacked.addWidget(scroll)
        return lay

    def add_title(self, layout, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {ACCENT}; font-weight: bold; margin-top: 15px; margin-bottom: 5px;")
        layout.addWidget(lbl)

    def add_action(self, layout, text, val, icon_name=None):
        from widgets import DraggableActionButton
        b = DraggableActionButton(text, val, self, icon_name=icon_name)
        b.clicked.connect(lambda checked, t=text, v=val, btn=b: self.stage_action(t, v, btn))
        layout.addWidget(b)
        self.all_action_btns.append(b)
        return b

    def add_deletable_item(self, layout, text, val, delete_callback, icon=None):
        from widgets import DraggableActionButton
        row = QHBoxLayout()
        b = DraggableActionButton(text, val, self)
        if icon and not icon.isNull():
            b.set_custom_icon(icon)
        b.clicked.connect(lambda checked, t=text, v=val, btn=b: self.stage_action(t, v, btn))
        row.addWidget(b, stretch=1)
        self.all_action_btns.append(b)

        del_b = QPushButton("")
        del_b.setIcon(icons.icon("trash", ICON_MUTED))
        del_b.setIconSize(QSize(18, 18))
        del_b.setObjectName("delBtn")
        del_b.setFixedSize(40, 40)
        del_b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        del_b.setToolTip("Видалити")
        del_b.setStyleSheet(f"QPushButton {{ background: transparent; border: 1px solid #333; border-radius: 5px; }} QPushButton:hover {{ background: rgba(255, 51, 102, 0.2); border: 1px solid {BTN_DANGER}; }}")
        del_b.clicked.connect(lambda checked, v=val: delete_callback(v))
        row.addWidget(del_b)
        layout.addLayout(row)

    def refresh_profile_combos(self):
        if not hasattr(self, 'combo_target_prof'):
            return
        self.combo_target_prof.blockSignals(True)
        self.combo_target_prof.clear()
        for i, p in enumerate(self.config.get("PROFILES", [])):
            self.combo_target_prof.addItem(f"{i+1}. {p.get('name', 'Профіль')}", i)
        self.combo_target_prof.blockSignals(False)
        self._update_prof_action_btns()

    def _update_prof_action_btns(self):
        if not hasattr(self, 'btn_prof_goto') or not hasattr(self, 'combo_target_prof'):
            return
        idx = self.combo_target_prof.currentData()
        if idx is None:
            idx = 0
        self.btn_prof_goto.val = f"SYS:PROFILE_GOTO:{idx}"
        self.btn_prof_hold.val = f"SYS:PROFILE_HOLD:{idx}"

    def build_tabs(self):
        from widgets import DraggableActionButton
        s = self.create_scroll_tab()

        self.add_title(s, "Управління профілями макропада")
        self.add_action(s, "Наступний профіль", "SYS:PROFILE_NEXT")
        self.add_action(s, "Попередній профіль", "SYS:PROFILE_PREV")

        prof_sel_lay = QHBoxLayout()
        self.combo_target_prof = AnimatedComboBox()
        self.combo_target_prof.setFixedHeight(40)
        prof_sel_lay.addWidget(self.combo_target_prof, stretch=1)
        s.addLayout(prof_sel_lay)

        self.btn_prof_goto = DraggableActionButton("Перейти на вибраний профіль", "SYS:PROFILE_GOTO:0", self)
        self.btn_prof_goto.clicked.connect(lambda checked, b=self.btn_prof_goto: self.stage_action(self.get_fname(b.val), b.val, b))
        s.addWidget(self.btn_prof_goto)
        self.all_action_btns.append(self.btn_prof_goto)

        self.btn_prof_hold = DraggableActionButton("Утримувати профіль (Shift / Fn-шар)", "SYS:PROFILE_HOLD:0", self)
        self.btn_prof_hold.clicked.connect(lambda checked, b=self.btn_prof_hold: self.stage_action(self.get_fname(b.val), b.val, b))
        s.addWidget(self.btn_prof_hold)
        self.all_action_btns.append(self.btn_prof_hold)

        self.combo_target_prof.currentIndexChanged.connect(lambda _: self._update_prof_action_btns())
        self.refresh_profile_combos()

        self.add_title(s, "Розумні дії для Енкодерів (Smart Dial)")
        self.add_action(s, "Зміна режиму крутилки (по кліку SW)", "ENC:MODE_TOGGLE")
        self.add_action(s, "Яскравість монітора", "ENC:BRIGHTNESS")
        self.add_action(s, "Прокрутка сторінки (Scroll)", "ENC:SCROLL")
        self.add_action(s, "Масштаб (Ctrl+ / Ctrl-)", "ENC:ZOOM")
        self.add_action(s, "Перемотка таймлайну (⬅ / ➡)", "ENC:TIMELINE")
        self.add_action(s, "Розмір пензля ([ / ])", "ENC:BRUSH")
        self.add_action(s, "Історія дій (Undo / Redo)", "ENC:UNDO_REDO")

        self.add_title(s, "Системні функції (Windows)")
        self.add_action(s, "Диспетчер завдань", "SYS:TASK")
        self.add_action(s, "Згорнути всі вікна", "SYS:DESKTOP")
        self.add_action(s, "Скріншот (Ножиці)", "SYS:SNIP")
        self.add_action(s, "Блокування ПК (Win+L)", "SYS:LOCK")
        self.add_action(s, "Режим сну", "SYS:SLEEP")

        m = self.create_scroll_tab()
        self.add_title(m, "Глобальне управління")
        self.add_action(m, "Play / Pause", "MED:PLAY")
        self.add_action(m, "Наступне медіа", "MED:NEXT")
        self.add_action(m, "Попереднє медіа", "MED:PREV")
        self.add_action(m, "Загальна гучність системи", "ENC:VOL")
        self.add_action(m, "Збільшити гучність системи", "MED:VOL_UP")
        self.add_action(m, "Зменшити гучність системи", "MED:VOL_DOWN")
        self.add_action(m, "Вимкнути звук системи (Mute)", "MED:MUTE")

        yt_title_lay = QHBoxLayout()
        yt_title_lay.setContentsMargins(0, 15, 0, 5)
        yt_lbl = QLabel("YouTube (Через розширення)")
        yt_lbl.setStyleSheet(f"color: {ACCENT}; font-weight: bold;")
        yt_title_lay.addWidget(yt_lbl)

        self.btn_yt_info = InfoButton()
        self.btn_yt_info.clicked.connect(self.show_yt_info)
        yt_title_lay.addWidget(self.btn_yt_info)
        yt_title_lay.addStretch()
        m.addLayout(yt_title_lay)

        self.add_action(m, "Play / Pause (YouTube)", "EXT:YT_PLAYPAUSE")

        yt_lay = QHBoxLayout()
        self.combo_yt = AnimatedComboBox()
        self.combo_yt.setFixedWidth(70)
        self.combo_yt.setFixedHeight(40)
        self.combo_yt.addItems(["1с", "3с", "5с", "10с"])
        self.combo_yt.setCurrentText("10с")
        yt_lay.addWidget(self.combo_yt)

        btn_back = DraggableActionButton("Назад", f"EXT:YT_BACK:{self.combo_yt.currentText().replace('с', '')}", self)
        btn_back.setFixedHeight(40)
        btn_back.clicked.connect(lambda checked, btn=btn_back: self.stage_action(f"Ютуб: Назад ({self.combo_yt.currentText()})", f"EXT:YT_BACK:{self.combo_yt.currentText().replace('с', '')}", btn))
        self.combo_yt.currentTextChanged.connect(lambda txt, b=btn_back: setattr(b, 'val', f"EXT:YT_BACK:{txt.replace('с', '')}"))
        yt_lay.addWidget(btn_back)
        self.all_action_btns.append(btn_back)

        btn_fwd = DraggableActionButton("Вперед", f"EXT:YT_FWD:{self.combo_yt.currentText().replace('с', '')}", self)
        btn_fwd.setFixedHeight(40)
        btn_fwd.clicked.connect(lambda checked, btn=btn_fwd: self.stage_action(f"Ютуб: Вперед ({self.combo_yt.currentText()})", f"EXT:YT_FWD:{self.combo_yt.currentText().replace('с', '')}", btn))
        self.combo_yt.currentTextChanged.connect(lambda txt, b=btn_fwd: setattr(b, 'val', f"EXT:YT_FWD:{txt.replace('с', '')}"))
        yt_lay.addWidget(btn_fwd)
        self.all_action_btns.append(btn_fwd)

        m.addLayout(yt_lay)

        self.add_title(m, "Мікрофон")
        self.add_action(m, "Вимкнути мікрофон глобально", "MED:MIC_MUTE")

        self.add_title(m, "Управління звуком окремих програм")
        lbl1 = QLabel("1. Виберіть програму зі списку:")
        lbl1.setStyleSheet(f"color: {TEXT_SUB}; margin-bottom: 5px;")
        m.addWidget(lbl1)

        mix_h = QHBoxLayout()
        self.combo_apps = AnimatedComboBox()
        self.combo_apps.setFixedHeight(45)
        self.combo_apps.addItem("Сканування…")
        mix_h.addWidget(self.combo_apps, stretch=1)

        btn_scan = QPushButton("")
        btn_scan.setIcon(icons.icon("refresh", ICON_COLOR))
        btn_scan.setIconSize(QSize(18, 18))
        btn_scan.setToolTip("Пересканувати програми зі звуком")
        btn_scan.setFixedSize(45, 45)
        btn_scan.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_scan.clicked.connect(self.scan_audio_apps)
        mix_h.addWidget(btn_scan)
        m.addLayout(mix_h)

        lbl2 = QLabel("2. Призначте дію для вибраної програми:")
        lbl2.setStyleSheet(f"color: {TEXT_SUB}; margin-top: 10px;")
        m.addWidget(lbl2)

        btn_vol = DraggableActionButton("Зміна гучності", "", self, icon_name="mixer")
        btn_vol.setFixedHeight(45)
        btn_vol.clicked.connect(lambda checked, btn=btn_vol: self.stage_action(f"Гучність: {self.combo_apps.currentText()}", f"ENC:APP:{self.combo_apps.currentData()}", btn))
        self.combo_apps.currentIndexChanged.connect(lambda idx, b=btn_vol: setattr(b, 'val', f"ENC:APP:{self.combo_apps.currentData()}"))
        m.addWidget(btn_vol)
        self.all_action_btns.append(btn_vol)

        btn_mute = DraggableActionButton("Вимкнути звук", "", self, icon_name="volume-x")
        btn_mute.setFixedHeight(45)
        btn_mute.clicked.connect(lambda checked, btn=btn_mute: self.stage_action(f"Мут: {self.combo_apps.currentText()}", f"APP_MUTE:{self.combo_apps.currentData()}", btn))
        self.combo_apps.currentIndexChanged.connect(lambda idx, b=btn_mute: setattr(b, 'val', f"APP_MUTE:{self.combo_apps.currentData()}"))
        m.addWidget(btn_mute)
        self.all_action_btns.append(btn_mute)
        self.scan_audio_apps()

        k = self.create_scroll_tab()

        self.btn_vkb = QPushButton("ВІРТУАЛЬНА КЛАВІАТУРА")
        self.btn_vkb.setIcon(icons.icon("keyboard", ICON_COLOR))
        self.btn_vkb.setIconSize(QSize(20, 20))
        self.btn_vkb.setFixedHeight(50)
        self.btn_vkb.setStyleSheet(f"background-color: {BG_HOVER}; border: 1px solid {ACCENT};")
        self.btn_vkb.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_vkb.clicked.connect(self.toggle_vkb)
        k.addWidget(self.btn_vkb)

        self.add_title(k, "Гарячі клавіші (Базові)")
        for t, v in [("Копіювати", "ctrl+c"), ("Вставити", "ctrl+v"), ("Вирізати", "ctrl+x"), ("Скасувати", "ctrl+z"), ("Виділити все", "ctrl+a"), ("Зберегти", "ctrl+s"), ("Закрити вікно", "alt+f4")]:
            self.add_action(k, f"{t} ({v.upper()})", f"HOTKEY:{v}")

        self.add_title(k, "Швидке введення тексту")
        h_txt = QHBoxLayout()
        self.inp_quick_text = QLineEdit()
        self.inp_quick_text.setPlaceholderText("Введіть текст або шаблон...")
        h_txt.addWidget(self.inp_quick_text, stretch=1)
        btn_add_txt = QPushButton("Додати")
        btn_add_txt.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_add_txt.clicked.connect(lambda: self.add_recent("TEXT", self.inp_quick_text.text()))
        h_txt.addWidget(btn_add_txt)
        k.addLayout(h_txt)

        self.texts_widget = QWidget()
        self.texts_layout = QVBoxLayout(self.texts_widget)
        self.texts_layout.setContentsMargins(0, 0, 0, 0)
        k.addWidget(self.texts_widget)
        self.update_texts_list()

        l = self.create_scroll_tab()
        self.add_title(l, "Додати нове")
        btn_exe = QPushButton("Огляд .exe файлу...")
        btn_exe.setIcon(icons.icon("folder", ICON_COLOR))
        btn_exe.setIconSize(QSize(18, 18))
        btn_exe.clicked.connect(self.pick_exe)
        l.addWidget(btn_exe)

        h_url = QHBoxLayout()
        self.inp_url = QLineEdit()
        self.inp_url.setPlaceholderText("https://youtube.com")
        h_url.addWidget(self.inp_url)
        btn_url = QPushButton("Додати URL")
        btn_url.clicked.connect(lambda: self.add_recent("URL", self.inp_url.text()))
        h_url.addWidget(btn_url)
        l.addLayout(h_url)

        self.add_title(l, "Швидкий запуск")
        self.add_action(l, "Spotify", "CMD:start spotify:")

        self.recents_widget = QWidget()
        self.recents_layout = QVBoxLayout(self.recents_widget)
        self.recents_layout.setContentsMargins(0, 0, 0, 0)
        l.addWidget(self.recents_widget)
        self.update_recents()

        self.add_title(l, "Мульти-запуск (Групи)")

        h_multi = QHBoxLayout()
        self.inp_multi_name = QLineEdit()
        self.inp_multi_name.setPlaceholderText("Назва групи...")
        h_multi.addWidget(self.inp_multi_name, stretch=1)

        btn_create_multi = QPushButton("Створити")
        btn_create_multi.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_create_multi.clicked.connect(self.create_multi_group)
        h_multi.addWidget(btn_create_multi)
        l.addLayout(h_multi)

        self.multi_widget = QWidget()
        self.multi_layout = QVBoxLayout(self.multi_widget)
        self.multi_layout.setContentsMargins(0, 0, 0, 0)
        l.addWidget(self.multi_widget)
        self.update_multi_list()

        ma = self.create_scroll_tab()
        self.add_title(ma, "Створення нового макросу")

        self.inp_macro_name = QLineEdit()
        self.inp_macro_name.setPlaceholderText("Назва макросу...")
        ma.addWidget(self.inp_macro_name)

        h_mac = QHBoxLayout()
        self.combo_macro_type = AnimatedComboBox()
        self.combo_macro_type.addItems([
            "One Shot (Один раз)",
            "Repeat while held (Поки натиснуто)",
            "Toggle (Вкл / Викл)"
        ])
        h_mac.addWidget(self.combo_macro_type, stretch=1)

        btn_create_mac = QPushButton("Створити")
        btn_create_mac.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_create_mac.clicked.connect(self.create_new_macro)
        h_mac.addWidget(btn_create_mac)
        ma.addLayout(h_mac)

        self.add_title(ma, "Бібліотека макросів")
        self.macros_widget = QWidget()
        self.macros_layout = QVBoxLayout(self.macros_widget)
        self.macros_layout.setContentsMargins(0, 0, 0, 0)
        ma.addWidget(self.macros_widget)
        self.update_macros_list()

    def set_vkb_visible(self, visible):
        if visible and self.vkb_container.maximumHeight() == 0:
            self.btn_reset.hide()
            self.vkb_anim.setStartValue(0)
            self.vkb_anim.setEndValue(360)
            self.vkb_anim.start()
            self.btn_vkb.setText("СХОВАТИ КЛАВІАТУРУ")
            self.btn_vkb.setStyleSheet("background-color: #1a1a1a; border: 1px solid #444;")
        elif not visible and self.vkb_container.maximumHeight() > 0:
            self.btn_reset.show()
            self.vkb_anim.setStartValue(self.vkb_container.maximumHeight())
            self.vkb_anim.setEndValue(0)
            self.vkb_anim.start()
            self.btn_vkb.setText("ВІРТУАЛЬНА КЛАВІАТУРА")
            self.btn_vkb.setStyleSheet(f"background-color: {BG_HOVER}; border: 1px solid {ACCENT};")
            self.clear_vkb_combo()

    def toggle_vkb(self):
        self.set_vkb_visible(self.vkb_container.maximumHeight() == 0)

    def handle_vkb_key(self, key_id):
        if self.listening_action:
            self.listening_action.key_caught_sig.emit(key_id)
            return

        if key_id in self.active_vkb_keys:
            self.active_vkb_keys.remove(key_id)
        else:
            self.active_vkb_keys.append(key_id)

        self.vkb.update_keys(self.active_vkb_keys)

        if self.active_vkb_keys:
            display_str = " + ".join([k.replace("left ", "").replace("right ", "").replace("num ", "Num ").upper() for k in self.active_vkb_keys])
            hotkey_str = "+".join([k.replace("left ", "").replace("right ", "") for k in self.active_vkb_keys])
            self.lbl_vkb_combo.setText(f"Ваша комбінація: [ {display_str} ]")
            self.stage_action(f"Комбінація: {display_str}", f"HOTKEY:{hotkey_str}")
        else:
            self.clear_vkb_combo()

    def clear_vkb_combo(self):
        self.active_vkb_keys.clear()
        self.vkb.update_keys(self.active_vkb_keys)
        self.lbl_vkb_combo.setText("Ваша комбінація: [ Порожньо ]")
        if self.staged_val and self.staged_val.startswith("HOTKEY:"):
            self.staged_val = None
            self.staged_name = None
            self.update_assign_ui()

    def scan_audio_apps(self):
        # Повторний клік під час сканування перезаписував self.scanner, і працюючий QThread
        # знищувався збирачем сміття -> аварійне завершення програми.
        if getattr(self, 'scanner', None) is not None and self.scanner.isRunning():
            return
        self.combo_apps.clear()
        self.combo_apps.addItem("Сканування…")
        self.combo_apps.setDisabled(True)
        self.scanner = AudioScannerThread()
        self.scanner.apps_found.connect(self.update_combo)
        self.scanner.start()

    def update_combo(self, apps_info):
        self.combo_apps.clear()
        if not apps_info:
            self.combo_apps.addItem("Програм не знайдено", "NONE")
        else:
            for item in apps_info:
                app = item["app"]
                path = item["path"]
                clean_name = app.replace(".exe", "").capitalize()
                icon = QIcon()
                if path and os.path.exists(path):
                    icon = self.icon_provider.icon(QFileInfo(path))
                self.combo_apps.addItem(icon, clean_name, app)
        self.combo_apps.setEnabled(True)

    def update_texts_list(self):
        if not hasattr(self, 'texts_layout'):
            return
        self.clear_layout(self.texts_layout)
        texts = self.config.get("RECENTS", {}).get("TEXT", [])
        for txt in reversed(texts):
            short_txt = txt if len(txt) <= 22 else txt[:22] + "..."
            self.add_deletable_item(self.texts_layout, short_txt, f"TEXT:{txt}", self.delete_recent)

    def update_recents(self):
        self.clear_layout(self.recents_layout)
        if self.config["RECENTS"]["EXE"] or self.config["RECENTS"]["URL"]:
            self.add_title(self.recents_layout, "Збережені програми та посилання")
            for ru in reversed(self.config["RECENTS"]["URL"]):
                self.add_deletable_item(self.recents_layout, ru, f"URL:{ru}", self.delete_recent)
            for re in reversed(self.config["RECENTS"]["EXE"]):
                clean_exe = os.path.basename(re).replace(".exe", "")
                icon = QIcon()
                if os.path.exists(re):
                    icon = self.icon_provider.icon(QFileInfo(re))
                self.add_deletable_item(self.recents_layout, clean_exe, f"EXE:{re}", self.delete_recent, icon)

    def clean_dead_links(self, deleted_val):
        changed = False
        for prof in self.config.get("PROFILES", []):
            actions = prof.get("actions", {})
            for k, v in list(actions.items()):
                if isinstance(v, dict):
                    for slot in ("tap", "dtap", "hold"):
                        if v.get(slot) == deleted_val:
                            v[slot] = "NONE"
                            changed = True
                    if all(val == "NONE" for val in v.values()):
                        del actions[k]
                elif v == deleted_val:
                    del actions[k]
                    changed = True

            enc_modes = prof.get("enc_modes", {})
            for ek, mlist in list(enc_modes.items()):
                if deleted_val in mlist:
                    new_list = [m for m in mlist if m != deleted_val]
                    if new_list:
                        enc_modes[ek] = new_list
                    else:
                        del enc_modes[ek]
                    changed = True

        if changed:
            self.save_config()
            self.sync_hardware_bindings(save_eeprom=True)
            self.update_assign_ui()
            self.refresh_pad_dots()

    def delete_recent(self, val):
        if val.startswith("URL:"):
            url = val.split(":", 1)[1]
            if url in self.config["RECENTS"]["URL"]:
                self.config["RECENTS"]["URL"].remove(url)
            self.update_recents()
        elif val.startswith("EXE:"):
            exe = val.split(":", 1)[1]
            if exe in self.config["RECENTS"]["EXE"]:
                self.config["RECENTS"]["EXE"].remove(exe)
            self.update_recents()
        elif val.startswith("TEXT:"):
            txt = val.split(":", 1)[1]
            if txt in self.config["RECENTS"].get("TEXT", []):
                self.config["RECENTS"]["TEXT"].remove(txt)
            self.update_texts_list()

        self.clean_dead_links(val)
        self.save_config()

    def add_recent(self, r_type, val):
        if not val:
            return
        if r_type not in self.config["RECENTS"]:
            self.config["RECENTS"][r_type] = []
        if val not in self.config["RECENTS"][r_type]:
            self.config["RECENTS"][r_type].append(val)
            if len(self.config["RECENTS"][r_type]) > 10:
                self.config["RECENTS"][r_type].pop(0)
            self.save_config()
        if r_type == "URL":
            self.inp_url.clear()
            self.update_recents()
        elif r_type == "TEXT":
            self.inp_quick_text.clear()
            self.update_texts_list()
        else:
            self.update_recents()

    def create_multi_group(self):
        name = self.inp_multi_name.text().strip()
        if not name:
            self.inp_multi_name.setStyleSheet(f"border: 1px solid {BTN_DANGER};")
            QTimer.singleShot(1000, lambda: self.inp_multi_name.setStyleSheet(f"background-color: {BG_MAIN}; border: 1px solid #333; color: {TEXT_MAIN}; border-radius: 5px; padding: 8px;"))
            return

        if "MULTI_LAUNCH" not in self.config:
            self.config["MULTI_LAUNCH"] = {}
        if name not in self.config["MULTI_LAUNCH"]:
            self.config["MULTI_LAUNCH"][name] = []
            self.save_config()

        self.inp_multi_name.clear()
        self.update_multi_list()
        self.edit_multi_group(name)

    def update_multi_list(self):
        from widgets import DraggableActionButton
        self.clear_layout(self.multi_layout)
        for g_name in self.config.get("MULTI_LAUNCH", {}).keys():
            row = QHBoxLayout()
            b = DraggableActionButton(g_name, f"MULTI:{g_name}", self)
            b.clicked.connect(lambda checked, t=f"Група: {g_name}", v=f"MULTI:{g_name}", btn=b: self.stage_action(t, v, btn))
            row.addWidget(b, stretch=1)
            self.all_action_btns.append(b)

            is_active = (hasattr(self, 'multi_editor') and getattr(self.multi_editor, 'current_group', None) == g_name)

            edit_b = QPushButton("")
            edit_b.setIcon(icons.icon("settings", ACCENT if is_active else ICON_MUTED))
            edit_b.setToolTip("Редагувати групу")
            edit_b.setIconSize(QSize(20, 20))
            edit_b.setProperty("active", "true" if is_active else "false")
            edit_b.setStyleSheet(f"""
                QPushButton {{ background-color: transparent; border: 1px solid #333; border-radius: 5px; padding: 0px; }}
                QPushButton:hover {{ background-color: {BG_HOVER}; border: 1px solid {ACCENT}; }}
                QPushButton[active="true"] {{ background-color: {BG_HOVER}; border: 1px solid {ACCENT}; }}
            """)
            edit_b.setFixedSize(40, 40)
            edit_b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            edit_b.clicked.connect(lambda checked, n=g_name: self.toggle_multi_group(n))
            row.addWidget(edit_b)

            del_b = QPushButton("")
            del_b.setIcon(icons.icon("trash", ICON_MUTED))
            del_b.setIconSize(QSize(18, 18))
            del_b.setToolTip("Видалити")
            del_b.setObjectName("delBtn")
            del_b.setFixedSize(40, 40)
            del_b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            del_b.setStyleSheet(f"QPushButton {{ background: transparent; border: 1px solid #333; border-radius: 5px; }} QPushButton:hover {{ background: rgba(255, 51, 102, 0.2); border: 1px solid {BTN_DANGER}; }}")
            del_b.clicked.connect(lambda checked, n=g_name: self.delete_multi_group(n))
            row.addWidget(del_b)
            self.multi_layout.addLayout(row)

    def edit_multi_group(self, name):
        self.macro_editor.hide_editor()
        self.set_vkb_visible(False)
        self.multi_editor.load(name)

    def toggle_multi_group(self, name):
        if hasattr(self, 'multi_editor') and self.multi_editor.current_group == name and self.multi_editor.maximumWidth() > 0:
            self.multi_editor.hide_editor()
        else:
            self.edit_multi_group(name)
        self.update_multi_list()

    def delete_multi_group(self, name):
        if "MULTI_LAUNCH" in self.config and name in self.config["MULTI_LAUNCH"]:
            del self.config["MULTI_LAUNCH"][name]
            self.clean_dead_links(f"MULTI:{name}")
            self.save_config()
            self.update_multi_list()
            if hasattr(self, 'multi_editor') and self.multi_editor.current_group == name:
                self.multi_editor.hide_editor()

    def create_new_macro(self):
        name = self.inp_macro_name.text().strip()
        if not name:
            self.inp_macro_name.setStyleSheet(f"border: 1px solid {BTN_DANGER};")
            QTimer.singleShot(1000, lambda: self.inp_macro_name.setStyleSheet(f"background-color: {BG_MAIN}; border: 1px solid #333; color: {TEXT_MAIN}; border-radius: 5px; padding: 8px;"))
            return

        type_str = self.combo_macro_type.currentText()
        if "One Shot" in type_str: t_id = "One Shot"
        elif "Repeat" in type_str: t_id = "Repeat while held"
        else: t_id = "Toggle"

        if name not in self.config["MACROS"]:
            self.config["MACROS"][name] = json.dumps({"mode": t_id, "events": []})
            self.save_config()

        self.inp_macro_name.clear()
        self.update_macros_list()

        target_val = f"MACRO:{name}"
        for i in range(self.macros_layout.count()):
            lay = self.macros_layout.itemAt(i)
            if lay and lay.layout():
                btn = lay.layout().itemAt(0).widget()
                if btn and getattr(btn, 'val', None) == target_val:
                    btn.click()
                    break

    def update_macros_list(self):
        from widgets import DraggableActionButton
        self.clear_layout(self.macros_layout)
        for m_name, m_json in self.config.get("MACROS", {}).items():
            m_type = "One Shot"
            cycle_delay = 100
            try:
                data = json.loads(m_json) if isinstance(m_json, str) else m_json
                if isinstance(data, dict):
                    m_type = data.get("mode", "One Shot")
                    cycle_delay = data.get("cycle_delay", 100)
            except Exception:
                pass

            mode_icon = {"Toggle": "toggle", "Repeat while held": "repeat"}.get(m_type, "macro")
            row = QHBoxLayout()

            b = DraggableActionButton(f"{m_name} [{m_type}]", f"MACRO:{m_name}", self, icon_name=mode_icon)
            b.clicked.connect(lambda checked, t=f"Макрос: {m_name}", v=f"MACRO:{m_name}", btn=b: self.stage_action(t, v, btn))
            row.addWidget(b, stretch=1)
            self.all_action_btns.append(b)

            if m_type in ["Toggle", "Repeat while held"]:
                inp_delay = QLineEdit(str(cycle_delay))
                inp_delay.setFixedSize(50, 40)
                inp_delay.setAlignment(Qt.AlignmentFlag.AlignCenter)
                inp_delay.setStyleSheet(f"QLineEdit {{ background: #111; color: #fff; border: 1px solid #444; border-radius: 4px; font-size: 12px; }} QLineEdit:focus {{ border: 1px solid {ACCENT}; }}")
                inp_delay.setToolTip("Затримка між циклами в мілісекундах")

                def make_update_func(name, widget):
                    def _update():
                        try:
                            v = int(widget.text())
                        except Exception:
                            v = 100
                        if v <= 0:
                            v = 1
                        widget.setText(str(v))
                        raw = self.config.get("MACROS", {}).get(name, "{}")
                        try:
                            cur_data = json.loads(raw) if isinstance(raw, str) else raw
                        except Exception:
                            cur_data = {}
                        if isinstance(cur_data, dict):
                            cur_data["cycle_delay"] = v
                            self.config["MACROS"][name] = json.dumps(cur_data)
                            self.save_config()
                    return _update

                inp_delay.editingFinished.connect(make_update_func(m_name, inp_delay))
                row.addWidget(inp_delay)

            del_b = QPushButton("")
            del_b.setIcon(icons.icon("trash", ICON_MUTED))
            del_b.setIconSize(QSize(18, 18))
            del_b.setToolTip("Видалити")
            del_b.setObjectName("delBtn")
            del_b.setFixedSize(40, 40)
            del_b.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            del_b.setStyleSheet(f"QPushButton {{ background: transparent; border: 1px solid #333; border-radius: 5px; }} QPushButton:hover {{ background: rgba(255, 51, 102, 0.2); border: 1px solid {BTN_DANGER}; }}")
            del_b.clicked.connect(lambda checked, v=f"MACRO:{m_name}": self.delete_macro(v))
            row.addWidget(del_b)

            self.macros_layout.addLayout(row)

    def delete_macro(self, val):
        m_name = val.split(":", 1)[1]
        if m_name in self.config["MACROS"]:
            del self.config["MACROS"][m_name]
            self.clean_dead_links(val)
            self.save_config()
            self.update_macros_list()
            self.macro_editor.hide_editor()

    def switch_tab(self, name):
        for t, b in self.tab_btns.items():
            b.setProperty("active", str(t == name).lower())
            b.style().unpolish(b)
            b.style().polish(b)
        idx = list(self.tab_btns.keys()).index(name)
        self.stacked.setCurrentIndex(idx)

    def select_pad(self, bid):
        self.selected_btn = bid
        for id_key, btn in self.ui_pad_btns.items():
            if isinstance(btn, EncoderCompoundWidget):
                btn.update()
            else:
                btn.setProperty("active", str(id_key == bid).lower())
                btn.style().unpolish(btn)
                btn.style().polish(btn)
        self.update_assign_ui()

    def deselect_pad(self):
        self.selected_btn = None
        for bid, btn in self.ui_pad_btns.items():
            if isinstance(btn, EncoderCompoundWidget):
                btn.update()
            else:
                btn.setProperty("active", "false")
                btn.style().unpolish(btn)
                btn.style().polish(btn)
        self.update_assign_ui()

    def clear_btn_assignment(self, bid):
        if bid.startswith("BTN_") or bid.endswith("_SW"):
            for slot in ("tap", "dtap", "hold"):
                self.set_action(bid, "NONE", trigger=slot, commit=False)
            self.save_config()
            self.sync_hardware_bindings(save_eeprom=True)
        else:
            self.set_action(bid, "NONE")
        self.refresh_pad_dots()
        if self.selected_btn == bid:
            self.update_assign_ui()

    def confirm_reset(self):
        dialog = ResetDialog(self)
        if dialog.exec():
            self.clear_profile(self.active_profile_idx)

    def stage_action(self, name, val, btn_obj=None):
        self.staged_name = name
        self.staged_val = val

        for b in self.findChildren(QPushButton, "actionBtn"):
            b.setProperty("staged", "false")
            b.style().unpolish(b)
            b.style().polish(b)
            if hasattr(b, "set_icon_staged"):
                b.set_icon_staged(False)

        if btn_obj:
            try:
                btn_obj.setProperty("staged", "true")
                btn_obj.style().unpolish(btn_obj)
                btn_obj.style().polish(btn_obj)
                if hasattr(btn_obj, "set_icon_staged"):
                    btn_obj.set_icon_staged(True)
            except RuntimeError:
                pass

        if val.startswith("MACRO:"):
            if hasattr(self, 'multi_editor'):
                self.multi_editor.hide_editor()
            self.macro_editor.load(val.split(":", 1)[1])
            self.set_vkb_visible(True)
        else:
            self.macro_editor.hide_editor()

        self.update_assign_ui()

    def update_assign_ui(self):
        if not hasattr(self, 'lbl_assign_info') or not hasattr(self, 'btn_assign'):
            return

        if self.selected_btn and self.staged_val:
            bn = self.selected_btn
            is_multi_btn = bn.startswith("BTN_") or bn.endswith("_SW")
            trig_names = {"tap": "Клік", "dtap": "2x Клік", "hold": "Утримання"}
            trig_suffix = f" [{trig_names.get(self.current_trigger_type, 'Клік')}]" if is_multi_btn else ""

            if "_L" in bn: bn = bn.replace("ENC_", "Енкодер ").replace("_L", " ⟲ (Вліво)")
            elif "_R" in bn: bn = bn.replace("ENC_", "Енкодер ").replace("_R", " ⟳ (Вправо)")
            elif bn.endswith("_SW"): bn = bn.replace("ENC_", "Енкодер ").replace("_SW", " (SW)") + trig_suffix
            elif bn.startswith("ENC_"): bn = bn.replace("ENC_", "Енкодер ") + " (Крутилка)"
            elif bn.startswith("BTN_"): bn = bn.replace("BTN_", "Кнопка ") + trig_suffix

            is_btn = self.selected_btn.startswith("BTN_")
            is_center_encoder = (self.selected_btn.startswith("ENC_") and not any(self.selected_btn.endswith(sfx) for sfx in ["_SW", "_L", "_R"]))
            is_sw_encoder = self.selected_btn.endswith("_SW")
            is_encoder_action = self.staged_val.startswith("ENC:") and self.staged_val != "ENC:MODE_TOGGLE"

            self.lbl_assign_info.setText(f"{bn} ➔ {self.staged_name}")
            pulse_actions = []

            if (is_btn or is_sw_encoder) and is_encoder_action:
                self.lbl_assign_info.setText("Тільки для обертання (Енкодери)")
                if is_btn:
                    pulse_actions.append((self.selected_btn, BTN_DANGER))
                for i in range(1, 4):
                    pulse_actions.append((f"ENC_{i}", {"center": ACCENT}))
                self.btn_assign.setText("НЕ СУМІСНО")

            elif is_center_encoder and not is_encoder_action:
                self.lbl_assign_info.setText("Тільки для кнопок (SW / Бокові / Звичайні)")
                base_enc = self.selected_btn.split("_")[0] + "_" + self.selected_btn.split("_")[1]
                pulse_actions.append((base_enc, {"center": BTN_DANGER, "outer": ACCENT}))
                for i in range(1, 10):
                    pulse_actions.append((f"BTN_{i}", ACCENT))
                self.btn_assign.setText("НЕ СУМІСНО")

            else:
                self.btn_assign.setText("ПРИЗНАЧИТИ")
                self.btn_assign.setDisabled(False)
                self.btn_assign.setProperty("ready", "true")
                self.btn_assign.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

            if pulse_actions:
                self.btn_assign.setDisabled(True)
                self.btn_assign.setProperty("ready", "false")
                self.btn_assign.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
                for bid, args in pulse_actions:
                    if bid in self.ui_pad_btns:
                        self.ui_pad_btns[bid].trigger_pulse(args)
        else:
            self.lbl_assign_info.setText(" ")
            self.btn_assign.setText("ПРИЗНАЧИТИ")
            self.btn_assign.setDisabled(True)
            self.btn_assign.setProperty("ready", "false")
            self.btn_assign.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

        self.btn_assign.style().unpolish(self.btn_assign)
        self.btn_assign.style().polish(self.btn_assign)

    def pick_exe(self):
        p, _ = QFileDialog.getOpenFileName(self, "Виберіть програму", "", "Programs (*.exe);;All Files (*)")
        if p:
            self.add_recent("EXE", p)

    def commit_assignment(self):
        if not self.selected_btn or not self.staged_val:
            return
        self.set_action(self.selected_btn, self.staged_val)
        self.update_assign_ui()
        # Раніше update_assign_ui() викликався ПІСЛЯ і одразу перезаписував "ЗБЕРЕЖЕНО"
        self.btn_assign.setText("ЗБЕРЕЖЕНО")
        self.btn_assign.setIcon(icons.icon("check", "#0a0a0a"))
        self.btn_assign.setIconSize(QSize(20, 20))
        self.btn_assign.setStyleSheet("background-color: #00ff66; color: black;")
        self.btn_assign.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

        def _restore():
            self.btn_assign.setIcon(QIcon())
            self.btn_assign.setStyleSheet("")
            self.update_assign_ui()
        QTimer.singleShot(1500, _restore)

    def update_status(self, text, color):
        # Під час прошивки плата штатно "зникає" — не перетираємо статус "Прошивка плати..."
        if self._flashing:
            return
        if self.lbl_status.text() != text:
            self.lbl_status.setText(text)

    def setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self)

        icon_path = os.path.join(ASSETS_DIR, "icon.ico")
        custom_icon = QIcon(icon_path)

        self.setWindowIcon(custom_icon)

        self.tray_icon.setIcon(custom_icon)
        self.tray_icon.setToolTip("VPT | Pad")

        tray_menu = QMenu()

        show_act = QAction("Відкрити налаштування", self)
        show_act.triggered.connect(self.show_window)
        tray_menu.addAction(show_act)

        tray_menu.addSeparator()

        quit_act = QAction("Вихід", self)
        quit_act.triggered.connect(self.quit_app)
        tray_menu.addAction(quit_act)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.tray_activated)
        self.tray_icon.show()

    def tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_window()

    def show_window(self):
        self.show()
        self.activateWindow()

    def quit_app(self):
        self.tray_icon.hide()
        self.cleanup_threads()
        from PySide6.QtWidgets import QApplication
        QApplication.quit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_dynamic_layout()

        if hasattr(self, 'drag_overlay') and self.drag_overlay:
            self.drag_overlay.resize(self.centralWidget().size())

        if hasattr(self, 'tutorial_overlay') and self.tutorial_overlay:
            if self.centralWidget():
                self.tutorial_overlay.resize(self.centralWidget().size())

        if hasattr(self, 'update_tutorial_controls_pos'):
            self.update_tutorial_controls_pos()

    def closeEvent(self, event):
        event.ignore()
        self.hide()

    def nativeEvent(self, eventType, message):
        try:
            if eventType == b"windows_generic_MSG" or eventType == "windows_generic_MSG":
                msg = ctypes.wintypes.MSG.from_address(int(message))
                # 0x0218 = WM_POWERBROADCAST (0x0012 = PBT_APMRESUMEAUTOMATIC, 0x0007 = PBT_APMRESUMESUSPEND)
                if msg.message == 0x0218 and msg.wParam in (0x0012, 0x0007, 0x0006):
                    if hasattr(self, 'serial_thread'):
                        self.lbl_status.setText("<font color='#888888'>●</font> Відновлення...")
                        self.serial_thread.force_reconnect()
        except Exception:
            pass
        return super().nativeEvent(eventType, message)
