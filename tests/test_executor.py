"""Тести машини станів ActionExecutor (Tap / Double-Tap / Hold, HW-позначки протоколу v2,
залипання клавіш, відпускання при втраті зв'язку)."""
import threading
import time

import pytest

import action_executor as ae
from config import action_to_hid_spec
from conftest import process_events_for


class FakeApp:
    """Мінімальна заміна MacroPadPro для executor-а."""

    def __init__(self):
        self.triggers = {}
        self.actions = {}
        self.config = {"PROFILES": [{"name": "A", "actions": {}}, {"name": "B", "actions": {}}], "MACROS": {}}
        self.active_profile_idx = 0
        self.volume_states = {"sys": 0.5, "mic": 0.5, "brightness": 0.7, "apps": {}}
        self.mute_states = {"sys": False, "mic": False, "apps": {}}
        self.osd = []
        self.profile_switches = []
        self.enc_cycles = []

    def get_button_triggers(self, bid):
        return dict(self.triggers.get(bid, {"tap": "NONE", "dtap": "NONE", "hold": "NONE"}))

    def get_action(self, bid, trigger=None):
        return self.actions.get(bid, "NONE")

    def get_enc_active_action(self, base):
        return self.actions.get(base, "NONE")

    def is_button_fully_hw(self, bid):
        vals = [v for v in self.get_button_triggers(bid).values() if v != "NONE"]
        return bool(vals) and all(action_to_hid_spec(v).startswith("HID_") for v in vals)

    def is_enc_dir_hw_handled(self, base, is_r):
        return False

    def request_profile_switch(self, idx, from_hotkey=False, is_temp_hold=False):
        self.profile_switches.append((idx, is_temp_hold))
        self.active_profile_idx = idx

    def trigger_osd(self, mode, title, val=0.0, icon_text="", is_danger=False, app_exe=""):
        self.osd.append(title)

    def update_instant_vol(self, target, vol, is_app=False):
        if is_app:
            self.volume_states["apps"][target] = vol
        else:
            self.volume_states[target] = vol

    def cycle_enc_mode(self, base):
        self.enc_cycles.append(base)


@pytest.fixture
def env(qapp, monkeypatch):
    log = []
    lock = threading.Lock()

    def rec(name):
        def _f(*args):
            with lock:
                log.append((name,) + args)
        return _f

    monkeypatch.setattr(ae, "win_hotkey", rec("hotkey"))
    monkeypatch.setattr(ae, "win_hotkey_down", rec("down"))
    monkeypatch.setattr(ae, "win_hotkey_up", rec("up"))
    monkeypatch.setattr(ae, "win_key_event", rec("key"))
    monkeypatch.setattr(ae, "send_unicode_text", rec("text"))
    app = FakeApp()
    ex = ae.ActionExecutor(app)

    def drain(ms=30):
        process_events_for(qapp, ms)
        # дочекатись, поки воркер вводу виконає чергу
        end = time.monotonic() + 1.0
        while not ex._input_q.empty() and time.monotonic() < end:
            time.sleep(0.002)
        time.sleep(0.01)

    return app, ex, log, drain, qapp


def test_unknown_and_garbage_lines_are_ignored(env):
    app, ex, log, drain, _ = env
    for raw in ("", "GARBAGE", "BTN_99_PRESSED", "ENC_7_RIGHT", "BTN_1", ":HW", "PRESSED"):
        ex.execute(raw, 2)
    drain()
    assert log == []


def test_fast_path_hotkey_hold_and_release(env):
    app, ex, log, drain, _ = env
    app.triggers["BTN_1"] = {"tap": "HOTKEY:ctrl+c", "dtap": "NONE", "hold": "NONE"}
    ex.execute("BTN_1_PRESSED", 2)
    drain()
    assert log == [("down", "ctrl+c")]
    ex.execute("BTN_1_RELEASED", 2)
    drain()
    assert log[-1] == ("up", "ctrl+c")


def test_hw_tagged_events_are_not_duplicated(env):
    """v2: плата вже виконала дію — ПК не має повторювати її, навіть якщо його конфіг каже SERIAL."""
    app, ex, log, drain, _ = env
    app.triggers["BTN_1"] = {"tap": "MACRO:x", "dtap": "NONE", "hold": "NONE"}  # для ПК це SERIAL
    ex.execute("BTN_1_PRESSED:HW", 2)
    ex.execute("BTN_1_RELEASED:HW", 2)
    drain()
    assert log == []
    assert ex.running_macros == {}


def test_untagged_v2_event_executes_even_if_config_says_hw(env):
    """v2 без :HW — плата НЕ виконала (наприклад, ще не отримала нову прив'язку), отже виконує ПК."""
    app, ex, log, drain, _ = env
    app.triggers["BTN_1"] = {"tap": "HOTKEY:ctrl+v", "dtap": "NONE", "hold": "NONE"}  # для ПК це HID
    ex.execute("BTN_1_PRESSED", 2)
    ex.execute("BTN_1_RELEASED", 2)
    drain()
    assert ("down", "ctrl+v") in log and ("up", "ctrl+v") in log


def test_legacy_v1_guesses_from_config(env):
    app, ex, log, drain, _ = env
    app.triggers["BTN_1"] = {"tap": "HOTKEY:ctrl+v", "dtap": "NONE", "hold": "NONE"}
    ex.execute("BTN_1_PRESSED", 1)
    ex.execute("BTN_1_RELEASED", 1)
    drain()
    assert log == []  # стара прошивка обробила апаратно


def test_no_stuck_key_when_profile_changes_while_held(env):
    """Регресія: відпускання брало дію з НОВОГО профілю -> Ctrl лишався натиснутим."""
    app, ex, log, drain, _ = env
    app.triggers["BTN_1"] = {"tap": "HOTKEY:ctrl", "dtap": "NONE", "hold": "NONE"}
    ex.execute("BTN_1_PRESSED", 2)
    app.triggers["BTN_1"] = {"tap": "HOTKEY:x", "dtap": "NONE", "hold": "NONE"}  # автоперемикання профілю
    ex.execute("BTN_1_RELEASED", 2)
    drain()
    assert log == [("down", "ctrl"), ("up", "ctrl")]


def test_tap_dtap_hold(env):
    app, ex, log, drain, _ = env
    app.triggers["BTN_2"] = {"tap": "HOTKEY:a", "dtap": "HOTKEY:b", "hold": "HOTKEY:c"}

    ex.execute("BTN_2_PRESSED", 2); drain(50)
    ex.execute("BTN_2_RELEASED", 2); drain(50)
    assert log == []                       # чекаємо вікно подвійного тапу
    drain(250)
    assert log == [("hotkey", "a")]

    log.clear()
    ex.execute("BTN_2_PRESSED", 2); drain(30)
    ex.execute("BTN_2_RELEASED", 2); drain(60)
    ex.execute("BTN_2_PRESSED", 2); drain(30)
    ex.execute("BTN_2_RELEASED", 2); drain(300)
    assert log == [("hotkey", "b")]

    log.clear()
    ex.execute("BTN_2_PRESSED", 2); drain(400)
    assert log == [("down", "c")]
    ex.execute("BTN_2_RELEASED", 2); drain(300)
    assert log == [("down", "c"), ("up", "c")]


def test_hold_timer_ignores_stale_press(env):
    app, ex, log, drain, _ = env
    app.triggers["BTN_3"] = {"tap": "HOTKEY:a", "dtap": "NONE", "hold": "HOTKEY:c"}
    ex.execute("BTN_3_PRESSED", 2); drain(100)
    ex.execute("BTN_3_RELEASED", 2); drain(10)
    ex.execute("BTN_3_PRESSED", 2); drain(100)   # нове натискання до спрацювання старого таймера
    ex.execute("BTN_3_RELEASED", 2); drain(400)
    assert ("down", "c") not in log
    assert log.count(("hotkey", "a")) == 2


def test_disconnect_releases_held_keys(env):
    app, ex, log, drain, _ = env
    app.triggers["BTN_1"] = {"tap": "HOTKEY:shift", "dtap": "NONE", "hold": "NONE"}
    ex.execute("BTN_1_PRESSED", 2); drain()
    ex.on_device_disconnected(); drain()
    assert log == [("down", "shift"), ("up", "shift")]
    ex.execute("BTN_1_RELEASED", 2); drain()   # запізніле відпускання не дублюється
    assert log == [("down", "shift"), ("up", "shift")]


def test_profile_hold_layer_returns_back(env):
    app, ex, log, drain, _ = env
    app.triggers["BTN_9"] = {"tap": "SYS:PROFILE_HOLD:1", "dtap": "NONE", "hold": "NONE"}
    ex.execute("BTN_9_PRESSED", 2); drain()
    assert app.profile_switches == [(1, True)]
    app.triggers["BTN_9"] = {"tap": "HOTKEY:x", "dtap": "NONE", "hold": "NONE"}  # у шарі B кнопка інша
    ex.execute("BTN_9_RELEASED", 2); drain()
    assert app.profile_switches == [(1, True), (0, False)]
    assert log == []


def test_repeat_macro_on_encoder_runs_once(env):
    """Регресія: макрос 'Repeat while held' на обертанні енкодера крутився нескінченно."""
    app, ex, log, drain, _ = env
    app.config["MACROS"]["rep"] = '{"mode": "Repeat while held", "events": [{"type": "tap", "val": "a"}], "cycle_delay": 5}'
    app.actions["ENC_1_R"] = "MACRO:rep"
    ex.execute("ENC_1_RIGHT", 2)
    drain(150)
    assert log.count(("key", "a", "tap")) == 1
    assert ex.running_macros == {}


def test_rotation_hw_tag_controls_extra_steps(env):
    app, ex, log, drain, _ = env
    app.actions["ENC_1"] = "ENC:VOL"
    ex.execute("ENC_1_RIGHT:HW", 2)       # перший тик — плата вже натиснула Volume Up
    drain()
    assert [e for e in log if e[0] == "key"] == []
    ex.execute("ENC_1_RIGHT", 2)          # без :HW — ПК робить крок сам
    drain()
    assert any(e[:2] == ("key", "volumeup") for e in log)
    assert app.osd and app.osd[-1] == "Гучність системи"


def test_hw_fired_mute_shows_osd(env):
    app, ex, log, drain, _ = env
    app.triggers["BTN_4"] = {"tap": "MED:PLAY", "dtap": "NONE", "hold": "MED:MUTE"}
    ex.execute("BTN_4_PRESSED:HW", 2)
    ex.execute("BTN_4_FIRED:HOLD", 2)
    ex.execute("BTN_4_RELEASED:HW", 2)
    drain()
    assert app.osd == ["Звук вимкнено"]
    assert log == []


def test_board_accel_flag_is_used(env):
    """Прискорення, виміряне платою (:A<n>), має пріоритет над оцінкою за часом приходу подій."""
    app, ex, log, drain, _ = env
    app.actions["ENC_2"] = "ENC:TIMELINE"
    ex.execute("ENC_2_RIGHT:A5", 2)
    drain()
    assert log.count(("key", "right", "tap")) == 5
    log.clear()
    time.sleep(0.2)                      # щоб і локальна оцінка дала 1
    ex.execute("ENC_2_LEFT:HW:A3", 2)    # плата вже натиснула 1 раз -> ПК додає 2
    drain()
    assert log.count(("key", "left", "tap")) == 2


def test_accel_flag_ignored_on_legacy_protocol(env):
    app, ex, log, drain, _ = env
    app.actions["ENC_2"] = "ENC:TIMELINE"
    time.sleep(0.2)
    ex.execute("ENC_2_RIGHT:A5", 1)      # v1 не має суфіксів — сміття ігнорується
    drain()
    assert log.count(("key", "right", "tap")) == 1


class FakeMonitor:
    def __init__(self, level):
        self.level = level
        self.sets = []
        self.reads = 0

    def get(self, allow_wmi=True):
        self.reads += 1
        return self.level

    def set(self, val):
        self.sets.append(round(val, 3))
        self.level = val


def test_brightness_starts_from_real_value_and_resyncs(qapp, monkeypatch):
    mon = FakeMonitor(0.40)
    monkeypatch.setattr(ae, "get_monitor_brightness", mon.get)
    monkeypatch.setattr(ae, "set_monitor_brightness", mon.set)
    app = FakeApp()
    ex = ae.ActionExecutor(app)
    # стартове зчитування доходить до UI (а не припущені 70%)
    process_events_for(qapp, 150)
    assert app.volume_states["brightness"] == pytest.approx(0.40)

    app.actions["ENC_3"] = "ENC:BRIGHTNESS"
    ex.execute("ENC_3_RIGHT:A1", 2)
    process_events_for(qapp, 150)
    assert mon.sets[-1] == pytest.approx(0.43)
    assert app.volume_states["brightness"] == pytest.approx(0.43)

    # Яскравість змінили кнопками монітора, а енкодер довго не чіпали ->
    # перед наступним кроком значення перечитується, без "стрибка" від старого
    mon.level = 0.80
    ex._br_last_sync -= 100
    ex.execute("ENC_3_RIGHT:A1", 2)
    process_events_for(qapp, 200)
    assert mon.sets[-1] == pytest.approx(0.83)
    assert app.volume_states["brightness"] == pytest.approx(0.83)

    # Швидкі кроки поспіль застосовуються відносно, без перечитування
    reads = mon.reads
    for _ in range(3):
        ex.execute("ENC_3_LEFT:A1", 2)
    process_events_for(qapp, 300)
    assert mon.level == pytest.approx(0.74)
    assert mon.reads == reads
    assert app.volume_states["brightness"] == pytest.approx(0.74)


def test_brightness_without_readback_keeps_old_behaviour(qapp, monkeypatch):
    mon = FakeMonitor(None)
    monkeypatch.setattr(ae, "get_monitor_brightness", mon.get)
    monkeypatch.setattr(ae, "set_monitor_brightness", mon.set)
    app = FakeApp()
    ex = ae.ActionExecutor(app)
    app.actions["ENC_3"] = "ENC:BRIGHTNESS"
    ex.execute("ENC_3_RIGHT:A1", 2)
    process_events_for(qapp, 150)
    assert mon.sets[-1] == pytest.approx(0.73)
