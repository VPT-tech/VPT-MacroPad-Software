# icons.py
# Набір іконок assets/icons/*.svg (лінійні, 24x24, stroke="currentColor").
# currentColor підміняється потрібним кольором під час рендеру, тож одна іконка
# може бути сірою, акцентною (бірюзовою) чи червоною залежно від стану.
#
# Іконки використовуються лише там, де вони несуть інформацію або заміняють текст:
# кнопки-інструменти (видалити, оновити, налаштування), меню, перемикач режиму
# натискання та OSD. У списках дій іконок навмисно немає — щоб не перевантажувати вікно.
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
