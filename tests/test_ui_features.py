"""Функції головного вікна: дублювання профілю, трей, верстка з редактором групи,
підсвітка фізичних натискань, налаштування, YouTube-дії, перевірка UF2."""
import os
import struct
import time

import pytest

import action_executor as ae
import threads as th
import updater
from conftest import process_events_for


@pytest.fixture
def window(qapp, monkeypatch, fresh_config):
    monkeypatch.setattr(th.serial.tools.list_ports, "comports", lambda: [])
    monkeypatch.setattr(updater, "get_latest_release_data", lambda: {})
    import main_window
    w = main_window.MacroPadPro()
    w.resize(1200, 750)
    w.show()
    process_events_for(qapp, 200)
    yield w
    w.cleanup_threads()
    w.hide()


def test_duplicate_profile(window):
    w = window
    profiles = w.config["PROFILES"]
    n = len(profiles)
    src = profiles[2]
    src["app_bind"] = "chrome.exe"
    w.duplicate_profile(2)
    assert len(profiles) == n + 1
    copy_ = profiles[-1]
    assert copy_["name"] == f"{src['name']} (копія)"
    assert copy_["actions"] == src["actions"] and copy_["actions"] is not src["actions"]
    assert copy_["app_bind"] == ""          # дві прив'язки до однієї програми конфліктували б
    assert w.active_profile_idx == n
    w.duplicate_profile(2)
    assert profiles[-1]["name"] == f"{src['name']} (копія) 2"


def test_tray_profile_menu(window):
    w = window
    w.switch_profile(1)
    w._fill_tray_profiles_menu()
    acts = w.tray_profiles_menu.actions()
    assert len(acts) == len(w.config["PROFILES"])
    assert [a.isChecked() for a in acts].index(True) == 1
    acts[2].trigger()
    assert w.active_profile_idx == 2


def test_first_close_explains_tray_once(window, qapp):
    w = window
    shown = []
    w.tray_icon.showMessage = lambda *a: shown.append(a[0])
    assert not w.config.get("tray_hint_shown")
    w.close()
    w.show(); w.close()
    assert len(shown) == 1 and w.config["tray_hint_shown"] is True


def test_reset_button_moved_to_settings(window):
    from widgets import SettingsDialog
    assert not hasattr(window, "btn_reset")
    SettingsDialog.check_autostart = lambda self: False
    d = SettingsDialog(window)
    assert d.btn_reset.text().startswith("Скинути призначення")
    assert d.btn_flash.isEnabled() is False      # плата не підключена
    d.close()


def _overlap(a, b):
    return a.geometry().intersects(b.geometry())


@pytest.mark.parametrize("width", [1000, 1200, 1500])
def test_group_editor_never_pushes_pad_under_profiles(window, qapp, width):
    w = window
    w.resize(width, 750)
    w.config["MULTI_LAUNCH"]["Робота"] = [{"action": "URL:example.com", "delay": 0.5}]
    w.edit_multi_group("Робота")
    process_events_for(qapp, 600)
    pad, profiles = w.pad_frame, w.profiles_scroll
    # макет не залазить під колонку профілів і не виходить за межі панелі
    assert not _overlap(pad, profiles), (pad.geometry(), profiles.geometry())
    assert pad.geometry().right() < w.right_panel.width()
    if width >= 1500:   # місця досить — редактор стоїть поруч, а не поверх
        assert not _overlap(pad, w.multi_editor)
    w.multi_editor.hide_editor()
    process_events_for(qapp, 500)


def test_physical_press_lights_up_pad(window, qapp):
    w = window
    w.executor.execute("BTN_5_PRESSED", 2)
    w.executor.execute("ENC_2_SW_PRESSED", 2)
    w.executor.execute("ENC_1_RIGHT:A1", 2)
    process_events_for(qapp, 50)
    assert w.ui_pad_btns["BTN_5"].hw_glow > 0.9
    assert w.ui_pad_btns["ENC_2"].hw_sw_glow > 0.9
    assert w.ui_pad_btns["ENC_1"].hw_rot_part == "right"
    w.executor.execute("BTN_5_RELEASED", 2)
    process_events_for(qapp, 500)
    assert w.ui_pad_btns["BTN_5"].hw_glow < 0.05
    # плата відключилась, поки кнопку тримали — підсвітка не "залипає"
    w.executor.execute("BTN_3_PRESSED", 2)
    process_events_for(qapp, 30)
    w.on_link_changed(False, 2, "", "")
    process_events_for(qapp, 500)
    assert w.ui_pad_btns["BTN_3"].hw_glow < 0.05


def test_youtube_action_without_extension_warns(window, qapp):
    w = window
    osd = []
    w.trigger_osd = lambda mode, title, *a, **k: osd.append(title)
    w.executor._execute_oneshot("EXT:YT_NEXT", "BTN_1")
    assert osd == ["Розширення YouTube не підключене"]
    # повторне натискання одразу — без потоку однакових повідомлень
    w.executor._execute_oneshot("EXT:YT_NEXT", "BTN_1")
    assert len(osd) == 1


def test_youtube_feedback_osd(window):
    w = window
    shown = []
    w.trigger_osd = lambda mode, title, val=0.0, icon_text="", is_danger=False, app_exe="": shown.append((mode, title, round(val, 2), icon_text))
    base = {"ok": True, "err": "", "note": "", "site": "yt", "title": "Відео", "paused": False,
            "muted": False, "live": False, "time": 90.0, "dur": 600.0, "vol": 40.0, "rate": 1.5}
    w.on_yt_feedback({**base, "cmd": "SEEK"})
    w.on_yt_feedback({**base, "cmd": "VOL"})
    w.on_yt_feedback({**base, "cmd": "SPEED"})
    w.on_yt_feedback({**base, "cmd": "PLAYPAUSE", "paused": True})
    w.on_yt_feedback({**base, "ok": False, "err": "no_video"})
    assert shown == [
        ("progress", "1:30 / 10:00", 0.15, "timeline"),
        ("volume", "Гучність YouTube", 0.4, "volume"),
        ("status", "Швидкість 1.5×\nВідео", 0.0, "forward"),
        ("status", "Пауза\nВідео", 0.0, "play-pause"),
        ("status", "YouTube: немає відкритого відео", 0.0, "youtube"),
    ]


# ------------------------------------------------------------ перевірка файлу прошивки
def _uf2(n_blocks=3, family=0xE48BFF56, bad_block=None):
    out = bytearray()
    for i in range(n_blocks):
        blk = struct.pack("<8I", 0x0A324655, 0x9E5D5157, 0x2000, 0x10000000 + 256 * i, 256, i, n_blocks, family)
        blk += bytes(476) + struct.pack("<I", 0x0AB16F30)
        if i == bad_block:
            blk = b"X" * 512
        out += blk
    return bytes(out)


def test_inspect_uf2(tmp_path):
    ok = tmp_path / "ok.uf2"; ok.write_bytes(_uf2())
    assert updater.inspect_uf2(str(ok)) == (True, 3)
    cases = {
        "trunc.uf2": _uf2()[:-512],
        "family.uf2": _uf2(family=0x12345678),
        "garbage.uf2": b"MZ" + bytes(1022),
        "broken.uf2": _uf2(bad_block=1),
        "odd.uf2": _uf2() + b"x",
    }
    for name, data in cases.items():
        p = tmp_path / name
        p.write_bytes(data)
        assert updater.inspect_uf2(str(p))[0] is False, name


def test_bundled_firmware_passes_check():
    """Зібрана прошивка в репозиторії — коректний UF2 для RP2040 (її прошиває кнопка в налаштуваннях)."""
    import glob
    files = glob.glob(os.path.join(os.path.dirname(__file__), "..", "firmware", "uf2", "*.uf2"))
    assert files
    for f in files:
        ok, info = updater.inspect_uf2(f)
        assert ok is True, (f, info)


def test_settings_standalone_profile_and_defaults(window, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from widgets import SettingsDialog
    w = window
    SettingsDialog.check_autostart = lambda self: False
    d = SettingsDialog(w)
    assert d.combo_standalone.count() == len(w.config["PROFILES"])
    assert d.combo_standalone.currentIndex() == 0
    d.combo_standalone.setCurrentIndex(1)
    assert w.standalone_profile_index() == 1 and w.config["standalone_profile"] == 1

    # видалення профілю зсуває номер профілю "без програми"
    w.delete_profile(0)
    assert w.standalone_profile_index() == 0
    assert w.config["PROFILES"][0]["name"] == "NumPad"

    # відновлення стандартних профілів
    w.config["PROFILES"][0]["name"] = "Мій"
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    d.restore_defaults()
    assert [p["name"] for p in w.config["PROFILES"]] == ["Медіа", "NumPad", "Офіс і браузер"]
    assert w.active_profile_idx == 0 and w.standalone_profile_index() == 0
