# icons.py
# Набір іконок assets/icons/*.svg (лінійні, 24x24, stroke="currentColor").
# currentColor підміняється потрібним кольором під час рендеру, тож одна іконка
# може бути сірою, акцентною (бірюзовою) чи червоною залежно від стану.
import os

from PySide6.QtCore import Qt, QByteArray, QRectF
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
from PySide6.QtSvg import QSvgRenderer

ICONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icons")

ICON_COLOR = "#d6d6d6"
ICON_MUTED = "#8a8a8a"
ICON_ACCENT = "#00e5ff"
ICON_DANGER = "#ff3366"
ICON_DISABLED = "#4a4a4a"

# Розміри (у фізичних пікселях), з яких QIcon обирає найближчий — покриває 100–200% масштабу
_PIXMAP_SIZES = (16, 20, 24, 32, 40, 48, 64)

_svg_text_cache = {}
_renderer_cache = {}
_icon_cache = {}


def _svg_text(name):
    if name not in _svg_text_cache:
        try:
            with open(os.path.join(ICONS_DIR, f"{name}.svg"), encoding="utf-8") as f:
                _svg_text_cache[name] = f.read()
        except OSError:
            _svg_text_cache[name] = None
    return _svg_text_cache[name]


def has_icon(name):
    return bool(name) and _svg_text(name) is not None


def _renderer(name, color):
    key = (name, QColor(color).name(QColor.NameFormat.HexArgb))
    r = _renderer_cache.get(key)
    if r is None:
        text = _svg_text(name)
        if text is None:
            return None
        c = QColor(color)
        svg = text.replace("currentColor", c.name())
        if c.alpha() < 255:
            svg = svg.replace("<svg ", f'<svg opacity="{c.alphaF():.3f}" ', 1)
        r = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        if not r.isValid():
            return None
        _renderer_cache[key] = r
    return r


def paint_icon(painter, name, rect, color=ICON_COLOR):
    """Малює іконку в прямокутнику (QRectF/QRect). Повертає False, якщо іконки немає."""
    r = _renderer(name, color)
    if r is None:
        return False
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    r.render(painter, QRectF(rect))
    painter.restore()
    return True


def pixmap(name, size, color=ICON_COLOR):
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    r = _renderer(name, color)
    if r is not None:
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r.render(p, QRectF(0, 0, size, size))
        p.end()
    return pm


def icon(name, color=ICON_COLOR, active=None, disabled=ICON_DISABLED):
    """QIcon з іконки набору. active — колір при наведенні/виборі (за замовчуванням як color)."""
    key = (name, color, active, disabled)
    ic = _icon_cache.get(key)
    if ic is not None:
        return ic
    ic = QIcon()
    if has_icon(name):
        for size in _PIXMAP_SIZES:
            ic.addPixmap(pixmap(name, size, color), QIcon.Mode.Normal, QIcon.State.Off)
            if active:
                ic.addPixmap(pixmap(name, size, active), QIcon.Mode.Active, QIcon.State.Off)
                ic.addPixmap(pixmap(name, size, active), QIcon.Mode.Selected, QIcon.State.Off)
            if disabled:
                ic.addPixmap(pixmap(name, size, disabled), QIcon.Mode.Disabled, QIcon.State.Off)
    _icon_cache[key] = ic
    return ic


# ----------------------------------------------------------------- дія -> іконка
_EXACT = {
    "SYS:PROFILE_NEXT": "profile-next",
    "SYS:PROFILE_PREV": "profile-prev",
    "ENC:MODE_TOGGLE": "dial",
    "ENC:VOL": "volume",
    "ENC:BRIGHTNESS": "brightness",
    "ENC:SCROLL": "scroll",
    "ENC:ZOOM": "zoom",
    "ENC:TIMELINE": "timeline",
    "ENC:BRUSH": "brush",
    "ENC:UNDO_REDO": "history",
    "SYS:TASK": "activity",
    "SYS:DESKTOP": "desktop",
    "SYS:SNIP": "screenshot",
    "SYS:LOCK": "lock",
    "SYS:SLEEP": "sleep",
    "MED:PLAY": "play-pause",
    "MED:NEXT": "next",
    "MED:PREV": "prev",
    "MED:VOL_UP": "volume-up",
    "MED:VOL_DOWN": "volume-down",
    "MED:MUTE": "volume-x",
    "MED:MIC_MUTE": "mic-off",
    "EXT:YT_PLAYPAUSE": "youtube",
    "CMD:start spotify:": "music",
}
_PREFIX = (
    ("SYS:PROFILE_GOTO:", "profile-goto"),
    ("SYS:PROFILE_HOLD:", "layers"),
    ("EXT:YT_BACK", "rewind"),
    ("EXT:YT_FWD", "forward"),
    ("ENC:APP:", "mixer"),
    ("APP_MUTE:", "volume-x"),
    ("TEXT:", "type"),
    ("URL:", "globe"),
    ("EXE:", "app"),
    ("MULTI:", "launch"),
    ("MACRO:", "macro"),
    ("CMD:", "terminal"),
)
_HOTKEYS = {
    "ctrl+c": "copy",
    "ctrl+v": "paste",
    "ctrl+x": "cut",
    "ctrl+z": "undo",
    "ctrl+a": "select-all",
    "ctrl+s": "save",
    "alt+f4": "window-close",
}


def action_icon_name(val):
    """Назва іконки для дії (рядка призначення) або None."""
    if not val or val == "NONE":
        return None
    if val in _EXACT:
        return _EXACT[val]
    for prefix, name in _PREFIX:
        if val.startswith(prefix):
            return name
    if val.startswith("HOTKEY:"):
        combo = val.split(":", 1)[1].strip().lower()
        if combo in _HOTKEYS:
            return _HOTKEYS[combo]
        if combo.startswith("mouse_"):
            return "mouse"
        return "keyboard"
    return None


def action_icon(val, color=ICON_COLOR, active=None):
    name = action_icon_name(val)
    return icon(name, color, active) if name else QIcon()
