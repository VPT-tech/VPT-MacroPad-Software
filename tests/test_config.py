import pytest

from config import split_hotkey_tokens, action_to_hid_spec, encoder_action_to_hid_spec, ARDUINO_HID_KEY_MAP


@pytest.mark.parametrize("combo,expected", [
    ("ctrl+c", ["ctrl", "c"]),
    ("CTRL + Shift + A", ["ctrl", "shift", "a"]),
    ("num +", ["num +"]),                 # регресія: раніше ['__NUM_PLUS__']
    ("ctrl+num +", ["ctrl", "num +"]),
    ("ctrl++", ["ctrl", "+"]),            # регресія: раніше ['ctrl', '__PLUS_KEY__']
    ("+", ["+"]),
    ("ctrl+=", ["ctrl", "="]),
    ("", []),
])
def test_split_hotkey_tokens(combo, expected):
    assert split_hotkey_tokens(combo) == expected


@pytest.mark.parametrize("act,spec", [
    ("NONE", "NONE"),
    ("", "NONE"),
    ("MED:PLAY", "HID_MEDIA:1"),
    ("MED:VOL_DOWN", "HID_MEDIA:6"),
    ("MED:MIC_MUTE", "SERIAL"),
    ("SYS:TASK", "HID_KEY:3:177"),        # ctrl+shift+esc
    ("SYS:LOCK", "HID_KEY:8:108"),        # win+l
    ("SYS:PROFILE_NEXT", "SERIAL"),
    ("HOTKEY:ctrl+c", "HID_KEY:1:99"),
    ("HOTKEY:num +", f"HID_KEY:0:{ARDUINO_HID_KEY_MAP['num +']}"),
    ("HOTKEY:ctrl++", "HID_KEY:1:43"),
    ("HOTKEY:f13", f"HID_KEY:0:{ARDUINO_HID_KEY_MAP['f13']}"),
    ("HOTKEY:ctrl+a+b", "SERIAL"),        # дві основні клавіші — прошивка не вміє
    ("HOTKEY:ctrl+й", "SERIAL"),          # не-ASCII — лише через ПК
    ("HOTKEY:mouse_left", "HID_MOUSE:1"),
    ("HOTKEY:mouse_wheel_down", "HID_MOUSE:5"),
    ("MACRO:x", "SERIAL"),
    ("TEXT:hello", "SERIAL"),
])
def test_action_to_hid_spec(act, spec):
    assert action_to_hid_spec(act) == spec


def test_hid_specs_are_valid_for_firmware():
    """Усе, що генерує ПК, має бути в діапазонах, які приймає прошивка (mods<=15, key<=255)."""
    for key in list(ARDUINO_HID_KEY_MAP) + ["a", "z", "0", "[", "`"]:
        for mods in ("", "ctrl+", "ctrl+shift+alt+win+"):
            spec = action_to_hid_spec(f"HOTKEY:{mods}{key}")
            assert spec.startswith("HID_KEY:")
            _, m, k = spec.split(":")
            assert 0 <= int(m) <= 15 and 0 < int(k) <= 255


@pytest.mark.parametrize("act,is_r,spec", [
    ("ENC:VOL", True, "HID_MEDIA:5"),
    ("ENC:VOL", False, "HID_MEDIA:6"),
    ("ENC:SCROLL", True, "HID_MOUSE:5"),
    ("ENC:ZOOM", True, "HID_KEY:1:61"),
    ("ENC:ZOOM", False, "HID_KEY:1:45"),
    ("ENC:BRIGHTNESS", True, "SERIAL"),
    ("ENC:APP:discord.exe", True, "SERIAL"),
    ("NONE", True, "NONE"),
])
def test_encoder_action_to_hid_spec(act, is_r, spec):
    assert encoder_action_to_hid_spec(act, is_r) == spec
