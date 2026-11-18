"""Набір SVG-іконок: усі файли валідні, усі згадані в коді іконки існують,
у теці немає зайвих (невикористаних) файлів."""
import glob
import os
import re

import pytest

import icons
from conftest import ROOT


def test_all_svgs_are_valid_and_tintable(qapp):
    files = sorted(glob.glob(os.path.join(icons.ICONS_DIR, "*.svg")))
    assert len(files) >= 20
    for f in files:
        name = os.path.basename(f)[:-4]
        text = open(f, encoding="utf-8").read()
        assert "currentColor" in text, f"{name}: не фарбується (немає currentColor)"
        assert 'viewBox="0 0 24 24"' in text, name
        assert icons._renderer(name, "#ff0000") is not None, f"{name}: невалідний SVG"
        pm = icons.pixmap(name, 24, "#ff0000")
        assert not pm.toImage().isNull()


def _sources():
    return [open(f, encoding="utf-8").read() for f in glob.glob(os.path.join(ROOT, "*.py"))]


def test_every_icon_referenced_in_code_exists():
    """Назва, передана напряму в icons.icon()/pixmap()/paint_icon(), icon_name= чи icon_text= (OSD), має існувати."""
    pat = re.compile(r'(?:icons\.(?:icon|pixmap)\(|icons\.paint_icon\(\w+,\s*|icon_name=|icon_text=)"([a-z][a-z0-9-]*)"')
    used = set()
    for src in _sources():
        used.update(pat.findall(src))
    assert len(used) > 20
    assert sorted(n for n in used if not icons.has_icon(n)) == []


def test_no_unused_icon_files():
    """У теці іконок немає файлів, назва яких ніде в коді не згадується."""
    code = "\n".join(_sources())
    on_disk = sorted(os.path.basename(f)[:-4] for f in glob.glob(os.path.join(icons.ICONS_DIR, "*.svg")))
    assert [n for n in on_disk if f'"{n}"' not in code] == []
