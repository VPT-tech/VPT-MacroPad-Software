"""Набір SVG-іконок: усі файли валідні, усі згадані в коді іконки існують,
кожна стандартна дія має іконку."""
import glob
import os
import re

import pytest

import icons
from config import BUILTIN_PRESETS, FRIENDLY_NAMES
from conftest import ROOT


def test_all_svgs_are_valid_and_tintable(qapp):
    files = sorted(glob.glob(os.path.join(icons.ICONS_DIR, "*.svg")))
    assert len(files) >= 60
    for f in files:
        name = os.path.basename(f)[:-4]
        text = open(f, encoding="utf-8").read()
        assert "currentColor" in text, f"{name}: не фарбується (немає currentColor)"
        assert 'viewBox="0 0 24 24"' in text, name
        assert icons._renderer(name, "#ff0000") is not None, f"{name}: невалідний SVG"
        pm = icons.pixmap(name, 24, "#ff0000")
        assert not pm.toImage().isNull()


def _names_used_in_code():
    pat = re.compile(r'(?:icons\.icon|icons\.pixmap|icon_name=|icon_text=|_set_update_btn\([^,]+,)\s*\(?\s*"([a-z][a-z0-9-]*)"')
    used = set()
    for f in glob.glob(os.path.join(ROOT, "*.py")):
        for m in pat.finditer(open(f, encoding="utf-8").read()):
            used.add(m.group(1))
    return used


def test_every_icon_referenced_in_code_exists():
    used = _names_used_in_code()
    assert len(used) > 30
    missing = sorted(n for n in used if not icons.has_icon(n))
    assert missing == []


def test_mapping_targets_exist():
    targets = set(icons._EXACT.values()) | {n for _, n in icons._PREFIX} | set(icons._HOTKEYS.values()) | {"keyboard", "mouse"}
    assert sorted(n for n in targets if not icons.has_icon(n)) == []


def _all_preset_actions():
    for prof in BUILTIN_PRESETS.values():
        for v in prof["actions"].values():
            if isinstance(v, dict):
                yield from (x for x in v.values() if x != "NONE")
            else:
                yield v
        for modes in prof.get("enc_modes", {}).values():
            yield from modes


@pytest.mark.parametrize("act", sorted(set(_all_preset_actions()) | set(k for k in FRIENDLY_NAMES if k != "NONE")))
def test_every_standard_action_has_icon(act):
    assert icons.action_icon_name(act) is not None, act


def test_unknown_or_empty_action_has_no_icon():
    assert icons.action_icon_name("NONE") is None
    assert icons.action_icon_name("") is None
    assert icons.action_icon_name("SOMETHING:NEW") is None
