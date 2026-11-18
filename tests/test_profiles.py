"""Стандартні профілі "з коробки" та профіль для роботи без програми."""
import os
import re

import pytest

from config import (BUILTIN_PRESETS, action_to_hid_spec, profile_to_hw_specs, profile_button_triggers,
                    HW_BUTTON_IDS)
from conftest import ROOT

FW = os.path.join(ROOT, "firmware", "VPT_MacroPad", "VPT_MacroPad.ino")


def test_three_basic_profiles_without_app_specific_ones():
    names = [p["name"] for p in BUILTIN_PRESETS.values()]
    assert names == ["Медіа", "NumPad", "Офіс і браузер"]
    for p in BUILTIN_PRESETS.values():
        assert p["app_bind"] == ""


@pytest.mark.parametrize("name", list(BUILTIN_PRESETS))
def test_every_button_is_assigned_and_profile_switch_is_reachable(name):
    prof = BUILTIN_PRESETS[name]
    for bid in HW_BUTTON_IDS:
        assert profile_button_triggers(prof, bid)["tap"] != "NONE", (name, bid)
    # з кожного профілю можна перейти на наступний (утримання нижньої крутилки)
    assert profile_button_triggers(prof, "ENC_3_SW")["hold"] == "SYS:PROFILE_NEXT"
    # нижня крутилка — гучність у всіх профілях
    assert prof["actions"]["ENC_3"] == "ENC:VOL"


@pytest.mark.parametrize("name", list(BUILTIN_PRESETS))
def test_profiles_work_without_the_app_as_much_as_possible(name):
    prof = BUILTIN_PRESETS[name]
    specs = profile_to_hw_specs(prof, standalone=True)
    assert "SERIAL" not in specs.values()
    # усі кнопки (крім тих, кому потрібна програма) та обидва напрямки всіх крутилок працюють самі
    for i in (1, 2, 3):
        assert specs[f"ENC_{i}_L"].startswith("HID_") and specs[f"ENC_{i}_R"].startswith("HID_"), (name, i)
    needs_app = [b for b in HW_BUTTON_IDS if specs[f"{b}:TAP"] == "NONE"]
    assert needs_app in ([], ["BTN_5"]), needs_app        # у «Медіа» BTN_5 — мут мікрофона


def test_numpad_layout_matches_a_real_numpad():
    prof = BUILTIN_PRESETS["NumPad"]
    taps = [profile_button_triggers(prof, f"BTN_{i}")["tap"] for i in range(1, 10)]
    assert taps == [f"HOTKEY:num {d}" for d in (7, 8, 9, 4, 5, 6, 1, 2, 3)]
    specs = profile_to_hw_specs(prof)
    # цифри — "швидкий шлях" (лише tap): натискання йде на хост одразу, працює автоповтор
    for i in range(1, 10):
        assert specs[f"BTN_{i}:TAP"].startswith("HID_KEY:0:")
        assert specs[f"BTN_{i}:DTAP"] == specs[f"BTN_{i}:HOLD"] == "NONE"
    assert action_to_hid_spec("HOTKEY:num 0") == specs["ENC_1_SW:TAP"]


def _firmware_default_table():
    src = open(FW, encoding="utf-8").read()
    btn = re.search(r"DEFAULT_BUTTON_SPECS\[NUM_BTNS\]\[3\] = \{(.*?)\n\};", src, re.S).group(1)
    enc = re.search(r"DEFAULT_ENCODER_SPECS\[NUM_ENC\]\[2\] = \{(.*?)\n\};", src, re.S).group(1)
    rows = [re.findall(r'"([^"]+)"', line) for line in btn.splitlines() if '"' in line]
    erows = [re.findall(r'"([^"]+)"', line) for line in enc.splitlines() if '"' in line]
    table = {}
    for bid, row in zip(HW_BUTTON_IDS, rows):
        table.update({f"{bid}:TAP": row[0], f"{bid}:DTAP": row[1], f"{bid}:HOLD": row[2]})
    for i, row in enumerate(erows, 1):
        table.update({f"ENC_{i}_L": row[0], f"ENC_{i}_R": row[1]})
    return table


def test_firmware_built_in_profile_equals_app_profile_1():
    """Нова плата з коробки поводиться так само, як після підключення програми з профілем «Медіа»."""
    fw = _firmware_default_table()
    assert len(fw) == 42
    assert fw == profile_to_hw_specs(BUILTIN_PRESETS["Медіа"], standalone=True)
