import os
import json
import time
import math
import keyboard
import mouse
import sys
import subprocess
import ctypes
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, 
                             QPushButton, QLabel, QScrollArea, QFrame, 
                             QComboBox, QLineEdit, QMenu, QDialog, QSizePolicy, QInputDialog,
                             QWidgetAction, QCheckBox)
from PySide6.QtCore import (Qt, Signal, QTimer, QVariantAnimation, QPropertyAnimation, 
                            QEasingCurve, QPoint, QPointF, QSize, QRect, QRectF)
from PySide6.QtGui import (QPainter, QPainterPath, QPolygonF, QColor, QPen, 
                           QCursor, QFont, QMouseEvent, QAction, QIcon)

from PySide6.QtCore import QPoint, QPointF, QRectF, QVariantAnimation, QEasingCurve, Signal, Qt
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QRadialGradient, QLinearGradient, QCursor, QMouseEvent

from config import ACCENT, TEXT_MAIN, TEXT_SUB, BTN_DANGER, BG_HOVER, BG_MAIN
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

class ProfileWidget(QFrame):
    clicked = Signal(int)

    def __init__(self, index, name, main_app, parent=None):
        super().__init__(parent)
        self.index = index
        self.name = name
        self.main_app = main_app
        self.is_active = False

        self.setObjectName("profileFrame")
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

        self.lbl_name = QLabel("", self)
        self.lbl_name.setObjectName("profileName")
        self.lbl_name.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_name.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self.lbl_num = QLabel(str(self.index + 1), self)
        self.lbl_num.setObjectName("profileNum")
        self.lbl_num.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_num.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self.anim = QVariantAnimation(self)
        self.anim.setDuration(200)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.valueChanged.connect(self.update_width_and_layout)

        self.setFixedHeight(40)
        self.setFixedWidth(40)

    def update_width_and_layout(self, val):
        self.setFixedWidth(val)
        if hasattr(self.main_app, 'update_dynamic_layout'):
            self.main_app.update_dynamic_layout()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, 'lbl_num') or not hasattr(self, 'lbl_name'):
            return

        w = self.width()
        self.lbl_num.setGeometry(w - 40, 0, 40, 40)

        default_prefix = f"Профіль {self.index + 1}"
        name_clean = "Профіль" if self.name.strip() == default_prefix else self.name.strip()
        if not name_clean:
            name_clean = "Профіль"
        self.lbl_name.setText(name_clean)

        if w <= 45:
            self.lbl_name.hide()
        else:
            self.lbl_name.show()
            self.lbl_name.setGeometry(0, 0, w - 25, 40)

    def set_active(self, state):
        self.is_active = state
        self.setProperty("active", str(state).lower())
        self.lbl_num.setProperty("active", str(state).lower())
        self.lbl_name.setProperty("active", str(state).lower())
        self.style().unpolish(self)
        self.style().polish(self)
        self.lbl_num.style().unpolish(self.lbl_num)
        self.lbl_num.style().polish(self.lbl_num)
        self.lbl_name.style().unpolish(self.lbl_name)
        self.lbl_name.style().polish(self.lbl_name)

    def enterEvent(self, e):
        self.anim.stop()
        self.anim.setStartValue(self.width())
        self.anim.setEndValue(110) 
        self.anim.start()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.anim.stop()
        self.anim.setStartValue(self.width())
        self.anim.setEndValue(40) 
        self.anim.start()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.index)
        elif e.button() == Qt.MouseButton.RightButton:
            self.show_menu(e.globalPosition().toPoint())
        super().mousePressEvent(e)

    def bind_app(self):
        profiles = self.main_app.config.get("PROFILES", [])
        current = profiles[self.index].get("app_bind", "")
        
        dialog = AppBindDialog(current, self)
        if dialog.exec():
            profiles[self.index]["app_bind"] = dialog.get_exe_name()
            self.main_app.save_config()

    def show_menu(self, pos):
        from config import BUILTIN_PRESETS
        menu = QMenu(self)
        a_bind = QAction(QIcon(os.path.join(ASSETS_DIR, "setting.svg")), "Прив'язати до .exe", self)
        a_ren = QAction(QIcon(os.path.join(ASSETS_DIR, "rename.svg")), "Перейменувати", self)
        a_exp = QAction("📤 Експорт профілю (.json)", self)
        a_imp = QAction("📥 Імпорт профілю (.json)", self)

        preset_menu = menu.addMenu("✨ Завантажити пресет...")
        preset_actions = {}
        for p_name in BUILTIN_PRESETS.keys():
            act_p = preset_menu.addAction(f"⚡ {p_name}")
            preset_actions[act_p] = p_name

        a_clear = QAction(QIcon(os.path.join(ASSETS_DIR, "clean.svg")), "Очистити призначення", self)
        a_del = QAction(QIcon(os.path.join(ASSETS_DIR, "trash.svg")), "Видалити профіль", self)
        a_del.setObjectName("danger")

        menu.addAction(a_bind)
        menu.addAction(a_ren)
        menu.addSeparator()
        menu.addAction(a_exp)
        menu.addAction(a_imp)
        menu.addSeparator()
        menu.addAction(a_clear)
        menu.addAction(a_del)

        prof_count = len(self.main_app.config.get("PROFILES", [{"name": "Профіль 1"}]))
        if prof_count <= 1:
            a_del.setEnabled(False)

        menu_size = menu.sizeHint()
        shifted_pos = QPoint(pos.x() - menu_size.width(), pos.y())
        action = menu.exec(shifted_pos)
        if action == a_ren:
            self.rename_profile()
        elif action == a_bind:
            self.bind_app()
        elif action == a_exp and hasattr(self.main_app, 'export_profile'):
            self.main_app.export_profile(self.index)
        elif action == a_imp and hasattr(self.main_app, 'import_profile'):
            self.main_app.import_profile()
        elif action in preset_actions and hasattr(self.main_app, 'apply_preset_to_profile'):
            self.main_app.apply_preset_to_profile(self.index, preset_actions[action])
        elif action == a_clear and hasattr(self.main_app, 'clear_profile'):
            self.main_app.clear_profile(self.index)
        elif action == a_del and hasattr(self.main_app, 'delete_profile'):
            self.main_app.delete_profile(self.index)

    def rename_profile(self):
        from PySide6.QtWidgets import QInputDialog
        text, ok = QInputDialog.getText(self, "Перейменувати", "Нова назва профілю:", text=self.name)
        if ok and text.strip():
            self.name = text.strip()
            self.lbl_name.setText(self.name)
            if hasattr(self.main_app, 'rename_profile'): self.main_app.rename_profile(self.index, self.name)

class ArrowWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(20, 20)
        self.angle = 0.0
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(250)
        self.anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.anim.valueChanged.connect(self.set_angle)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_angle(self, angle):
        self.angle = angle
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.translate(self.width() / 2, self.height() / 2)
        p.rotate(self.angle)
        
        pen = QPen(QColor("#ffffff"), 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        
        p.drawLine(-5, -2, 0, 3)
        p.drawLine(0, 3, 5, -2)

class AnimatedComboBox(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.arrow = ArrowWidget(self)
        self.setStyleSheet("QComboBox::down-arrow { image: none; }")
        
    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.arrow.move(self.width() - 25, (self.height() - 20) // 2)
        
    def showPopup(self):
        super().showPopup()
        self.arrow.anim.stop()
        self.arrow.anim.setStartValue(self.arrow.angle)
        self.arrow.anim.setEndValue(180.0)
        self.arrow.anim.start()
        
    def hidePopup(self):
        super().hidePopup()
        self.arrow.anim.stop()
        self.arrow.anim.setStartValue(self.arrow.angle)
        self.arrow.anim.setEndValue(0.0)
        self.arrow.anim.start()
        
    def wheelEvent(self, event):
        event.ignore()

class NoScrollComboBox(QComboBox):
    def wheelEvent(self, event):
        event.ignore() 
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setStyleSheet("""
            QComboBox::down-arrow { image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23ffffff' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'/%3E%3C/svg%3E"); width: 14px; height: 14px; }
        """)

class AnimatedToolTip(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        self.label = QLabel("")
        self.label.setStyleSheet("""
            background-color: rgba(60, 60, 60, 240); 
            color: #ffffff; 
            padding: 5px 12px; 
            border-radius: 6px; 
            font-size: 11px; 
            font-weight: bold; 
            font-family: Arial; 
            border: 1px solid #555;
        """)
        self.layout.addWidget(self.label)
        
        self.anim = QPropertyAnimation(self, b"windowOpacity")
        self.anim.setDuration(150)
        
    def show_text(self, text, pos, align="top"):
        self.anim.stop()
        try: self.anim.finished.disconnect(self.hide_after_anim)
        except TypeError: pass

        self.label.setText(text)
        self.adjustSize()
        
        if align == "top": self.move(pos.x() - self.width() // 2, pos.y() - self.height() - 5)
        elif align == "right": self.move(pos.x() + 8, pos.y() - self.height() // 2)
            
        self.setWindowOpacity(0.0)
        self.show()
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.start()
        
    def hide_tip(self):
        self.anim.stop()
        try: self.anim.finished.disconnect(self.hide_after_anim)
        except TypeError: pass
            
        self.anim.setStartValue(self.windowOpacity())
        self.anim.setEndValue(0.0)
        self.anim.finished.connect(self.hide_after_anim)
        self.anim.start()

    def hide_after_anim(self):
        try: self.anim.finished.disconnect(self.hide_after_anim)
        except TypeError: pass
        self.hide()

class OSDOverlay(QWidget):
    """Спливаючий напівпрозорий Mini-HUD (OSD) поверх вікон та ігор."""
    def __init__(self, main_app):
        super().__init__(None)
        self.main_app = main_app
        self.setWindowFlags(
            Qt.WindowType.ToolTip |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.WindowTransparentForInput
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedSize(310, 74)

        self.mode = "status"
        self.title = ""
        self.val = 0.0
        self.icon_text = "🔊"
        self.app_icon = None
        self.is_danger = False

        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.fade_out)

        self.anim = QPropertyAnimation(self, b"windowOpacity")
        self.anim.setDuration(180)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def show_osd(self, mode, title, val=0.0, icon_text="🔊", is_danger=False, app_icon=None):
        if not self.main_app.config.get("show_osd", True):
            return
        self.mode = mode
        self.title = title
        self.val = max(0.0, min(1.0, float(val))) if val is not None else 0.0
        self.icon_text = icon_text
        self.is_danger = is_danger
        self.app_icon = app_icon

        from PySide6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(geo.right() - self.width() - 28, geo.top() + 28)

        self.anim.stop()
        try:
            self.anim.finished.disconnect(self.hide)
        except Exception:
            pass

        self.update()
        if not self.isVisible():
            self.setWindowOpacity(0.0)
            self.show()
        self.anim.setStartValue(self.windowOpacity())
        self.anim.setEndValue(0.96)
        self.anim.start()
        self.hide_timer.start(1500)

    def fade_out(self):
        self.anim.stop()
        try:
            self.anim.finished.disconnect(self.hide)
        except Exception:
            pass
        self.anim.setStartValue(self.windowOpacity())
        self.anim.setEndValue(0.0)
        self.anim.finished.connect(self.hide)
        self.anim.start()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(2, 2, self.width() - 4, self.height() - 4)
        border_col = QColor(BTN_DANGER) if self.is_danger else QColor(ACCENT)

        bg_grad = QLinearGradient(rect.topLeft(), rect.bottomRight())
        bg_grad.setColorAt(0.0, QColor(18, 22, 28, 240))
        bg_grad.setColorAt(1.0, QColor(10, 12, 16, 248))
        p.setBrush(bg_grad)
        p.setPen(QPen(border_col, 1.6))
        p.drawRoundedRect(rect, 14, 14)

        # Іконка зліва
        icon_rect = QRectF(16, 17, 40, 40)
        p.setBrush(QColor(border_col.red(), border_col.green(), border_col.blue(), 35))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(icon_rect, 10, 10)

        if self.app_icon and not self.app_icon.isNull():
            pix = self.app_icon.pixmap(26, 26)
            p.drawPixmap(int(icon_rect.center().x() - 13), int(icon_rect.center().y() - 13), pix)
        else:
            p.setPen(QColor("#ffffff"))
            p.setFont(QFont("Segoe UI Emoji", 16))
            p.drawText(icon_rect, Qt.AlignmentFlag.AlignCenter, self.icon_text)

        if self.mode == "volume":
            # Заголовок + відсотки
            p.setFont(QFont("Arial", 10, QFont.Weight.Bold))
            p.setPen(QColor("#ffffff"))
            p.drawText(QRectF(68, 15, 175, 22), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.title)

            pct_str = f"{int(round(self.val * 100))}%"
            p.setPen(border_col)
            p.setFont(QFont("Arial", 11, QFont.Weight.Bold))
            p.drawText(QRectF(235, 15, 58, 22), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, pct_str)

            # Прогрес-бар
            bar_bg = QRectF(68, 44, 224, 8)
            p.setBrush(QColor("#262a30"))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(bar_bg, 4, 4)

            if self.val > 0:
                fill_w = max(8.0, bar_bg.width() * self.val)
                p.setBrush(border_col)
                p.drawRoundedRect(QRectF(68, 44, fill_w, 8), 4, 4)
        else:
            p.setFont(QFont("Arial", 11, QFont.Weight.Bold))
            p.setPen(border_col if self.is_danger else QColor("#ffffff"))
            p.drawText(QRectF(68, 12, 225, 50), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.title)
        p.end()

class ResetDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Підтвердження")
        self.setFixedSize(450, 180)
        layout = QVBoxLayout(self)
        lbl = QLabel("Ви впевнені, що хочете скинути всі \nпризначення кнопок поточного профілю?\n\nМакроси та збережені програми залишаться.")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setFont(QFont("Arial", 12))
        layout.addWidget(lbl)
        h_lay = QHBoxLayout()
        btn_yes = QPushButton("Так, скинути")
        btn_yes.setStyleSheet(f"background-color: {BTN_DANGER}; border: none; color: white;")
        btn_yes.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_yes.clicked.connect(self.accept)
        btn_no = QPushButton("Скасувати")
        btn_no.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_no.clicked.connect(self.reject)
        h_lay.addWidget(btn_yes)
        h_lay.addWidget(btn_no)
        layout.addLayout(h_lay)

class EncoderCompoundWidget(QWidget):
    leftClicked = Signal(str)
    rightClicked = Signal(str)

    def __init__(self, enc_base_id, main_app, parent=None):
        super().__init__(parent)
        self.enc_base_id = enc_base_id
        self.bid = enc_base_id
        self.main_app = main_app
        self.setFixedSize(90, 90)
        self.setMouseTracking(True)
        self.hover_part = None
        self.drag_hover_part = None
        self.drag_hover_valid = True
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        
        self.pulse_alpha = 0
        self.pulse_targets = {}
        self.pulse_anim = QVariantAnimation(self)
        self.pulse_anim.setDuration(1200)
        self.pulse_anim.setLoopCount(2) 
        self.pulse_anim.setKeyValueAt(0.0, 0)
        self.pulse_anim.setKeyValueAt(0.5, 200)
        self.pulse_anim.setKeyValueAt(1.0, 0)
        self.pulse_anim.valueChanged.connect(self._update_pulse)

        # Сплин поглинання
        self.drop_ripple_progress = 0.0
        self.drop_ripple_target = None
        self.drop_anim = QVariantAnimation(self)
        self.drop_anim.setDuration(350)
        self.drop_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.drop_anim.setKeyValueAt(0.0, 0.0)
        self.drop_anim.setKeyValueAt(1.0, 1.0)
        self.drop_anim.valueChanged.connect(self._update_drop_ripple)

    def _update_pulse(self, val):
        self.pulse_alpha = val
        self.update()

    def _update_drop_ripple(self, val):
        self.drop_ripple_progress = val
        self.update()

    def trigger_drop_effect(self, target_part):
        self.drop_ripple_target = target_part
        self.drop_anim.stop()
        self.drop_anim.start()
        
    def trigger_pulse(self, targets_dict):
        self.pulse_targets = targets_dict
        self.pulse_anim.stop()
        self.pulse_anim.start()

    def _get_hit_part(self, pos):
        cx, cy = self.width() / 2.0, self.height() / 2.0
        dx = pos.x() - cx; dy = pos.y() - cy
        dist = math.hypot(dx, dy)
        if dist <= 18.0: return "center"
        elif 21.0 <= dist <= 42.5:
            angle = math.degrees(math.atan2(-dy, dx)) % 360.0
            margin = math.degrees(math.asin(min(1.0, 1.4 / max(1.0, dist))))
            if (45.0 + margin) <= angle <= (135.0 - margin): return "sw"
            elif (135.0 + margin) <= angle <= (270.0 - margin): return "left"
            elif (angle >= 270.0 + margin) or (angle <= 45.0 - margin): return "right"
        return None

    def _get_bid_by_part(self, part):
        if part == "center": return self.enc_base_id
        elif part == "sw": return f"{self.enc_base_id}_SW"
        elif part == "left": return f"{self.enc_base_id}_L"
        elif part == "right": return f"{self.enc_base_id}_R"
        return None

    def _is_part_muted(self, bid):
        if not hasattr(self.main_app, 'mute_states'):
            return False
        if bid.endswith("_SW") and hasattr(self.main_app, 'get_button_triggers'):
            acts = list(self.main_app.get_button_triggers(bid).values())
        elif bid == self.enc_base_id and hasattr(self.main_app, 'get_enc_active_action'):
            acts = [self.main_app.get_enc_active_action(bid)]
        else:
            acts = [self.main_app.get_action(bid) if hasattr(self.main_app, 'get_action') else "NONE"]

        for act in acts:
            if act in ("MED:MUTE", "ENC:VOL"):
                return self.main_app.mute_states.get("sys", False)
            elif act == "MED:MIC_MUTE":
                return self.main_app.mute_states.get("mic", False)
            elif act.startswith("APP_MUTE:") or act.startswith("ENC:APP:"):
                app = act.split(":")[-1].lower()
                return self.main_app.mute_states.get("apps", {}).get(app, False)
        return False

    def _get_part_volume(self, bid):
        if not hasattr(self.main_app, 'volume_states'):
            return None
        act = self.main_app.get_enc_active_action(bid) if hasattr(self.main_app, 'get_enc_active_action') else self.main_app.get_action(bid)
        if act == "ENC:VOL":
            return self.main_app.volume_states.get("sys", 0.0)
        elif act == "ENC:BRIGHTNESS":
            return self.main_app.volume_states.get("brightness", 0.7)
        elif act.startswith("ENC:APP:"):
            app = act.split(":")[-1].lower()
            return self.main_app.volume_states.get("apps", {}).get(app, 0.0)
        return None

    def mouseMoveEvent(self, event):
        old_hover = self.hover_part
        self.hover_part = self._get_hit_part(event.position())
        if old_hover != self.hover_part:
            self.update()
            if self.hover_part:
                bid = self._get_bid_by_part(self.hover_part)
                if self.hover_part == "center" and hasattr(self.main_app, 'get_enc_tooltip'):
                    tip = self.main_app.get_enc_tooltip(bid)
                elif self.hover_part == "sw" and hasattr(self.main_app, 'get_btn_tooltip'):
                    tip = self.main_app.get_btn_tooltip(bid)
                else:
                    val = self.main_app.get_action(bid)
                    tip = self.main_app.get_fname(val) if val != "NONE" else ""
                if tip:
                    pos = self.mapToGlobal(QPoint(self.width(), int(event.position().y())))
                    self.main_app.tooltip.show_text(tip, pos, "right")
                else:
                    self.main_app.tooltip.hide_tip()
            else:
                self.main_app.tooltip.hide_tip()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self.hover_part = None
        self.update()
        if hasattr(self.main_app, 'tooltip'):
            self.main_app.tooltip.hide_tip()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        part = self._get_hit_part(event.position())
        if part:
            bid = self._get_bid_by_part(part)
            if event.button() == Qt.MouseButton.LeftButton:
                self.leftClicked.emit(bid)
            elif event.button() == Qt.MouseButton.RightButton:
                menu = QMenu(self)
                add_mode_act = None
                clear_modes_act = None
                if part == "center" and self.main_app.staged_val and self.main_app.staged_val.startswith("ENC:"):
                    add_mode_act = menu.addAction(f"➕ Додати «{self.main_app.staged_name}» у Smart Dial")
                if part == "center":
                    clear_modes_act = menu.addAction("🔄 Очистити додаткові режими крутилки")
                    menu.addSeparator()
                del_act = QAction("🗑 Видалити призначення", self)
                del_act.setObjectName("danger")
                menu.addAction(del_act)
                action = menu.exec(event.globalPosition().toPoint())
                if add_mode_act and action == add_mode_act:
                    self.main_app.add_enc_smart_mode(self.enc_base_id, self.main_app.staged_val)
                elif clear_modes_act and action == clear_modes_act:
                    self.main_app.clear_enc_smart_modes(self.enc_base_id)
                elif action == del_act:
                    self.rightClicked.emit(bid)
        super().mousePressEvent(event)

    def _draw_curved_arrow(self, painter, is_left, color):
        cx, cy = 45.0, 45.0; r = 31.75
        painter.setPen(QPen(color, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        rect = QRectF(cx - r, cy - r, r * 2, r * 2)
        path = QPainterPath()

        if is_left:
            path.arcMoveTo(rect, 150); path.arcTo(rect, 150, 58); painter.drawPath(path)
            rad = math.radians(208.0)
            tip_x = cx + r * math.cos(rad); tip_y = cy - r * math.sin(rad)
            tangent_x = -math.sin(rad); tangent_y = -math.cos(rad)
            t_len = math.hypot(tangent_x, tangent_y)
            tx, ty = tangent_x / t_len, tangent_y / t_len
            nx, ny = -ty, tx
            base_x = tip_x - 5.2 * tx; base_y = tip_y - 5.2 * ty
            painter.setBrush(color); painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPolygon(QPolygonF([QPointF(tip_x, tip_y), QPointF(base_x + 3.2 * nx, base_y + 3.2 * ny), QPointF(base_x - 3.2 * nx, base_y - 3.2 * ny)]))
        else:
            path.arcMoveTo(rect, 30); path.arcTo(rect, 30, -58); painter.drawPath(path)
            rad = math.radians(-28.0)
            tip_x = cx + r * math.cos(rad); tip_y = cy - r * math.sin(rad)
            tangent_x = math.sin(rad); tangent_y = math.cos(rad)
            t_len = math.hypot(tangent_x, tangent_y)
            tx, ty = tangent_x / t_len, tangent_y / t_len
            nx, ny = -ty, tx
            base_x = tip_x - 5.2 * tx; base_y = tip_y - 5.2 * ty
            painter.setBrush(color); painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPolygon(QPolygonF([QPointF(tip_x, tip_y), QPointF(base_x + 3.2 * nx, base_y + 3.2 * ny), QPointF(base_x - 3.2 * nx, base_y - 3.2 * ny)]))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx, cy = 45.0, 45.0
        r_out = 42.0; r_in = 21.5; r_cnt = 17.5
        gap_half = 1.4
        a_out = math.degrees(math.asin(gap_half / r_out))
        a_in = math.degrees(math.asin(gap_half / r_in))

        sel = getattr(self.main_app, 'selected_btn', None)
        is_cnt_active = (sel == self.enc_base_id)
        is_sw_active = (sel == f"{self.enc_base_id}_SW")
        is_l_active = (sel == f"{self.enc_base_id}_L")
        is_r_active = (sel == f"{self.enc_base_id}_R")

        c_accent = QColor(ACCENT)
        c_bg = QColor(10, 10, 10)
        c_bg_hover = QColor(BG_HOVER)
        c_border = QColor(45, 45, 45)
        c_muted = QColor(BTN_DANGER)

        rect_out = QRectF(cx - r_out, cy - r_out, r_out * 2, r_out * 2)
        rect_in = QRectF(cx - r_in, cy - r_in, r_in * 2, r_in * 2)

        # 1. SW
        path_sw = QPainterPath()
        path_sw.arcMoveTo(rect_out, 45.0 + a_out)
        path_sw.arcTo(rect_out, 45.0 + a_out, 90.0 - 2 * a_out)
        path_sw.arcTo(rect_in, 135.0 - a_in, -(90.0 - 2 * a_in))
        path_sw.closeSubpath()

        is_sw_muted = self._is_part_muted(f"{self.enc_base_id}_SW")
        is_sw_drag = (self.drag_hover_part == "sw")
        drag_sw_col = c_accent if self.drag_hover_valid else c_muted
        sw_color = c_muted if is_sw_muted else (drag_sw_col if is_sw_drag else (c_accent if (is_sw_active or self.hover_part == "sw") else c_border))
        p.setBrush(QColor(drag_sw_col.red(), drag_sw_col.green(), drag_sw_col.blue(), 50) if is_sw_drag else (c_bg_hover if self.hover_part == "sw" else c_bg))
        p.setPen(QPen(sw_color, 2.0 if (is_sw_active or is_sw_muted or is_sw_drag) else 1.0))
        p.drawPath(path_sw)

        p.setPen(QPen(sw_color if (is_sw_active or is_sw_muted or is_sw_drag or self.hover_part == "sw") else QColor("#666666"), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        sw_y = cy - 30.5
        p.drawLine(QPointF(cx - 4, sw_y - 2), QPointF(cx, sw_y + 2))
        p.drawLine(QPointF(cx, sw_y + 2), QPointF(cx + 4, sw_y - 2))

        # 2. Left
        path_l = QPainterPath()
        path_l.arcMoveTo(rect_out, 135.0 + a_out)
        path_l.arcTo(rect_out, 135.0 + a_out, 135.0 - 2 * a_out)
        path_l.arcTo(rect_in, 270.0 - a_in, -(135.0 - 2 * a_in))
        path_l.closeSubpath()

        is_l_muted = self._is_part_muted(f"{self.enc_base_id}_L")
        is_l_drag = (self.drag_hover_part == "left")
        drag_l_col = c_accent if self.drag_hover_valid else c_muted
        l_color = c_muted if is_l_muted else (drag_l_col if is_l_drag else (c_accent if (is_l_active or self.hover_part == "left") else c_border))
        p.setBrush(QColor(drag_l_col.red(), drag_l_col.green(), drag_l_col.blue(), 50) if is_l_drag else (c_bg_hover if self.hover_part == "left" else c_bg))
        p.setPen(QPen(l_color, 2.0 if (is_l_active or is_l_muted or is_l_drag) else 1.0))
        p.drawPath(path_l)

        # 3. Right
        path_r = QPainterPath()
        path_r.arcMoveTo(rect_out, -90.0 + a_out)
        path_r.arcTo(rect_out, -90.0 + a_out, 135.0 - 2 * a_out)
        path_r.arcTo(rect_in, 45.0 - a_in, -(135.0 - 2 * a_in))
        path_r.closeSubpath()

        is_r_muted = self._is_part_muted(f"{self.enc_base_id}_R")
        is_r_drag = (self.drag_hover_part == "right")
        drag_r_col = c_accent if self.drag_hover_valid else c_muted
        r_color = c_muted if is_r_muted else (drag_r_col if is_r_drag else (c_accent if (is_r_active or self.hover_part == "right") else c_border))
        p.setBrush(QColor(drag_r_col.red(), drag_r_col.green(), drag_r_col.blue(), 50) if is_r_drag else (c_bg_hover if self.hover_part == "right" else c_bg))
        p.setPen(QPen(r_color, 2.0 if (is_r_active or is_r_muted or is_r_drag) else 1.0))
        p.drawPath(path_r)

        # 4. Arrows
        arrow_col_l = l_color if (is_l_active or is_l_muted or is_l_drag or self.hover_part == "left") else QColor("#666666")
        self._draw_curved_arrow(p, True, arrow_col_l)

        arrow_col_r = r_color if (is_r_active or is_r_muted or is_r_drag or self.hover_part == "right") else QColor("#666666")
        self._draw_curved_arrow(p, False, arrow_col_r)

        # 5. Center
        is_cnt_drag = (self.drag_hover_part == "center")
        drag_cnt_col = c_accent if self.drag_hover_valid else c_muted
        cnt_color = drag_cnt_col if is_cnt_drag else (c_accent if (is_cnt_active or self.hover_part == "center") else c_border)
        p.setBrush(QColor(drag_cnt_col.red(), drag_cnt_col.green(), drag_cnt_col.blue(), 50) if is_cnt_drag else (c_bg_hover if self.hover_part == "center" else c_bg))
        p.setPen(QPen(cnt_color, 2.0 if (is_cnt_active or is_cnt_drag) else 1.0))
        p.drawEllipse(QPointF(cx, cy), r_cnt, r_cnt)

        # Progress bar
        vol = self._get_part_volume(self.enc_base_id)
        if vol is not None:
            arc_r = 19.5 
            arc_rect = QRectF(cx - arc_r, cy - arc_r, arc_r * 2, arc_r * 2)
            p.setPen(QPen(QColor("#222222"), 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(arc_rect, 225 * 16, -270 * 16)
            if vol > 0:
                is_vol_muted = self._is_part_muted(self.enc_base_id)
                bar_color = c_muted if is_vol_muted else c_accent
                p.setPen(QPen(bar_color, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawArc(arc_rect, 225 * 16, int(-270 * 16 * vol))

        # Action dots
        def has_act(bid):
            if not hasattr(self.main_app, 'get_action'):
                return False
            if bid.endswith("_SW") and hasattr(self.main_app, 'get_button_triggers'):
                return any(v != "NONE" for v in self.main_app.get_button_triggers(bid).values())
            if bid == self.enc_base_id and hasattr(self.main_app, 'get_enc_active_action'):
                return self.main_app.get_enc_active_action(bid) != "NONE"
            return self.main_app.get_action(bid) != "NONE"

        p.setBrush(QColor("#ffffff"))
        p.setPen(Qt.PenStyle.NoPen)
        if has_act(f"{self.enc_base_id}_SW"): p.drawEllipse(QPointF(cx, cy - 36.5), 2.2, 2.2)
        if has_act(f"{self.enc_base_id}_L"): p.drawEllipse(QPointF(cx - 13.5, cy + 27.5), 2.5, 2.5)
        if has_act(f"{self.enc_base_id}_R"): p.drawEllipse(QPointF(cx + 13.5, cy + 27.5), 2.5, 2.5)
        if has_act(self.enc_base_id): p.drawEllipse(QPointF(cx, cy), 3.0, 3.0)

        # Drop Ripple
        if self.drop_ripple_progress > 0 and self.drop_anim.state() == QVariantAnimation.State.Running:
            alpha = int((1.0 - self.drop_ripple_progress) * 255)
            p.setPen(QPen(QColor(0, 229, 255, alpha), 2.0))
            p.setBrush(QColor(0, 229, 255, int(alpha * 0.4)))
            if self.drop_ripple_target == "center":
                p.drawEllipse(QPointF(cx, cy), r_cnt * self.drop_ripple_progress, r_cnt * self.drop_ripple_progress)
            elif self.drop_ripple_target == "sw":
                p.drawPath(path_sw)
            elif self.drop_ripple_target == "left":
                p.drawPath(path_l)
            elif self.drop_ripple_target == "right":
                p.drawPath(path_r)

        # Pulse Error
        if self.pulse_alpha > 0 and self.pulse_targets:
            p.setPen(Qt.PenStyle.NoPen)
            for target, color_hex in self.pulse_targets.items():
                c = QColor(color_hex); c.setAlpha(self.pulse_alpha)
                p.setBrush(c)
                if target == "center":
                    p.drawEllipse(QPointF(cx, cy), r_cnt, r_cnt)
                elif target == "outer":
                    path = QPainterPath()
                    path.addEllipse(QPointF(cx, cy), r_out, r_out)
                    inner = QPainterPath()
                    inner.addEllipse(QPointF(cx, cy), r_in, r_in)
                    p.drawPath(path.subtracted(inner))

class FloatingDragOverlay(QWidget):
    """
    Повноекранний шар для плавного 60 FPS морфінгу без ривків і стрибків.
    """
    def __init__(self, main_app):
        super().__init__(main_app.centralWidget())
        self.main_app = main_app
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.hide()

        self.current_btn = None
        self.action_val = ""
        self.action_text = ""
        
        self.cur_pos = QPointF(0, 0)
        self.start_rect = QRectF(0, 0, 100, 40)
        self.initial_mouse_offset = QPointF(0, 0)
        self.morph_progress = 0.0
        self.is_active = False

        # Плавне перетворення без стрибків (OutCubic)
        self.morph_anim = QVariantAnimation(self)
        self.morph_anim.setDuration(190)
        self.morph_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.morph_anim.valueChanged.connect(self._on_morph_step)

        # Анімація поглинання / скасування
        self.absorb_progress = 0.0
        self.target_absorb_pos = QPointF(0, 0)
        self.absorb_anim = QVariantAnimation(self)
        self.absorb_anim.setDuration(150)
        self.absorb_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.absorb_anim.valueChanged.connect(self._on_absorb_step)
        self.absorb_anim.finished.connect(self.hide)

    def start_drag(self, btn, val, text, global_mouse_pos):
        self.current_btn = btn
        self.action_val = val
        self.action_text = text
        self.is_active = True
        self.absorb_progress = 0.0

        parent = self.main_app.centralWidget()
        self.resize(parent.size())
        self.raise_()
        self.show()

        btn_pos = btn.mapTo(parent, QPoint(0, 0))
        self.start_rect = QRectF(btn_pos.x(), btn_pos.y(), btn.width(), btn.height())
        self.cur_pos = QPointF(parent.mapFromGlobal(global_mouse_pos))

        # Фіксуємо точний зсув точки хвату, щоб усунути стартовий ривок
        start_center = self.start_rect.center()
        self.initial_mouse_offset = start_center - self.cur_pos

        self.morph_anim.stop()
        self.morph_anim.setStartValue(0.0)
        self.morph_anim.setEndValue(1.0)
        self.morph_anim.start()
        self.update()

    def update_position(self, global_mouse_pos):
        if not self.is_active: return
        parent = self.main_app.centralWidget()
        self.cur_pos = QPointF(parent.mapFromGlobal(global_mouse_pos))
        self.update()

    def end_drag_absorb(self, target_center_global):
        """Анімація плавного втягування в кнопку."""
        self.is_active = False
        parent = self.main_app.centralWidget()
        self.target_absorb_pos = QPointF(parent.mapFromGlobal(target_center_global))
        
        self.absorb_anim.stop()
        self.absorb_anim.setStartValue(0.0)
        self.absorb_anim.setEndValue(1.0)
        self.absorb_anim.start()

    def end_drag_cancel(self):
        """Плавне повернення на початкове місце."""
        self.is_active = False
        self.target_absorb_pos = QPointF(self.start_rect.center())
        self.absorb_anim.stop()
        self.absorb_anim.setStartValue(0.0)
        self.absorb_anim.setEndValue(1.0)
        self.absorb_anim.start()

    def _on_morph_step(self, val):
        self.morph_progress = val
        self.update()

    def _on_absorb_step(self, val):
        self.absorb_progress = val
        self.update()

    def paintEvent(self, event):
        if not self.isVisible(): return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        t = self.morph_progress
        target_w = 160.0
        target_h = 36.0
        
        cur_w = self.start_rect.width() + (target_w - self.start_rect.width()) * t
        cur_h = self.start_rect.height() + (target_h - self.start_rect.height()) * t
        radius = 5.0 + (target_h / 2.0 - 5.0) * t

        # Безперервна інтерполяція центру без стрибка
        current_offset = self.initial_mouse_offset * (1.0 - t)
        cx = self.cur_pos.x() + current_offset.x()
        cy = self.cur_pos.y() + current_offset.y()

        if self.absorb_progress > 0.0:
            ap = self.absorb_progress
            cx = cx + (self.target_absorb_pos.x() - cx) * ap
            cy = cy + (self.target_absorb_pos.y() - cy) * ap
            cur_w *= (1.0 - ap * 0.7)
            cur_h *= (1.0 - ap * 0.7)
            p.setOpacity(max(0.0, 1.0 - ap))

        card_rect = QRectF(cx - cur_w / 2.0, cy - cur_h / 2.0, cur_w, cur_h)

        # 1. Зовнішнє неонове світіння
        glow_alpha = int(60 * t)
        if glow_alpha > 0:
            glow_grad = QRadialGradient(card_rect.center(), cur_w * 0.65)
            glow_grad.setColorAt(0.0, QColor(0, 229, 255, glow_alpha))
            glow_grad.setColorAt(0.7, QColor(0, 229, 255, int(glow_alpha * 0.2)))
            glow_grad.setColorAt(1.0, QColor(0, 229, 255, 0))
            p.setBrush(glow_grad)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(card_rect.adjusted(-6, -6, 6, 6), radius + 4, radius + 4)

        # 2. Тінь під капсулою
        if t > 0.1:
            p.setBrush(QColor(0, 0, 0, int(80 * t)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(card_rect.adjusted(0, 4 * t, 0, 4 * t), radius, radius)

        # 3. Тіло капсули
        bg_grad = QLinearGradient(card_rect.topLeft(), card_rect.bottomRight())
        bg_grad.setColorAt(0.0, QColor(16, 26, 36, 250))
        bg_grad.setColorAt(1.0, QColor(8, 12, 18, 255))
        p.setBrush(bg_grad)
        
        border_pen = QPen(QColor(ACCENT), 1.5)
        p.setPen(border_pen)
        p.drawRoundedRect(card_rect, radius, radius)

        # 4. Неонова енерго-крапка
        dot_x = card_rect.left() + 14
        dot_y = card_rect.center().y()
        p.setBrush(QColor(ACCENT))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(dot_x, dot_y), 3.5, 3.5)

        # 5. Текст дії
        p.setFont(QFont("Arial", 9, QFont.Weight.Bold))
        p.setPen(QColor(255, 255, 255))
        text_rect = QRectF(dot_x + 8, card_rect.top(), card_rect.width() - 28, card_rect.height())
        fm = p.fontMetrics()
        elided = fm.elidedText(self.action_text, Qt.TextElideMode.ElideRight, int(text_rect.width()))
        p.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided)
        p.end()

class DraggableActionButton(QPushButton):
    def __init__(self, text, val, main_app, parent=None):
        super().__init__(text, parent)
        self.val = val
        self.main_app = main_app
        self.drag_start_pos = None
        self.is_dragging = False
        self.setObjectName("actionBtn")
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        
        self.ghost_alpha = 255
        self.ghost_anim = QVariantAnimation(self)
        self.ghost_anim.setDuration(160)
        self.ghost_anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        self.ghost_anim.valueChanged.connect(self._update_ghost)

    def _update_ghost(self, val):
        self.ghost_alpha = val
        self.update()

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_start_pos = event.position().toPoint()
            self.is_dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if (event.buttons() & Qt.MouseButton.LeftButton) and self.drag_start_pos:
            dist = (event.position().toPoint() - self.drag_start_pos).manhattanLength()
            from PySide6.QtWidgets import QApplication
            if not self.is_dragging and dist >= QApplication.startDragDistance():
                self.is_dragging = True
                
                self.ghost_anim.stop()
                self.ghost_anim.setStartValue(255)
                self.ghost_anim.setEndValue(60)
                self.ghost_anim.start()

                if hasattr(self.main_app, 'drag_overlay'):
                    self.main_app.drag_overlay.start_drag(self, self.val, self.text(), event.globalPosition().toPoint())

            if self.is_dragging and hasattr(self.main_app, 'drag_overlay'):
                g_pos = event.globalPosition().toPoint()
                self.main_app.drag_overlay.update_position(g_pos)
                self._check_pad_hover(g_pos)
                return

        super().mouseMoveEvent(event)

    def _check_pad_hover(self, global_pos):
        """Підсвічує фізичні кнопки та перевіряє конфлікти в реальному часі."""
        for btn in self.main_app.ui_pad_btns.values():
            local_p = btn.mapFromGlobal(global_pos)
            is_inside = btn.rect().contains(local_p)
            
            if isinstance(btn, EncoderCompoundWidget):
                part = btn._get_hit_part(local_p) if is_inside else None
                if btn.drag_hover_part != part:
                    btn.drag_hover_part = part
                    if part:
                        # Перевіряємо чи дозволено скидання на цей сектор
                        is_valid, _, _ = self._validate_encoder_drop(btn.enc_base_id, part)
                        btn.drag_hover_valid = is_valid
                    else:
                        btn.drag_hover_valid = True
                    btn.update()
            else:
                if btn.is_drag_over != is_inside:
                    btn.is_drag_over = is_inside
                    btn.is_drag_valid = not (self.val.startswith("ENC:") and self.val != "ENC:MODE_TOGGLE")
                    btn.update()

    def _validate_encoder_drop(self, base_enc_id, part):
        """Безконфліктна перевірка для енкодера (Центр і Боки не блокують одне одного)."""
        is_enc_action = self.val.startswith("ENC:") and self.val != "ENC:MODE_TOGGLE"

        if part == "center":
            if not is_enc_action:
                return False, {"center": BTN_DANGER, "outer": ACCENT}, "Центр — для дій обертання (гучність, скрол, масштаб, таймлайн)"
            return True, None, None

        elif part in ["left", "right"]:
            return True, None, None

        elif part == "sw":
            if is_enc_action:
                return False, {"outer": BTN_DANGER, "center": ACCENT}, "Кнопка SW тільки для натискань або Smart Dial Toggle"
            return True, None, None

        return False, None, None

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self.is_dragging:
            self.is_dragging = False
            g_pos = event.globalPosition().toPoint()
            
            self.ghost_anim.stop()
            self.ghost_anim.setStartValue(self.ghost_alpha)
            self.ghost_anim.setEndValue(255)
            self.ghost_anim.start()

            target_hit = False
            for bid, btn in self.main_app.ui_pad_btns.items():
                local_p = btn.mapFromGlobal(g_pos)
                if btn.rect().contains(local_p):
                    target_hit = True
                    target_center = btn.mapToGlobal(QPoint(btn.width() // 2, btn.height() // 2))
                    
                    if isinstance(btn, EncoderCompoundWidget):
                        part = btn._get_hit_part(local_p)
                        btn.drag_hover_part = None
                        btn.update()
                        
                        if part:
                            is_valid, pulse_targets, err_msg = self._validate_encoder_drop(btn.enc_base_id, part)
                            if not is_valid:
                                if hasattr(self.main_app, 'drag_overlay'):
                                    self.main_app.drag_overlay.end_drag_cancel()
                                if pulse_targets:
                                    btn.trigger_pulse(pulse_targets)
                                if err_msg and hasattr(self.main_app, 'tooltip'):
                                    pos = btn.mapToGlobal(QPoint(btn.width() // 2, 0))
                                    self.main_app.tooltip.show_text(f"❌ {err_msg}", pos, "top")
                                    QTimer.singleShot(1800, self.main_app.tooltip.hide_tip)
                            else:
                                if hasattr(self.main_app, 'drag_overlay'):
                                    self.main_app.drag_overlay.end_drag_absorb(target_center)
                                target_bid = btn._get_bid_by_part(part)
                                self.main_app.set_action(target_bid, self.val)
                                btn.trigger_drop_effect(part)
                        else:
                            if hasattr(self.main_app, 'drag_overlay'):
                                self.main_app.drag_overlay.end_drag_cancel()
                                
                    else:
                        btn.is_drag_over = False
                        btn.update()

                        if self.val.startswith("ENC:") and self.val != "ENC:MODE_TOGGLE":
                            if hasattr(self.main_app, 'drag_overlay'):
                                self.main_app.drag_overlay.end_drag_cancel()
                            btn.trigger_pulse(BTN_DANGER)
                            if hasattr(self.main_app, 'tooltip'):
                                pos = btn.mapToGlobal(QPoint(btn.width() // 2, 0))
                                self.main_app.tooltip.show_text("❌ Тільки для енкодерів (Центр)", pos, "top")
                                QTimer.singleShot(1800, self.main_app.tooltip.hide_tip)
                        else:
                            if hasattr(self.main_app, 'drag_overlay'):
                                self.main_app.drag_overlay.end_drag_absorb(target_center)
                            self.main_app.set_action(bid, self.val)
                            btn.trigger_drop_effect()
                    break

            if not target_hit:
                for b in self.main_app.ui_pad_btns.values():
                    if isinstance(b, EncoderCompoundWidget):
                        b.drag_hover_part = None
                        b.update()
                    else:
                        b.is_drag_over = False
                        b.update()
                if hasattr(self.main_app, 'drag_overlay'):
                    self.main_app.drag_overlay.end_drag_cancel()
            return

        super().mouseReleaseEvent(event)

    def paintEvent(self, event):
        if self.ghost_alpha >= 255:
            super().paintEvent(event)
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(1, 1, self.width() - 2, self.height() - 2)

        p.setBrush(QColor(10, 15, 20, int(self.ghost_alpha * 0.4)))
        p.setPen(QPen(QColor(0, 229, 255, int(self.ghost_alpha * 0.7)), 1.2, Qt.PenStyle.DashLine))
        p.drawRoundedRect(rect, 6, 6)

        p.setFont(self.font())
        p.setPen(QColor(120, 140, 150, int(self.ghost_alpha * 0.5)))
        p.drawText(QRectF(15, 0, self.width() - 30, self.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())
        p.end()


class PadButton(QPushButton):
    leftClicked = Signal(str)
    rightClicked = Signal(str)
    
    def __init__(self, text, bid, main_app, *args, **kwargs):
        super().__init__(text, *args, **kwargs)
        self.bid = bid
        self.main_app = main_app
        self.has_action = False
        self.is_drag_over = False
        self.is_drag_valid = True
        
        # Пульсація помилки
        self.pulse_alpha = 0
        self.pulse_color = QColor(BTN_DANGER)
        self.pulse_anim = QVariantAnimation(self)
        self.pulse_anim.setDuration(1200)
        self.pulse_anim.setLoopCount(2)
        self.pulse_anim.setKeyValueAt(0.0, 0)
        self.pulse_anim.setKeyValueAt(0.5, 200)
        self.pulse_anim.setKeyValueAt(1.0, 0)
        self.pulse_anim.valueChanged.connect(self._update_pulse)

        # Сплеск успішного поглинання
        self.drop_ripple_radius = 0.0
        self.drop_ripple_alpha = 0
        self.drop_anim = QVariantAnimation(self)
        self.drop_anim.setDuration(350)
        self.drop_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.drop_anim.setKeyValueAt(0.0, 0.0)
        self.drop_anim.setKeyValueAt(1.0, 1.0)
        self.drop_anim.valueChanged.connect(self._update_drop_ripple)

    def _update_pulse(self, val):
        self.pulse_alpha = val
        self.update()

    def _update_drop_ripple(self, progress):
        max_r = math.hypot(self.width() / 2, self.height() / 2)
        self.drop_ripple_radius = progress * max_r
        self.drop_ripple_alpha = int((1.0 - progress) * 255)
        self.update()

    def trigger_drop_effect(self):
        self.drop_anim.stop()
        self.drop_anim.start()

    def trigger_pulse(self, color_hex):
        self.pulse_color = QColor(color_hex)
        self.pulse_anim.stop()
        self.pulse_anim.start()
        
    def set_has_action(self, state):
        self.has_action = state
        self.update()
        
    def enterEvent(self, event):
        super().enterEvent(event)
        if self.has_action and hasattr(self.main_app, 'get_btn_tooltip'):
            tip = self.main_app.get_btn_tooltip(self.bid)
            if tip:
                pos = self.mapToGlobal(QPoint(self.width() // 2, 0))
                self.main_app.tooltip.show_text(tip, pos, "top")

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.main_app.tooltip.hide_tip()
        
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.leftClicked.emit(self.bid)
        elif event.button() == Qt.MouseButton.RightButton:
            menu = QMenu(self)
            del_act = QAction("🗑 Видалити призначення", self)
            del_act.setObjectName("danger")
            menu.addAction(del_act)
            action = menu.exec(event.globalPosition().toPoint())
            if action == del_act:
                self.rightClicked.emit(self.bid)
        super().mousePressEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        triggers = self.main_app.get_button_triggers(self.bid) if hasattr(self.main_app, 'get_button_triggers') else {
            "tap": self.main_app.get_action(self.bid), "dtap": "NONE", "hold": "NONE"
        }
        action = triggers.get("tap", "NONE")
        dtap_act = triggers.get("dtap", "NONE")
        hold_act = triggers.get("hold", "NONE")

        is_muted = False
        icon_type = None

        if hasattr(self.main_app, 'mute_states'):
            for a in (action, dtap_act, hold_act):
                if a == "MED:MUTE":
                    icon_type = "audio"
                    is_muted = self.main_app.mute_states.get("sys", False)
                    break
                elif a.startswith("APP_MUTE:"):
                    icon_type = "audio"
                    app_name = a.split(":")[-1].lower()
                    is_muted = self.main_app.mute_states.get("apps", {}).get(app_name, False)
                    break
                elif a == "MED:MIC_MUTE":
                    icon_type = "mic"
                    is_muted = self.main_app.mute_states.get("mic", False)
                    break

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self.is_drag_over:
            c = QColor(ACCENT) if self.is_drag_valid else QColor(BTN_DANGER)
            p.setBrush(QColor(c.red(), c.green(), c.blue(), 45))
            p.setPen(QPen(c, 2.0))
            p.drawRoundedRect(1, 1, self.width() - 2, self.height() - 2, 15, 15)

        if self.drop_ripple_alpha > 0:
            p.setPen(QPen(QColor(0, 229, 255, self.drop_ripple_alpha), 2.5))
            p.setBrush(QColor(0, 229, 255, int(self.drop_ripple_alpha * 0.35)))
            p.drawEllipse(QPointF(self.width() / 2, self.height() / 2), self.drop_ripple_radius, self.drop_ripple_radius)

        if self.has_action:
            p.setPen(Qt.PenStyle.NoPen)
            d = 6
            margin = 12
            dots = []
            if action != "NONE":
                col = QColor(ACCENT) if action.startswith("SYS:PROFILE_") else QColor(255, 255, 255)
                dots.append(col)
            if dtap_act != "NONE":
                dots.append(QColor("#ffaa00"))  # Бурштиновий для 2x Кліку
            if hold_act != "NONE":
                dots.append(QColor("#b366ff"))  # Неоново-фіолетовий для Утримання

            for i, col in enumerate(reversed(dots)):
                p.setBrush(col)
                p.drawEllipse(self.width() - margin - d - (i * 10), self.height() - margin - d, d, d)

            if is_muted and icon_type:
                p.setPen(QPen(QColor("#ff3366"), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                p.setBrush(Qt.BrushStyle.NoBrush)
                ix = self.width() - 24
                iy = 8
                if icon_type == "audio":
                    p.drawLine(ix + 2, iy + 6, ix + 5, iy + 6)
                    p.drawLine(ix + 5, iy + 6, ix + 9, iy + 2)
                    p.drawLine(ix + 9, iy + 2, ix + 9, iy + 14)
                    p.drawLine(ix + 9, iy + 14, ix + 5, iy + 10)
                    p.drawLine(ix + 5, iy + 10, ix + 2, iy + 10)
                    p.drawLine(ix + 2, iy + 10, ix + 2, iy + 6)
                    p.drawLine(ix + 12, iy + 5, ix + 16, iy + 9)
                    p.drawLine(ix + 16, iy + 5, ix + 12, iy + 9)
                elif icon_type == "mic":
                    p.drawRoundedRect(ix + 6, iy + 2, 4, 7, 2, 2)
                    p.drawArc(ix + 3, iy + 4, 10, 8, 0, -180 * 16)
                    p.drawLine(ix + 8, iy + 12, ix + 8, iy + 15)
                    p.drawLine(ix + 5, iy + 15, ix + 11, iy + 15)
                    p.drawLine(ix + 2, iy + 2, ix + 14, iy + 14)
                p.drawRoundedRect(1, 1, self.width() - 2, self.height() - 2, 14, 14)

        if self.pulse_alpha > 0:
            p.setPen(Qt.PenStyle.NoPen)
            c = QColor(self.pulse_color)
            c.setAlpha(self.pulse_alpha)
            p.setBrush(c)
            p.drawRoundedRect(0, 0, self.width(), self.height(), 15, 15)

        p.end()

class MacroScrollArea(QScrollArea):
    def wheelEvent(self, event):
        if event.modifiers() == Qt.KeyboardModifier.NoModifier:
            delta = event.angleDelta().y()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta)
        else:
            super().wheelEvent(event)

class DelayWidget(QWidget):
    def __init__(self, val, unit, index, editor):
        super().__init__()
        self.index = index
        self.editor = editor
        self.setFixedSize(90, 60) 
        
        self.inp = QLineEdit(str(val), self)
        self.inp.setGeometry(2, 4, 40, 26) 
        self.inp.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.inp.setStyleSheet("background: #1a1a1a; color: #ffffff; border: 1px solid #444; border-radius: 4px; font-size: 12px; font-weight: bold; padding: 0;")
        self.inp.editingFinished.connect(self.update_val)
        
        self.combo = NoScrollComboBox(self)
        self.combo.addItems(["мс", "с"])
        self.combo.setCurrentText(unit)
        self.combo.setGeometry(44, 4, 46, 26) 
        self.combo.setStyleSheet("""
            QComboBox { background: #1a1a1a; color: #ffffff; border: 1px solid #444; border-radius: 4px; font-size: 12px; font-weight: bold; padding: 0px 0px 0px 6px; }
            QComboBox::drop-down { border: none; width: 16px; }
            QComboBox::down-arrow { image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%23ffffff' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'/%3E%3C/svg%3E"); width: 10px; height: 10px; }
        """)
        self.combo.currentTextChanged.connect(self.update_val)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor("#444"), 2))
        mid_y = 40 
        p.drawLine(0, mid_y, self.width(), mid_y)
        p.setBrush(QColor("#ffffff")) 
        p.setPen(Qt.PenStyle.NoPen)
        r = 5 
        p.drawEllipse(self.width()//2 - r, mid_y - r, r*2, r*2) 
        
    def update_val(self):
        text = self.inp.text().replace(',', '.')
        num_str = "".join([c for c in text if c.isdigit() or c == '.'])
        m_data = self.editor.get_macro_data()
        try:
            v = float(num_str) if num_str else 100.0
            if v <= 0: v = 1.0
            if v.is_integer(): v = int(v)
            u = self.combo.currentText()
            m_data["events"][self.index]["val"] = v
            m_data["events"][self.index]["unit"] = u
            self.editor.save_macro_data(m_data)
            self.inp.setText(str(v))
        except: 
            v = m_data["events"][self.index].get("val", 100)
            self.inp.setText(str(v))

class InsertPlusButton(QPushButton):
    """Компактна кнопка '+' між блоками макросу для вставки нової дії у довільне місце."""
    def __init__(self, editor, insert_idx):
        super().__init__()
        self.editor = editor
        self.insert_idx = insert_idx
        self.setFixedSize(22, 40)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.hover = False
        self.setToolTip("Вставити дію сюди")
        self.clicked.connect(lambda: self.editor.insert_block_at(self.insert_idx))

    def enterEvent(self, e):
        self.hover = True
        self.update()

    def leaveEvent(self, e):
        self.hover = False
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = self.width() // 2, self.height() // 2
        if self.hover:
            p.setBrush(QColor(0, 229, 255, 40))
            p.setPen(QPen(QColor(ACCENT), 1.5))
            p.drawRoundedRect(2, 8, self.width() - 4, self.height() - 16, 5, 5)
            p.setPen(QPen(QColor(ACCENT), 2))
        else:
            p.setPen(QPen(QColor("#555555"), 1.5))
        p.drawLine(cx - 4, cy, cx + 4, cy)
        p.drawLine(cx, cy - 4, cx, cy + 4)

class ActionWidget(QPushButton):
    key_caught_sig = Signal(str)

    def __init__(self, data, index, editor):
        super().__init__()
        self.index = index
        self.editor = editor
        self.data = data
        self.hook = None
        self.drag_start_pos = None
        self.is_dragging = False
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setFixedHeight(40)
        self.update_look()
        self.key_caught_sig.connect(self.process_key)

    def update_look(self):
        d = self.data
        if d["type"] == "empty":
            self.setText("Вибрати дію...")
            self.setStyleSheet("border-radius: 8px; background: #1f1f1f; border: 1px dashed #555; color: #888; padding: 0 15px;")
        elif d["type"] == "move":
            self.setText(f"Курсор: {d.get('x', 0)}, {d.get('y', 0)}")
            self.setStyleSheet(f"border-radius: 8px; background: #142228; border: 1px solid {ACCENT}; color: #fff; padding: 0 15px;")
        else:
            val_str = str(d.get('val', ''))
            if val_str == "mouse_wheel_up":
                val_display = "СКРОЛ ВГОРУ ⬆"
            elif val_str == "mouse_wheel_down":
                val_display = "СКРОЛ ВНИЗ ⬇"
            elif val_str.startswith("mouse_"):
                val_display = val_str.replace("mouse_", "МИША: ").upper()
            else:
                val_display = val_str.upper()

            t = "Невідомо"
            if d["type"] == "tap": t = f"Клік: {val_display}"
            elif d["type"] == "press": t = f"Затиснути: {val_display}"
            elif d["type"] == "release": t = f"Відпустити: {val_display}"
            elif d["type"] == "text": t = f"Текст: {d['val'][:10]}..."
            elif d["type"] == "hotkey": t = f"Комбінація: {val_display}"
            self.setText(t)
            self.setStyleSheet("border-radius: 8px; background: #111; border: 1px solid #666; color: #fff; padding: 0 15px;")

        font_metrics = self.fontMetrics()
        w = font_metrics.horizontalAdvance(self.text()) + 45
        self.setFixedWidth(max(110, w))

    def mousePressEvent(self, e: QMouseEvent):
        if e.button() == Qt.MouseButton.LeftButton:
            self.drag_start_pos = e.position().toPoint()
            self.is_dragging = False
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e: QMouseEvent):
        if (e.buttons() & Qt.MouseButton.LeftButton) and self.drag_start_pos:
            dist = (e.position().toPoint() - self.drag_start_pos).manhattanLength()
            from PySide6.QtWidgets import QApplication
            if not self.is_dragging and dist >= QApplication.startDragDistance():
                self.is_dragging = True
                self.setStyleSheet(f"border-radius: 8px; background: #1a2a3a; border: 2px dashed {ACCENT}; color: {ACCENT}; padding: 0 15px;")
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e: QMouseEvent):
        if self.is_dragging:
            self.is_dragging = False
            self.update_look()
            g_pos = e.globalPosition().toPoint()
            self.editor.handle_block_drop(self.index, g_pos)
            return
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.show_menu()
        super().mouseReleaseEvent(e)

    def show_menu(self):
        self.unhook_if_listening()
        menu = QMenu(self)
        a_tap = menu.addAction("Натиснути і відпустити")
        a_press = menu.addAction("Затиснути клавішу")
        a_release = menu.addAction("Відпустити клавішу")
        a_hotkey = menu.addAction("Комбінація (швидко)")
        a_text = menu.addAction("Ввести текст")
        a_move = menu.addAction("📍 Перемістити курсор (X, Y)")
        menu.addSeparator()

        del_action = QWidgetAction(menu)
        del_btn = QPushButton("🗑 Видалити блок")
        del_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent; color: #fff; text-align: left;
                padding: 8px 25px; border: none; border-radius: 4px; font-size: 13px;
            }
            QPushButton:hover { background-color: #ff3366; color: white; }
        """)
        del_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        del_btn.clicked.connect(lambda: [menu.close(), QTimer.singleShot(50, self.delete_self)])
        del_action.setDefaultWidget(del_btn)
        menu.addAction(del_action)

        action = menu.exec(self.mapToGlobal(self.rect().bottomLeft()))

        if action == a_tap: self.start_listening("tap")
        elif action == a_press: self.start_listening("press")
        elif action == a_release: self.start_listening("release")
        elif action == a_hotkey: self.ask_hotkey()
        elif action == a_text: self.ask_text()
        elif action == a_move: self.ask_mouse_move()

    def ask_mouse_move(self):
        self.unhook_if_listening()
        cur_p = QCursor.pos()
        default_str = f"{self.data.get('x', cur_p.x())}, {self.data.get('y', cur_p.y())}"
        text, ok = QInputDialog.getText(
            self,
            "Координати курсора (X, Y)",
            "Введіть X, Y через кому (поточні координати підставлено):",
            text=default_str
        )
        if ok and text:
            parts = text.replace(";", ",").split(",")
            if len(parts) >= 2:
                try:
                    x, y = int(parts[0].strip()), int(parts[1].strip())
                    self.save_event({"type": "move", "x": x, "y": y})
                except ValueError:
                    pass

    def start_listening(self, t_type):
        if self.editor.main_app.listening_action:
            self.editor.main_app.listening_action.unhook_if_listening()

        self.listen_type = t_type
        self.setText("Слухаю...")
        self.setStyleSheet("border-radius: 8px; background: #ff3366; border: none; color: #fff; padding: 0 15px;")
        self.editor.main_app.listening_action = self
        self.hook = keyboard.on_press(self.on_key)

    def on_key(self, e):
        self.key_caught_sig.emit(e.name.lower())

    def process_key(self, key_name):
        self.unhook_if_listening()
        key_name = key_name.replace('left ', '').replace('right ', '')
        if key_name in ("windows", "left windows", "right windows"):
            key_name = "win"
        self.save_event({"type": self.listen_type, "val": key_name})

    def ask_hotkey(self):
        self.unhook_if_listening()
        text, ok = QInputDialog.getText(self, "Комбінація", "Введіть комбінацію (напр. ctrl+v):")
        if ok and text:
            self.save_event({"type": "hotkey", "val": text})

    def ask_text(self):
        self.unhook_if_listening()
        text, ok = QInputDialog.getText(self, "Введення", "Текст для макросу:")
        if ok and text:
            self.save_event({"type": "text", "val": text})

    def save_event(self, new_data):
        self.data = new_data
        m_data = self.editor.get_macro_data()
        m_data["events"][self.index] = new_data
        self.editor.save_macro_data(m_data)
        self.update_look()

    def delete_self(self):
        self.unhook_if_listening()
        m_data = self.editor.get_macro_data()
        events = m_data["events"]
        if self.index > 0 and events[self.index - 1]["type"] == "delay":
            events.pop(self.index)
            events.pop(self.index - 1)
        elif self.index < len(events) - 1 and events[self.index + 1]["type"] == "delay":
            events.pop(self.index + 1)
            events.pop(self.index)
        else:
            events.pop(self.index)
        m_data["events"] = events
        self.editor.save_macro_data(m_data)
        self.editor.render()

    def unhook_if_listening(self):
        if self.editor.main_app.listening_action == self:
            self.editor.main_app.listening_action = None
        if self.hook:
            try:
                keyboard.unhook(self.hook)
            except Exception:
                pass
            self.hook = None
        self.update_look()

class PlusButton(QPushButton):
    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.setFixedSize(40, 40)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.hover = False
        self.clicked.connect(self.editor.add_block)

    def enterEvent(self, e):
        self.hover = True
        self.update()

    def leaveEvent(self, e):
        self.hover = False
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor("#ffffff") if self.hover else QColor("#555")
        pen = QPen(color, 2, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawRoundedRect(1, 1, self.width() - 2, self.height() - 2, 8, 8)
        p.setPen(QPen(color, 2, Qt.PenStyle.SolidLine))
        cx, cy = self.width() // 2, self.height() // 2
        p.drawLine(cx - 6, cy, cx + 6, cy)
        p.drawLine(cx, cy - 6, cx, cy + 6)

class MacroEditor(QFrame):
    stop_record_sig = Signal(bool)

    def __init__(self, main_app, parent=None):
        super().__init__(parent)
        self.main_app = main_app
        self.current_macro = None
        self.setStyleSheet("background: transparent; border: none;")
        self.setMinimumHeight(0)
        self.setMaximumHeight(0)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        header = QHBoxLayout()
        self.lbl_title = QLabel("")
        self.lbl_title.setStyleSheet("color: #ffffff; font-weight: bold; font-size: 14px;")
        header.addWidget(self.lbl_title)
        header.addSpacing(12)

        self.combo_mode_edit = AnimatedComboBox()
        self.combo_mode_edit.setFixedSize(230, 30)
        self.combo_mode_edit.setStyleSheet("QComboBox { background: #1a1a1a; border: 1px solid #444; color: #00e5ff; border-radius: 5px; padding: 2px 8px; font-size: 12px; font-weight: bold; }")
        self.combo_mode_edit.addItems([
            "One Shot (Один раз)",
            "Repeat while held (Поки натиснуто)",
            "Toggle (Вкл / Викл)"
        ])
        self.combo_mode_edit.currentIndexChanged.connect(self.on_mode_changed)
        header.addWidget(self.combo_mode_edit)
        header.addStretch()
        layout.addLayout(header)

        self.scroll = MacroScrollArea()
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setWidgetResizable(True)
        self.scroll.setMinimumHeight(75)

        self.content = QWidget()
        self.content_layout = QHBoxLayout(self.content)
        self.content_layout.setAlignment(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft)
        self.content_layout.setContentsMargins(0, 0, 0, 5)
        self.content_layout.setSpacing(6)
        self.scroll.setWidget(self.content)

        layout.addWidget(self.scroll)

        self.bottom_lay = QHBoxLayout()
        self.bottom_lay.setContentsMargins(5, 0, 0, 0)

        self.btn_record = QPushButton("⬤ Авто-запис дій")
        self.btn_record.setFixedSize(150, 32)
        self.btn_record.setStyleSheet("""
            QPushButton { background-color: transparent; border: 1px solid #ff3366; color: #ff3366; border-radius: 4px; font-size: 12px; font-weight: bold; padding: 0px 10px; }
            QPushButton:hover { background-color: #ff3366; color: white; }
        """)
        self.btn_record.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_record.clicked.connect(self.toggle_record)

        self.cb_rec_mouse_move = QCheckBox("Записувати рух курсора (X, Y)")
        self.cb_rec_mouse_move.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._rec_mouse_move = False
        self.cb_rec_mouse_move.toggled.connect(lambda v: setattr(self, "_rec_mouse_move", bool(v)))
        self.cb_rec_mouse_move.setStyleSheet(f"QCheckBox {{ color: {TEXT_SUB}; font-size: 12px; margin-left: 10px; }} QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid #444; border-radius: 4px; background: #141414; }} QCheckBox::indicator:checked {{ background: {ACCENT}; border: 1px solid {ACCENT}; }}")

        self.lbl_record_status = QLabel("")
        self.lbl_record_status.setStyleSheet("color: #888; font-size: 11px;")

        self.bottom_lay.addWidget(self.btn_record)
        self.bottom_lay.addWidget(self.cb_rec_mouse_move)
        self.bottom_lay.addWidget(self.lbl_record_status)
        self.bottom_lay.addStretch()
        layout.addLayout(self.bottom_lay)

        self.anim = QVariantAnimation(self)
        self.anim.setDuration(300)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.valueChanged.connect(self.set_editor_height)

        self.is_recording = False
        self.recorded_events = []
        self.last_event_time = 0
        self.last_move_time = 0
        self.last_move_pos = (0, 0)
        self.stop_record_sig.connect(self.stop_recording)

    def on_mode_changed(self, idx):
        if not self.current_macro:
            return
        m_data = self.get_macro_data()
        modes = ["One Shot", "Repeat while held", "Toggle"]
        if 0 <= idx < len(modes):
            new_mode = modes[idx]
            if m_data.get("mode") != new_mode:
                m_data["mode"] = new_mode
                self.save_macro_data(m_data)
                self.lbl_title.setText(f"Редактор: {self.current_macro}")
                self.main_app.update_macros_list()

    def set_editor_height(self, val):
        self.setMinimumHeight(val)
        self.setMaximumHeight(val)
        self.main_app.update_dynamic_layout()

    def get_macro_data(self):
        m_data = self.main_app.config["MACROS"].get(self.current_macro)
        if isinstance(m_data, str):
            try:
                m_data = json.loads(m_data)
            except Exception:
                m_data = []
        if isinstance(m_data, list):
            return {"mode": "One Shot", "events": m_data}
        return m_data if isinstance(m_data, dict) else {"mode": "One Shot", "events": []}

    def save_macro_data(self, m_data):
        self.main_app.config["MACROS"][self.current_macro] = json.dumps(m_data)
        self.main_app.save_config()

    def load(self, name):
        self.current_macro = name
        m_data = self.get_macro_data()
        mode = m_data.get("mode", "One Shot")
        self.lbl_title.setText(f"Редактор: {name}")
        self.combo_mode_edit.blockSignals(True)
        if mode == "One Shot": self.combo_mode_edit.setCurrentIndex(0)
        elif mode == "Repeat while held": self.combo_mode_edit.setCurrentIndex(1)
        else: self.combo_mode_edit.setCurrentIndex(2)
        self.combo_mode_edit.blockSignals(False)

        self.render()
        if self.maximumHeight() == 0:
            self.main_app.combo_header_widget.hide()
            self.anim.setStartValue(0)
            self.anim.setEndValue(140)
            self.anim.start()

    def hide_editor(self):
        if self.is_recording:
            self.stop_recording(stopped_by_esc=True)
        for child in self.findChildren(QPushButton):
            if isinstance(child, ActionWidget):
                child.unhook_if_listening()
        if self.maximumHeight() > 0:
            self.main_app.combo_header_widget.show()
            self.main_app.set_vkb_visible(False)
            self.anim.setStartValue(self.maximumHeight())
            self.anim.setEndValue(0)
            self.anim.start()

    def toggle_record(self):
        if not self.is_recording:
            self.start_recording()
        else:
            self.stop_recording(stopped_by_esc=False)

    def start_recording(self):
        self.is_recording = True
        self.btn_record.setText("⏹ Зупинити (Esc)")
        self.btn_record.setStyleSheet("QPushButton { background-color: #ff3366; border: 1px solid #ff3366; color: white; border-radius: 4px; font-size: 12px; font-weight: bold; padding: 0px 10px; }")
        self.lbl_record_status.setText("Запис... Натисніть Esc для зупинки.")
        self.lbl_record_status.setStyleSheet("color: #ff3366; font-size: 11px;")

        self.recorded_events = []
        self.pressed_keys_record = set()
        # Хук миші працює в чужому потоці — не чіпаємо з нього Qt-віджет, кешуємо прапорець
        self._rec_mouse_move = self.cb_rec_mouse_move.isChecked()
        self.last_event_time = time.time()
        self.last_move_time = 0.0
        self.last_move_pos = (0, 0)
        self.main_app.set_vkb_visible(False)

        keyboard.hook(self.record_kbd_hook)
        try:
            mouse.hook(self.record_mouse_hook)
        except Exception:
            pass

    def stop_recording(self, stopped_by_esc=False):
        if not self.is_recording:
            return
        self.is_recording = False
        try:
            keyboard.unhook(self.record_kbd_hook)
        except Exception:
            pass
        try:
            mouse.unhook(self.record_mouse_hook)
        except Exception:
            pass

        self.btn_record.setText("⬤ Авто-запис дій")
        self.btn_record.setStyleSheet("QPushButton { background-color: transparent; border: 1px solid #ff3366; color: #ff3366; border-radius: 4px; font-size: 12px; font-weight: bold; padding: 0px 10px; } QPushButton:hover { background-color: #ff3366; color: white; }")
        self.lbl_record_status.setText("")

        if self.recorded_events:
            # Видаляємо лише завершальне натискання Esc або один фінальний клік ЛКМ по кнопці "Зупинити"
            removed_stop_click = False
            while self.recorded_events:
                last_event = self.recorded_events[-1]
                val = last_event.get("val")
                etype = last_event.get("type")
                if etype == "delay":
                    self.recorded_events.pop()
                elif val == "esc":
                    self.recorded_events.pop()
                elif not stopped_by_esc and not removed_stop_click and val == "mouse_left":
                    self.recorded_events.pop()
                    if etype == "press":
                        removed_stop_click = True
                else:
                    break

            m_data = self.get_macro_data()
            if m_data["events"] and self.recorded_events:
                m_data["events"].append({"type": "delay", "val": 100, "unit": "мс"})

            m_data["events"].extend(self.recorded_events)
            self.save_macro_data(m_data)
            self.render()
            QTimer.singleShot(50, lambda: self.scroll.horizontalScrollBar().setValue(self.scroll.horizontalScrollBar().maximum()))

    def record_kbd_hook(self, event):
        if not self.is_recording:
            return
        key = event.name.lower().replace('left ', '').replace('right ', '')

        if key == "esc":
            if event.event_type == keyboard.KEY_UP:
                self.stop_record_sig.emit(True)
            return

        is_down = (event.event_type == keyboard.KEY_DOWN)
        if is_down:
            if key in self.pressed_keys_record:
                return
            self.pressed_keys_record.add(key)
        else:
            self.pressed_keys_record.discard(key)

        now = time.time()
        delay = int((now - self.last_event_time) * 1000)
        self.last_event_time = now
        if delay > 5 and self.recorded_events:
            self.recorded_events.append({"type": "delay", "val": delay, "unit": "мс"})

        e_type = "press" if is_down else "release"
        if key in ("windows", "left windows", "right windows"):
            key = "win"
        self.recorded_events.append({"type": e_type, "val": key})

    def record_mouse_hook(self, event):
        if not self.is_recording:
            return
        import mouse
        now = time.time()

        if isinstance(event, mouse.MoveEvent):
            if not self._rec_mouse_move:
                return
            if (now - self.last_move_time) < 0.030:
                return
            dx = abs(event.x - self.last_move_pos[0])
            dy = abs(event.y - self.last_move_pos[1])
            if dx < 4 and dy < 4:
                return
            self.last_move_time = now
            self.last_move_pos = (event.x, event.y)
            delay = int((now - self.last_event_time) * 1000)
            self.last_event_time = now
            if delay > 5 and self.recorded_events:
                self.recorded_events.append({"type": "delay", "val": delay, "unit": "мс"})
            self.recorded_events.append({"type": "move", "x": int(event.x), "y": int(event.y)})

        elif isinstance(event, mouse.ButtonEvent):
            delay = int((now - self.last_event_time) * 1000)
            self.last_event_time = now
            if delay > 5 and self.recorded_events:
                self.recorded_events.append({"type": "delay", "val": delay, "unit": "мс"})
            e_type = "press" if event.event_type == mouse.DOWN else "release"
            btn_name = f"mouse_{event.button}"
            self.recorded_events.append({"type": e_type, "val": btn_name})

        elif isinstance(event, mouse.WheelEvent):
            delay = int((now - self.last_event_time) * 1000)
            self.last_event_time = now
            if delay > 5 and self.recorded_events:
                self.recorded_events.append({"type": "delay", "val": delay, "unit": "мс"})
            wheel_dir = "mouse_wheel_up" if event.delta > 0 else "mouse_wheel_down"
            self.recorded_events.append({"type": "tap", "val": wheel_dir})

    def handle_block_drop(self, src_event_idx, global_pos):
        """Переміщує блок дії на нову позицію методом Drag-and-Drop зі збереженням структури затримок."""
        m_data = self.get_macro_data()
        events = m_data.get("events", [])
        if not (0 <= src_event_idx < len(events)):
            return

        action_widgets = []
        for i in range(self.content_layout.count()):
            w = self.content_layout.itemAt(i).widget()
            if isinstance(w, ActionWidget):
                action_widgets.append(w)

        if len(action_widgets) <= 1:
            return

        target_action_pos = len(action_widgets) - 1
        for pos_idx, aw in enumerate(action_widgets):
            center_x = aw.mapToGlobal(QPoint(aw.width() // 2, aw.height() // 2)).x()
            if global_pos.x() < center_x:
                target_action_pos = pos_idx
                break

        actions_only = [ev for ev in events if ev.get("type") != "delay"]
        delays_only = [ev for ev in events if ev.get("type") == "delay"]

        src_action_pos = sum(1 for ev in events[:src_event_idx] if ev.get("type") != "delay")
        if src_action_pos == target_action_pos or not (0 <= src_action_pos < len(actions_only)):
            return

        item = actions_only.pop(src_action_pos)
        actions_only.insert(target_action_pos, item)

        rebuilt = []
        for idx, act_ev in enumerate(actions_only):
            rebuilt.append(act_ev)
            if idx < len(actions_only) - 1:
                d_ev = delays_only[idx] if idx < len(delays_only) else {"type": "delay", "val": 100, "unit": "мс"}
                rebuilt.append(d_ev)

        m_data["events"] = rebuilt
        self.save_macro_data(m_data)
        self.render()

    def insert_block_at(self, event_idx):
        """Вставляє нову порожню дію та затримку у вказану позицію макросу."""
        m_data = self.get_macro_data()
        events = m_data.get("events", [])
        new_action = {"type": "empty", "val": ""}
        new_delay = {"type": "delay", "val": 100, "unit": "мс"}

        if not events:
            events.append(new_action)
        elif event_idx <= 0:
            events.insert(0, new_delay)
            events.insert(0, new_action)
        elif event_idx >= len(events):
            events.append(new_delay)
            events.append(new_action)
        else:
            events.insert(event_idx, new_action)
            events.insert(event_idx, new_delay)

        m_data["events"] = events
        self.save_macro_data(m_data)
        self.render()

    def render(self):
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget():
                if isinstance(item.widget(), ActionWidget):
                    item.widget().unhook_if_listening()
                item.widget().deleteLater()

        m_data = self.get_macro_data()
        events = m_data.get("events", [])

        if events:
            self.content_layout.addWidget(InsertPlusButton(self, 0))

        for i, ev in enumerate(events):
            if ev["type"] == "delay":
                w = DelayWidget(ev.get("val", 100), ev.get("unit", "мс"), i, self)
                self.content_layout.addWidget(w)
            else:
                w = ActionWidget(ev, i, self)
                self.content_layout.addWidget(w)
                if i < len(events) - 1:
                    self.content_layout.addWidget(InsertPlusButton(self, i + 1))

        spacer = QWidget()
        spacer.setFixedWidth(6)
        self.content_layout.addWidget(spacer)
        btn_plus = PlusButton(self)
        self.content_layout.addWidget(btn_plus)

    def add_block(self):
        m_data = self.get_macro_data()
        events = m_data.get("events", [])
        if len(events) > 0:
            events.append({"type": "delay", "val": 100, "unit": "мс"})
        events.append({"type": "empty", "val": ""})
        m_data["events"] = events
        self.save_macro_data(m_data)
        self.render()
        QTimer.singleShot(50, lambda: self.scroll.horizontalScrollBar().setValue(self.scroll.horizontalScrollBar().maximum()))

class VKBButton(QPushButton):
    def __init__(self, text, key_id):
        super().__init__(text)
        self.key_id = key_id
        self.active = False
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.update_style()
        
    def update_style(self):
        base = "border-radius: 6px; font-size: 10px; font-weight: bold; padding: 0px;"
        if self.active:
            self.setStyleSheet(f"QPushButton {{ background: #1a1a1a; color: {ACCENT}; border: 2px solid {ACCENT}; {base} }}")
        else:
            self.setStyleSheet(f"""
                QPushButton {{ background: #1a1a1a; color: #fff; border: 1px solid #333; {base} }}
                QPushButton:hover {{ background: #222; border: 1px solid {ACCENT}; color: {ACCENT}; }}
                QPushButton:pressed {{ background: #333; }}
            """)

class VirtualKeyboard(QFrame):
    key_pressed = Signal(str)
    
    def handle_mouse_combo(self, index):
        if index == 0: return
        btn_map = {
            1: "mouse_left", 
            2: "mouse_right", 
            3: "mouse_middle", 
            4: "mouse_x1", 
            5: "mouse_x2",
            6: "mouse_wheel_up",
            7: "mouse_wheel_down"
        }
        if index in btn_map:
            self.key_pressed.emit(btn_map[index])
            
        self.combo_mouse.setCurrentIndex(0)

    def __init__(self):
        super().__init__()
        self.setStyleSheet("background: transparent;")
        self.btn_refs = {}
        self.setMinimumSize(1160, 335)
        
        main_lay = QHBoxLayout(self)
        main_lay.setContentsMargins(0, 0, 0, 0)
        main_lay.setSpacing(20)
        main_lay.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        mb_lay = QVBoxLayout()
        mb_lay.setSpacing(6)
        mb_lay.setContentsMargins(0, 0, 0, 0)
        
        rows = [
            [("F13", "f13", 58), ("F14", "f14", 58), ("F15", "f15", 58), ("F16", "f16", 58), ("F17", "f17", 58), ("F18", "f18", 58), ("F19", "f19", 58), ("F20", "f20", 58), ("F21", "f21", 58), ("F22", "f22", 58), ("F23", "f23", 58), ("F24", "f24", 58)],
            [("Esc", "esc", 46), ("F1", "f1", 46), ("F2", "f2", 46), ("F3", "f3", 46), ("F4", "f4", 46), ("F5", "f5", 46), ("F6", "f6", 46), ("F7", "f7", 46), ("F8", "f8", 46), ("F9", "f9", 46), ("F10", "f10", 46), ("F11", "f11", 46), ("F12", "f12", 46), ("PrtSc", "print screen", 74)],
            [("`", "`", 46), ("1", "1", 46), ("2", "2", 46), ("3", "3", 46), ("4", "4", 46), ("5", "5", 46), ("6", "6", 46), ("7", "7", 46), ("8", "8", 46), ("9", "9", 46), ("0", "0", 46), ("-", "-", 46), ("=", "=", 46), ("Back", "backspace", 74)],
            [("Tab", "tab", 66), ("Q", "q", 46), ("W", "w", 46), ("E", "e", 46), ("R", "r", 46), ("T", "t", 46), ("Y", "y", 46), ("U", "u", 46), ("I", "i", 46), ("O", "o", 46), ("P", "p", 46), ("[", "[", 46), ("]", "]", 46), ("\\", "\\", 54)],
            [("Caps", "caps lock", 82), ("A", "a", 46), ("S", "s", 46), ("D", "d", 46), ("F", "f", 46), ("G", "g", 46), ("H", "h", 46), ("J", "j", 46), ("K", "k", 46), ("L", "l", 46), (";", ";", 46), ("'", "'", 46), ("Enter", "enter", 90)],
            [("Shift", "left shift", 106), ("Z", "z", 46), ("X", "x", 46), ("C", "c", 46), ("V", "v", 46), ("B", "b", 46), ("N", "n", 46), ("M", "m", 46), (",", ",", 46), (".", ".", 46), ("/", "/", 46), ("Shift", "right shift", 118)],
            [("Ctrl", "ctrl", 54), ("Win", "win", 54), ("Alt", "alt", 54), ("Space", "space", 330), ("Alt", "right alt", 54), ("Win", "right windows", 54), ("Menu", "menu", 54), ("Ctrl", "right ctrl", 54)]
        ]
        for r in rows:
            r_lay = QHBoxLayout()
            r_lay.setSpacing(6)
            for text, kid, width in r:
                btn = VKBButton(text, kid)
                btn.setFixedSize(width, 44)
                btn.clicked.connect(lambda checked=False, k=kid: self.key_pressed.emit(k))
                self.btn_refs[kid] = btn
                r_lay.addWidget(btn)
            mb_lay.addLayout(r_lay)
        main_lay.addLayout(mb_lay)

        right_side_lay = QVBoxLayout()
        right_side_lay.setContentsMargins(0, 0, 0, 0)
        right_side_lay.setSpacing(10)

        self.combo_mouse = QComboBox()
        # Додано пункти прокрутки 6 та 7:
        self.combo_mouse.addItems([
            "🖱 Кнопки миші...", 
            "Ліва (LMB)", 
            "Права (RMB)", 
            "Середня (MMB)", 
            "Бокова 1 (X1)", 
            "Бокова 2 (X2)",
            "Колесо вгору (Scroll Up)",
            "Колесо вниз (Scroll Down)"
        ])
        self.combo_mouse.setFixedSize(306, 40)
        self.combo_mouse.setStyleSheet("QComboBox { background: #1a1a1a; color: #fff; border: 1px dashed #555; border-radius: 6px; font-weight: bold; padding: 5px 10px; } QComboBox:hover { border: 1px solid #00e5ff; }")
        self.combo_mouse.activated.connect(self.handle_mouse_combo)
        right_side_lay.addWidget(self.combo_mouse, alignment=Qt.AlignmentFlag.AlignRight)

        keys_hbox = QHBoxLayout()
        keys_hbox.setContentsMargins(0, 0, 0, 0)
        keys_hbox.setSpacing(20)

        nav_layout = QGridLayout()
        nav_layout.setSpacing(6)
        nav_layout.setContentsMargins(0, 5, 0, 0) 
        nav_keys = [
            ("Ins", "insert", 0, 0), ("Home", "home", 0, 1), ("PgUp", "page up", 0, 2),
            ("Del", "delete", 1, 0), ("End", "end", 1, 1), ("PgDn", "page down", 1, 2),
            ("Up", "up", 3, 1),
            ("Left", "left", 4, 0), ("Down", "down", 4, 1), ("Right", "right", 4, 2)
        ]
        for text, kid, r, c in nav_keys:
            btn = VKBButton(text, kid)
            btn.setFixedSize(46, 44)
            btn.clicked.connect(lambda checked=False, k=kid: self.key_pressed.emit(k))
            self.btn_refs[kid] = btn
            nav_layout.addWidget(btn, r, c)
        nav_layout.setRowMinimumHeight(2, 44)
        keys_hbox.addLayout(nav_layout)

        num_layout = QGridLayout()
        num_layout.setSpacing(6)
        num_layout.setContentsMargins(0, 5, 0, 0)
        numpad_keys = [
            ("Num", "num lock", 0, 0, 1, 1, 46, 44), ("/", "num /", 0, 1, 1, 1, 46, 44), 
            ("*", "num *", 0, 2, 1, 1, 46, 44), ("-", "num -", 0, 3, 1, 1, 46, 44),
            ("7", "num 7", 1, 0, 1, 1, 46, 44), ("8", "num 8", 1, 1, 1, 1, 46, 44), 
            ("9", "num 9", 1, 2, 1, 1, 46, 44), ("+", "num +", 1, 3, 2, 1, 46, 94),
            ("4", "num 4", 2, 0, 1, 1, 46, 44), ("5", "num 5", 2, 1, 1, 1, 46, 44), 
            ("6", "num 6", 2, 2, 1, 1, 46, 44),
            ("1", "num 1", 3, 0, 1, 1, 46, 44), ("2", "num 2", 3, 1, 1, 1, 46, 44),
            ("3", "num 3", 3, 2, 1, 1, 46, 44), ("Ent", "num enter", 3, 3, 2, 1, 46, 94),
            ("0", "num 0", 4, 0, 1, 2, 98, 44), (".", "num .", 4, 2, 1, 1, 46, 44) 
        ]
        for text, kid, r, c, rs, cs, w, h in numpad_keys:
            btn = VKBButton(text, kid)
            btn.setFixedSize(w, h)
            btn.clicked.connect(lambda checked=False, k=kid: self.key_pressed.emit(k))
            self.btn_refs[kid] = btn
            num_layout.addWidget(btn, r, c, rs, cs)
        keys_hbox.addLayout(num_layout)

        right_side_lay.addLayout(keys_hbox)
        right_side_lay.addStretch()

        main_lay.addLayout(right_side_lay)
        main_lay.addStretch()

    def update_keys(self, active_keys):
        for key_id, btn in self.btn_refs.items():
            btn.active = key_id in active_keys
            btn.update_style()

class DelayLineEdit(QLineEdit):
    def __init__(self, val, main_app, parent=None):
        super().__init__(str(val), parent)
        self.main_app = main_app
        self.setFixedSize(38, 26)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(f"QLineEdit {{ background: #111; color: #fff; border: 1px solid #444; border-radius: 4px; font-size: 12px; padding: 0px; }} QLineEdit:focus {{ border: 1px solid {ACCENT}; }}")
        
        self.tooltip_timer = QTimer(self)
        self.tooltip_timer.setSingleShot(True)
        self.tooltip_timer.timeout.connect(self._show_tooltip)

    def enterEvent(self, e):
        super().enterEvent(e)
        self.tooltip_timer.start(500)

    def _show_tooltip(self):
        pos = self.mapToGlobal(QPoint(self.width() // 2, 0))
        self.main_app.tooltip.show_text("Затримка після запуску цієї програми (перед наступною)", pos, "top")

    def leaveEvent(self, e):
        super().leaveEvent(e)
        self.tooltip_timer.stop()
        self.main_app.tooltip.hide_tip()

class MultiLaunchEditor(QFrame):
    def __init__(self, main_app, parent=None):
        super().__init__(parent)
        self.main_app = main_app
        self.current_group = None
        
        self.setObjectName("multiEditor")
        self.setStyleSheet("#multiEditor { background: #111; border: 1px solid #222; border-radius: 8px; }")
        self.setMinimumWidth(0)
        self.setMaximumWidth(0)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        
        self.header = QFrame()
        self.header.setStyleSheet("border: none; background: transparent;")
        header_lay = QHBoxLayout(self.header)
        header_lay.setContentsMargins(0, 0, 0, 0)
        
        self.lbl_title = QLabel("")
        self.lbl_title.setStyleSheet(f"color: {ACCENT}; font-weight: bold; font-size: 16px; border: none;")
        self.lbl_title.setWordWrap(True)
        
        btn_close = QPushButton("")
        btn_close.setIcon(QIcon(os.path.join(ASSETS_DIR, "close.svg")))
        btn_close.setIconSize(QSize(16, 16))
        btn_close.setFixedSize(30, 30)
        btn_close.setStyleSheet("QPushButton { background: transparent; border: none; } QPushButton:hover { background: rgba(255, 51, 102, 0.15); border-radius: 4px; }")
        btn_close.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_close.clicked.connect(self.hide_editor)
        
        header_lay.addWidget(self.lbl_title, stretch=1)
        header_lay.addWidget(btn_close)
        layout.addWidget(self.header)
        
        self.scroll = QScrollArea()
        self.scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidgetResizable(True)
        
        self.content = QWidget()
        self.content.setStyleSheet("background: transparent;")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(8)
        
        self.btn_add = QPushButton("➕ Додати елемент")
        self.btn_add.setFixedHeight(40)
        self.btn_add.setStyleSheet(f"QPushButton {{ background-color: {BG_HOVER}; border: 1px dashed #555; color: {TEXT_MAIN}; border-radius: 5px; font-weight: bold; }} QPushButton:hover {{ border: 1px solid {ACCENT}; color: {ACCENT}; }}")
        self.btn_add.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_add.clicked.connect(self.show_add_menu)
        
        self.scroll.setWidget(self.content)
        layout.addWidget(self.scroll)
        
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(350)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.valueChanged.connect(self.set_editor_width)

    def set_editor_width(self, val):
        self.setMinimumWidth(val)
        self.setMaximumWidth(val)
        self.main_app.update_dynamic_layout()

    def load(self, name):
        self.current_group = name
        self.lbl_title.setText(f"Група:\n{name}")
        self.render()
        if self.maximumWidth() == 0:
            self.anim.setStartValue(0)
            self.anim.setEndValue(340)
            self.anim.start()

    def hide_editor(self):
        if self.maximumWidth() > 0:
            self.anim.setStartValue(self.maximumWidth())
            self.anim.setEndValue(0)
            self.anim.start()
            
            self.current_group = None
            if hasattr(self.main_app, 'update_multi_list'):
                self.main_app.update_multi_list()

    def render(self):
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            if item.widget() and item.widget() != self.btn_add:
                item.widget().deleteLater()
            
        items = self.main_app.config.get("MULTI_LAUNCH", {}).get(self.current_group, [])
        
        if not items:
            lbl = QLabel("Тут поки порожньо.\nДодайте файли чи посилання.")
            lbl.setStyleSheet("color: #666; font-style: italic; border: none;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.content_layout.addWidget(lbl)
            
        for i, item_data in enumerate(items):
            from PySide6.QtCore import QFileInfo
            import os
            
            if isinstance(item_data, str):
                action_str = item_data
                delay_val = 0.5 
            else:
                action_str = item_data.get("action", "")
                delay_val = item_data.get("delay", 0.5)
            
            row = QWidget()
            row.setObjectName("rowWidget")
            row.setStyleSheet("#rowWidget { background: #1a1a1a; border: 1px solid #333; border-radius: 6px; }")
            row.setMinimumHeight(46)
            
            row_lay = QHBoxLayout(row)
            row_lay.setContentsMargins(10, 5, 8, 5)
            row_lay.setSpacing(6)
            
            is_url = action_str.startswith("URL:")
            val_clean = action_str.split(":", 1)[1]
            
            lbl_icon = QLabel()
            lbl_icon.setStyleSheet("border: none; background: transparent;")
            lbl_icon.setFixedSize(24, 24)
            lbl_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            
            if is_url:
                lbl_icon.setText("🌐")
                lbl_icon.setStyleSheet("border: none; background: transparent; font-size: 16px;")
            else:
                path = val_clean
                val_clean = path.replace("\\", "/").split("/")[-1]
                if os.path.exists(path):
                    icon = self.main_app.icon_provider.icon(QFileInfo(path))
                    lbl_icon.setPixmap(icon.pixmap(24, 24))
                else:
                    lbl_icon.setText("📁" if "." not in val_clean else "❓")
                    lbl_icon.setStyleSheet("border: none; background: transparent; font-size: 16px;")
            
            lbl_text = QLabel(val_clean)
            lbl_text.setStyleSheet("border: none; background: transparent; color: #ddd; font-weight: bold;")
            lbl_text.setWordWrap(True)
            lbl_text.setMinimumWidth(10)
            
            is_last_item = (i == len(items) - 1)
            
            if not is_last_item:
                inp_delay = DelayLineEdit(delay_val, self.main_app)
                
                def make_update_func(idx, inp_widget, current_act):
                    def _update():
                        try: 
                            v = float(inp_widget.text().replace(',', '.'))
                            if v < 0: v = 0.0
                        except: v = 0.5
                        inp_widget.setText(str(v)) 
                        group = self.main_app.config["MULTI_LAUNCH"].get(self.current_group, [])
                        if 0 <= idx < len(group):
                            group[idx] = {"action": current_act, "delay": v}
                            self.main_app.save_config()
                    return _update
                    
                inp_delay.editingFinished.connect(make_update_func(i, inp_delay, action_str))
                
                lbl_sec = QLabel("с")
                lbl_sec.setStyleSheet("color: #777; font-size: 12px; background: transparent; border: none;")
            
            btn_del = QPushButton("")
            btn_del.setIcon(QIcon(os.path.join(ASSETS_DIR, "trash.svg")))
            btn_del.setIconSize(QSize(18, 18))
            btn_del.setFixedSize(26, 26)
            btn_del.setStyleSheet(f"QPushButton {{ background: transparent; border: none; border-radius: 4px; }} QPushButton:hover {{ background: rgba(255, 51, 102, 0.2); }}")
            btn_del.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            btn_del.clicked.connect(lambda checked, idx=i: QTimer.singleShot(50, lambda: self.delete_item(idx)))
            
            row_lay.addWidget(lbl_icon)
            row_lay.addWidget(lbl_text, stretch=1)
            
            if not is_last_item:
                row_lay.addWidget(inp_delay)
                row_lay.addWidget(lbl_sec)
                
            row_lay.addWidget(btn_del)
            
            self.content_layout.addWidget(row)
            
        self.content_layout.addWidget(self.btn_add)
        self.content_layout.addStretch()

    def show_add_menu(self):
        menu = QMenu(self)
        a_exe = menu.addAction("📄 Додати програму (.exe)")
        a_folder = menu.addAction("📁 Додати папку")
        a_url = menu.addAction("🌐 Додати посилання (URL)")
        
        action = menu.exec(self.btn_add.mapToGlobal(self.btn_add.rect().bottomLeft()))
        if action == a_exe:
            from PySide6.QtWidgets import QFileDialog
            path, _ = QFileDialog.getOpenFileName(self, "Виберіть програму", "", "Programs (*.exe);;All Files (*)")
            if path: self.add_item(f"EXE:{path}")
        elif action == a_folder:
            from PySide6.QtWidgets import QFileDialog
            path = QFileDialog.getExistingDirectory(self, "Виберіть папку")
            if path: self.add_item(f"EXE:{path}")
        elif action == a_url:
            from PySide6.QtWidgets import QInputDialog
            text, ok = QInputDialog.getText(self, "Посилання", "Введіть URL:")
            if ok and text:
                self.add_item(f"URL:{text}")

    def add_item(self, val):
        if self.current_group:
            group = self.main_app.config.get("MULTI_LAUNCH", {}).get(self.current_group, [])
            group.append({"action": val, "delay": 0.5})
            self.main_app.config["MULTI_LAUNCH"][self.current_group] = group
            self.main_app.save_config()
            self.render()

    def delete_item(self, index):
        if self.current_group:
            group = self.main_app.config["MULTI_LAUNCH"].get(self.current_group, [])
            if 0 <= index < len(group):
                group.pop(index)
                self.main_app.config["MULTI_LAUNCH"][self.current_group] = group
                self.main_app.save_config()
                self.render()

class InfoButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__("?", parent)
        self.setFixedSize(20, 20)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: 1px solid #555;
                color: #888;
                border-radius: 10px;
                font-size: 11px;
                font-weight: bold;
                padding: 0;
                margin: 0;
            }
            QPushButton:hover {
                background: #222;
                border: 1px solid #777;
                color: #aaa;
            }
        """)

class InfoPopup(QWidget):
    def __init__(self, text, btn_text, callback, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        
        frame = QFrame()
        frame.setStyleSheet("QFrame { background-color: #1a1a1a; border: 1px solid #444; border-radius: 8px; }")
        flay = QVBoxLayout(frame)
        flay.setSpacing(10)
        
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #ccc; font-size: 12px; border: none;")
        lbl.setWordWrap(True)
        flay.addWidget(lbl)
        
        btn = QPushButton(btn_text)
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setStyleSheet("""
            QPushButton {
                background-color: #222; border: 1px solid #555; color: #fff; border-radius: 4px; padding: 6px; font-size: 12px;
            }
            QPushButton:hover {
                background-color: #333; border: 1px solid #777;
            }
        """)
        btn.clicked.connect(self.close)
        btn.clicked.connect(callback)
        flay.addWidget(btn)
        
        lay.addWidget(frame)

class TutorialControls(QFrame):
    def __init__(self, parent, close_cb, pdf_cb):
        super().__init__(parent)
        self.setStyleSheet("QFrame { background: #1a1a1a; border: 1px solid #00e5ff; border-radius: 8px; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(15, 15, 15, 15)
        lay.setSpacing(10)
        
        btn_pdf = QPushButton("📄 Інструкція (PDF)")
        btn_pdf.setStyleSheet("QPushButton { background: #222; border: 1px solid #555; padding: 10px; border-radius: 4px; color: #fff; font-size: 13px; font-weight: bold; } QPushButton:hover { background: #00e5ff; color: #000; }")
        btn_pdf.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_pdf.clicked.connect(pdf_cb)
        lay.addWidget(btn_pdf)
        
        btn_close = QPushButton("✖ Закрити підказки")
        btn_close.setStyleSheet("QPushButton { background: transparent; border: 1px solid #ff3366; color: #ff3366; padding: 10px; border-radius: 4px; font-size: 13px; font-weight: bold;} QPushButton:hover { background: #ff3366; color: #fff; }")
        btn_close.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_close.clicked.connect(close_cb)
        lay.addWidget(btn_close)

class NativeTutorialOverlay(QWidget):
    def __init__(self, main_app):
        super().__init__(main_app.centralWidget())
        self.main_app = main_app
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.resize(main_app.centralWidget().size())
        
        self.alpha = 50
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(2000) 
        self.anim.setKeyValueAt(0.0, 50)
        self.anim.setKeyValueAt(0.5, 255)
        self.anim.setKeyValueAt(1.0, 50)
        self.anim.setLoopCount(-1)
        self.anim.valueChanged.connect(self.update_alpha)
        self.anim.start()
        
    def update_alpha(self, val):
        self.alpha = val
        self.update()
        
    def paintEvent(self, e):
        if not self.parent(): return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        glow_color = QColor(0, 229, 255, self.alpha)
        pen = QPen(glow_color, 2, Qt.PenStyle.SolidLine)
        p.setPen(pen)
        p.setBrush(QColor(0, 229, 255, int(self.alpha * 0.1)))
        
        # 1. Підсвітка блоку дій ліворуч (крок 2)
        st = self.main_app.stacked
        if st:
            st_pos = st.mapTo(self.parent(), QPoint(0, 0))
            st_rect = QRect(st_pos, st.size())
            p.drawRoundedRect(st_rect, 8, 8)
            p.setPen(QColor(255, 255, 255))
            p.setFont(QFont("Arial", 11, QFont.Weight.Bold))
            
            text_x = st_rect.right() + 25
            text_y = st_rect.center().y()
            p.drawText(QRect(text_x, text_y - 20, 300, 40), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "⬅ 2. Оберіть бажану \nдію зі списку")
            p.setPen(pen)
            
        # 2. Підсвітка кнопки "ПРИЗНАЧИТИ" (крок 3)
        btn_ass = self.main_app.btn_assign
        if btn_ass:
            ass_pos = btn_ass.mapTo(self.parent(), QPoint(0, 0))
            ass_rect = QRect(ass_pos, btn_ass.size())
            p.drawRoundedRect(ass_rect, 5, 5)
            p.setPen(QColor(255, 255, 255))
            p.setFont(QFont("Arial", 11, QFont.Weight.Bold))
            
            assign_text_rect = QRect(ass_rect.right() - 250, ass_rect.top() - 30, 250, 25)
            p.drawText(assign_text_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom, "3. Збережіть призначення ⬇")
            p.setPen(pen)
            
        # 3. Підсвітка кнопок та комбінованих енкодерів
        for bid, btn in self.main_app.ui_pad_btns.items():
            b_pos = btn.mapTo(self.parent(), QPoint(0, 0))
            b_rect = QRect(b_pos, btn.size())
            
            if isinstance(btn, EncoderCompoundWidget) or bid.startswith("ENC_"):
                p.setPen(pen)
                p.setBrush(QColor(0, 229, 255, int(self.alpha * 0.1)))
                p.drawEllipse(b_rect)
                
                # Підсвітка внутрішнього кола енкодера
                cx, cy = b_rect.center().x(), b_rect.center().y()
                p.drawEllipse(QPoint(cx, cy), 18, 18)
                
                if bid == "ENC_1":
                    p.setPen(QColor(255, 255, 255))
                    p.setFont(QFont("Arial", 10, QFont.Weight.Bold))
                    
                    tut_text = (
                        "⬅ Або оберіть частину енкодера:\n"
                        "   • Верхня дуга — натискання (SW)\n"
                        "   • Бокові сектори — дії на обертання\n"
                        "   • Центр — крутилка"
                    )
                    
                    # Збільшений прямокутник для комфортного розміщення тексту
                    p.drawText(
                        QRect(b_rect.right() + 15, b_rect.center().y() - 42, 340, 85), 
                        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, 
                        tut_text
                    )
                    p.setPen(pen)
            else:
                p.setPen(pen)
                p.setBrush(QColor(0, 229, 255, int(self.alpha * 0.1)))
                p.drawRoundedRect(b_rect, 15, 15)
                if bid == "BTN_2":
                    p.setPen(QColor(255, 255, 255))
                    p.setFont(QFont("Arial", 11, QFont.Weight.Bold))
                    p.drawText(QRect(b_rect.left() - 55, b_rect.top() - 30, 200, 25), Qt.AlignmentFlag.AlignCenter, "1. Виберіть кнопку ⬇")
                    p.setPen(pen)

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Налаштування")
        self.setFixedSize(380, 225)
        self.setStyleSheet(f"background-color: {BG_MAIN}; color: {TEXT_MAIN};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        lbl = QLabel("Налаштування програми")
        lbl.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lbl)

        checkbox_style = f"""
            QCheckBox {{
                font-size: 13px;
                color: {TEXT_MAIN};
                spacing: 10px;
            }}
            QCheckBox::indicator {{
                width: 20px;
                height: 20px;
                border-radius: 5px;
                border: 1px solid #444;
                background-color: #141414;
            }}
            QCheckBox::indicator:hover {{
                border: 1px solid {ACCENT};
                background-color: #1a1a1a;
            }}
            QCheckBox::indicator:checked {{
                background-color: {ACCENT};
                border: 1px solid {ACCENT};
                image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%230a0a0a' stroke-width='3.5' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='20 6 9 17 4 12'/%3E%3C/svg%3E");
            }}
        """

        self.cb_autostart = QCheckBox("Запускати разом з Windows")
        self.cb_autostart.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.cb_autostart.setChecked(self.check_autostart())
        self.cb_autostart.clicked.connect(self.toggle_autostart)
        self.cb_autostart.setStyleSheet(checkbox_style)
        layout.addWidget(self.cb_autostart)

        self.cb_auto_prof = QCheckBox("Автоперемикання профілів (.exe)")
        self.cb_auto_prof.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.cb_auto_prof.setChecked(self.parent().config.get("auto_profile_switch", True))
        self.cb_auto_prof.clicked.connect(self.toggle_auto_prof)
        self.cb_auto_prof.setStyleSheet(checkbox_style)
        layout.addWidget(self.cb_auto_prof)

        self.cb_show_osd = QCheckBox("Екранний оверлей (HUD / OSD поверх ігор)")
        self.cb_show_osd.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.cb_show_osd.setChecked(self.parent().config.get("show_osd", True))
        self.cb_show_osd.clicked.connect(self.toggle_osd)
        self.cb_show_osd.setStyleSheet(checkbox_style)
        layout.addWidget(self.cb_show_osd)

        layout.addSpacing(5)

        btn_close = QPushButton("Закрити")
        btn_close.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_close.clicked.connect(self.accept)
        btn_close.setStyleSheet(f"QPushButton {{ background-color: {BG_HOVER}; border: 1px solid #333; padding: 8px; border-radius: 5px; font-weight: bold; }} QPushButton:hover {{ border: 1px solid {ACCENT}; }}")
        layout.addWidget(btn_close)

    def toggle_auto_prof(self):
        self.parent().config["auto_profile_switch"] = self.cb_auto_prof.isChecked()
        self.parent().save_config()

    def toggle_osd(self):
        self.parent().config["show_osd"] = self.cb_show_osd.isChecked()
        self.parent().save_config()

    def check_autostart(self):
        try:
            subprocess.check_output(["schtasks", "/Query", "/TN", "VPT_MacroPad_AutoStart"],
                                    stderr=subprocess.STDOUT, creationflags=0x08000000, timeout=5)
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            return False

    @staticmethod
    def _autostart_command():
        """Команда запуску для Планувальника завдань.
        Раніше при запуску з .py у задачу потрапляв голий python.exe без скрипта."""
        if getattr(sys, "frozen", False):
            return f'"{os.path.abspath(sys.executable)}" --tray'
        argv0 = os.path.abspath(sys.argv[0])
        if argv0.lower().endswith(".exe"):
            return f'"{argv0}" --tray'
        py = os.path.abspath(sys.executable)
        pyw = os.path.join(os.path.dirname(py), "pythonw.exe")
        if os.path.exists(pyw):
            py = pyw
        return f'"{py}" "{argv0}" --tray'

    def toggle_autostart(self):
        enable = self.cb_autostart.isChecked()
        try:
            if enable:
                cmd = [
                    "schtasks", "/Create", "/F",
                    "/TN", "VPT_MacroPad_AutoStart",
                    "/TR", self._autostart_command(),
                    "/SC", "ONLOGON",
                    "/RL", "HIGHEST"
                ]
            else:
                cmd = ["schtasks", "/Delete", "/TN", "VPT_MacroPad_AutoStart", "/F"]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=0x08000000)
        except Exception:
            pass
        self.cb_autostart.setChecked(self.check_autostart())

class AppBindDialog(QDialog):
    def __init__(self, current_bind, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Прив'язка до програми")
        self.setFixedSize(450, 240)
        self.setStyleSheet(f"background-color: {BG_MAIN}; color: {TEXT_MAIN};")
        
        layout = QVBoxLayout(self)
        
        lbl1 = QLabel("Введіть назву процесу (напр. photoshop.exe):\nАбо залиште порожнім, щоб видалити прив'язку.")
        lbl1.setFont(QFont("Arial", 11))
        layout.addWidget(lbl1)
        
        self.inp_exe = QLineEdit(current_bind)
        self.inp_exe.setStyleSheet(f"QLineEdit {{ background: #111; color: #fff; border: 1px solid #444; border-radius: 4px; padding: 8px; font-size: 13px; }} QLineEdit:focus {{ border: 1px solid {ACCENT}; }}")
        layout.addWidget(self.inp_exe)
        
        lbl2 = QLabel("Або виберіть зі списку відкритих програм:")
        lbl2.setStyleSheet("margin-top: 10px; color: #aaa;")
        layout.addWidget(lbl2)
        
        self.combo = QComboBox()
        self.combo.setStyleSheet(f"QComboBox {{ background: #111; color: #fff; border: 1px solid #444; border-radius: 4px; padding: 8px; font-size: 13px; }} QComboBox:hover {{ border: 1px solid {ACCENT}; }}")
        self.combo.addItem("--- Виберіть відкриту програму ---", "")
        
        # Заповнюємо список активними програмами
        for exe, title in self.get_running_apps():
            display_text = f"[{exe}]  {title[:40]}..." if len(title) > 40 else f"[{exe}]  {title}"
            self.combo.addItem(display_text, exe)
            
        self.combo.currentIndexChanged.connect(self.on_combo_change)
        layout.addWidget(self.combo)
        
        layout.addStretch()
        
        h_lay = QHBoxLayout()
        btn_save = QPushButton("Зберегти")
        btn_save.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_save.setStyleSheet(f"QPushButton {{ background-color: {BG_HOVER}; border: 1px solid #333; padding: 8px; border-radius: 5px; font-weight: bold; }} QPushButton:hover {{ border: 1px solid {ACCENT}; color: {ACCENT}; }}")
        btn_save.clicked.connect(self.accept)
        
        btn_cancel = QPushButton("Скасувати")
        btn_cancel.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_cancel.setStyleSheet(f"QPushButton {{ background-color: transparent; border: 1px solid #555; padding: 8px; border-radius: 5px; }} QPushButton:hover {{ background-color: #333; }}")
        btn_cancel.clicked.connect(self.reject)
        
        h_lay.addWidget(btn_save)
        h_lay.addWidget(btn_cancel)
        layout.addLayout(h_lay)

    def on_combo_change(self, index):
        exe = self.combo.itemData(index)
        if exe:
            self.inp_exe.setText(exe)

    def get_exe_name(self):
        return self.inp_exe.text().strip().lower()

    def get_running_apps(self):
        import ctypes.wintypes as wt
        from utils import get_process_exe_name
        user32 = ctypes.windll.user32

        apps = []
        seen = set()
        own_pid = os.getpid()
        # Ігноруємо системні вікна Windows, які висять у фоні
        ignore = {"applicationframehost.exe", "shellexperiencehost.exe", "systemsettings.exe",
                  "textinputhost.exe", "searchhost.exe", "explorer.exe"}

        EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

        def foreach_window(hwnd, lParam):
            try:
                if user32.IsWindowVisible(hwnd):
                    length = user32.GetWindowTextLengthW(hwnd)
                    if length > 0:
                        pid = wt.DWORD()
                        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                        if pid.value and pid.value != own_pid:
                            # PROCESS_QUERY_LIMITED_INFORMATION: бачимо й програми, запущені від адміністратора
                            exe_name = get_process_exe_name(pid.value)
                            if exe_name and exe_name not in ignore and exe_name not in seen:
                                seen.add(exe_name)
                                title_buf = ctypes.create_unicode_buffer(length + 1)
                                user32.GetWindowTextW(hwnd, title_buf, length + 1)
                                apps.append((exe_name, title_buf.value))
            except Exception:
                pass
            return True

        try:
            user32.EnumWindows(EnumWindowsProc(foreach_window), 0)
        except Exception:
            pass
        return sorted(apps, key=lambda x: x[0])
