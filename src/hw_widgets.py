# Neo8085 - 8085 Microprocessor Simulator
# Copyright (C) 2026 Shahibur Rahaman
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
Widgets for the side-panel tabs: sections in the style of the main window,
glowing LEDs, animated switches, port pin cells and value chips, and the
common page layout every tab uses.

Everything is drawn with vector painting (like SVG), so the widgets are
sharp at any size and on high-DPI screens, and need no image files.
"""

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QVariantAnimation, QEasingCurve
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QSplitterHandle,
    QVBoxLayout,
    QWidget,
)

# Material palette (primary matches the rest of Neo8085)
PRIMARY = "#5C2D91"
PRIMARY_LIGHT = "#F3ECFA"
TEAL = "#00897B"  # inputs you control
RED = "#E53935"  # data outputs
AMBER = "#FFA000"  # control / handshake outputs
GREEN = "#43A047"
TEXT = "#212121"
TEXT_2 = "#6B6B6B"
OUTLINE = "#DDDDDD"
BORDER = "#DDDDDD"  # the border colour of the boxes in the main window
SURFACE = "#FFFFFF"
PAGE = "#F0F0F0"  # the main window background
PAGE_MARGIN = 6
DISABLED = "#BDBDBD"


# Bottom panes: text uses the font of the section headings, hex values a
# fixed-width font so digits and columns line up
PANEL_FONT = "Segoe UI"
HEX_FONT = "Consolas"


def ui_font(size=8, bold=False, mono=False):
    """Font for the bottom panes: Segoe UI, or Consolas (mono) for hex values."""
    font = QFont(HEX_FONT if mono else PANEL_FONT, size)
    font.setBold(bold)
    return font


def _tint(color, amount):
    """The colour mixed into white (amount 0 = white, 1 = the colour): Material tonal surfaces."""
    c = QColor(color)
    mix = lambda channel: round(255 + (channel - 255) * amount)
    return QColor(mix(c.red()), mix(c.green()), mix(c.blue())).name()


def _off_color(color):
    """The unlit look of an LED of the given colour."""
    c = QColor(color)
    h, s, v, _ = c.getHsv()
    return QColor.fromHsv(max(h, 0), int(s * 0.55), int(v * 0.32))


# ----------------------------------------------------------------------
# Containers and text
# ----------------------------------------------------------------------


class ElidedLabel(QLabel):
    """A one-line label that shrinks with its container, ending in '...' when cut short."""

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._full = text
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(0)
        super().setText(text)

    def setText(self, text):
        self._full = text
        self._elide()

    def text(self):
        return self._full

    def setFont(self, font):
        super().setFont(font)
        self._elide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def _elide(self):
        metrics = QFontMetrics(self.font())
        super().setText(metrics.elidedText(self._full, Qt.TextElideMode.ElideRight, max(self.width(), 0)))
        self.setToolTip(self._full if metrics.horizontalAdvance(self._full) > self.width() else "")


class Card(QFrame):
    """
    A section in the style of the rest of Neo8085: a compact purple header
    bar (title and optional subtitle) above a white body with a light border.
    `header` is a row at the top of the body for controls aligned to the
    right; `body` holds the section's content.
    """

    def __init__(self, title="", subtitle="", parent=None, square=True):
        super().__init__(parent)
        self.setObjectName("card")
        self.setStyleSheet(f"#card {{ background: {SURFACE}; border: 1px solid {BORDER}; }}")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)
        self.title = QLabel(title.upper())
        self.subtitle = ElidedLabel(subtitle)
        if title:
            bar = QWidget()
            bar.setObjectName("cardBar")
            bar.setStyleSheet(f"#cardBar {{ background: {PRIMARY}; }}")
            row = QHBoxLayout(bar)
            row.setContentsMargins(10, 4, 10, 4)
            row.setSpacing(8)
            self.title.setFont(ui_font(9, True))
            self.title.setStyleSheet("color: white; background: transparent;")
            self.subtitle.setFont(ui_font(8))
            self.subtitle.setStyleSheet("color: #DCCBF0; background: transparent;")
            row.addWidget(self.title)
            row.addWidget(self.subtitle, 1)
            self.bar_actions = QHBoxLayout()  # small controls on the right of the bar
            self.bar_actions.setSpacing(4)
            row.addLayout(self.bar_actions)
            outer.addWidget(bar)
        else:
            self.bar_actions = None
        content = QVBoxLayout()
        content.setContentsMargins(10, 8, 10, 10)
        content.setSpacing(6)
        self.header = QHBoxLayout()
        self.header.setSpacing(6)
        self.header.addStretch(1)
        content.addLayout(self.header)
        self.body = QVBoxLayout()
        self.body.setSpacing(6)
        content.addLayout(self.body, 1)
        outer.addLayout(content, 1)


class GripHandle(QSplitterHandle):
    """
    A pane divider that shows it can be dragged: a row of grip dots in the
    middle, light purple on hover and purple while dragging. Double-clicking
    it asks the splitter to restore the panes on both sides.
    """

    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self.setMouseTracking(True)
        self._hover = False
        self._pressed = False
        self.setToolTip(parent.handle_tooltip)

    def enterEvent(self, event):
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        self._pressed = True
        self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._pressed = False
        self.update()
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        splitter = self.splitter()
        index = splitter.indexOf(self)
        if splitter.on_double_click is not None:
            splitter.on_double_click(splitter, index)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._pressed:
            background, dots = QColor(PRIMARY), QColor("white")
        elif self._hover:
            background, dots = QColor("#C9B6E2"), QColor(PRIMARY)
        else:
            background, dots = QColor("#E2E2E2"), QColor("#8C8C8C")
        painter.fillRect(self.rect(), background)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(dots)
        center = QPointF(self.width() / 2, self.height() / 2)
        spacing = 5
        for i in range(-2, 3):  # five dots along the divider
            if self.orientation() == Qt.Orientation.Horizontal:  # vertical divider
                point = QPointF(center.x(), center.y() + i * spacing)
            else:
                point = QPointF(center.x() + i * spacing, center.y())
            painter.drawEllipse(point, 1.3, 1.3)
        painter.end()


class GripSplitter(QSplitter):
    """QSplitter with GripHandle dividers (see GripHandle)."""

    def __init__(self, orientation=Qt.Orientation.Horizontal, tooltip="", parent=None):
        super().__init__(orientation, parent)
        self.handle_tooltip = tooltip
        self.on_double_click = None  # callable(splitter, handle index)
        self.setHandleWidth(7)

    def createHandle(self):
        return GripHandle(self.orientation(), self)


def scroll_page(widget):
    """
    Gives a side-panel tab the common page layout: the app background,
    6 px margins and spacing, and scrolling when the tab is short.
    Returns the layout to add sections (Cards) to.
    """
    outer = QVBoxLayout(widget)
    outer.setContentsMargins(0, 0, 0, 0)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setStyleSheet(f"QScrollArea {{ background: {PAGE}; border: none; }}")
    body = QWidget()
    body.setObjectName("page")
    body.setStyleSheet(f"#page {{ background: {PAGE}; }}")
    layout = QVBoxLayout(body)
    layout.setContentsMargins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)
    layout.setSpacing(PAGE_MARGIN)
    scroll.setWidget(body)
    outer.addWidget(scroll)
    return layout


def plain_page(widget):
    """The common page layout without scrolling (for tabs whose content stretches)."""
    widget.setObjectName("page")
    widget.setStyleSheet(f"#page {{ background: {PAGE}; }}")
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN, PAGE_MARGIN)
    layout.setSpacing(PAGE_MARGIN)
    return layout


class Chip(QLabel):
    """Small tinted label for a value such as a port address or a mode (square unless square=False)."""

    STYLES = {
        "primary": (PRIMARY_LIGHT, PRIMARY),
        "teal": ("#E0F2F1", "#00695C"),
        "red": ("#FFEBEE", "#C62828"),
        "amber": ("#FFF8E1", "#B26A00"),
        "grey": ("#F1F1F1", "#555555"),
    }

    def __init__(self, text="", kind="primary", mono=True, parent=None, square=True):
        super().__init__(text, parent)
        self.radius = 0 if square else 9
        self.setFont(ui_font(8, True, mono))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedHeight(19)
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.kind = None
        self.set_kind(kind)

    def set_kind(self, kind):
        if kind == self.kind:
            return
        self.kind = kind
        background, color = self.STYLES[kind]
        self.setStyleSheet(
            f"QLabel {{ background: {background}; color: {color}; border-radius: {self.radius}px; padding: 1px 8px; }}"
        )


def caption(text, color=TEXT_2, size=8, bold=False):
    label = QLabel(text)
    label.setFont(ui_font(size, bold))
    label.setStyleSheet(f"color: {color}; background: transparent;")
    return label


def set_text(widget, text):
    """Sets a widget's text only when it changed. Returns True if it did."""
    if widget.text() == text:
        return False
    widget.setText(text)
    return True


# ----------------------------------------------------------------------
# Form controls in the same style
# ----------------------------------------------------------------------

FIELD_STYLE = (
    f"QLineEdit {{ background: white; border: 1px solid {OUTLINE}; border-radius: RADIUSpx; padding: 2px 6px; color: {TEXT}; }}"
    f" QLineEdit:hover {{ border-color: #B9A3D6; }}"
    f" QLineEdit:focus {{ border: 1px solid {PRIMARY}; }}"
)

COMBO_STYLE = (
    f"QComboBox {{ background: white; border: 1px solid {OUTLINE}; border-radius: RADIUSpx; padding: 2px 8px; color: {TEXT}; }}"
    f" QComboBox:hover {{ border-color: #B9A3D6; }}"
    f" QComboBox:focus {{ border-color: {PRIMARY}; }}"
    f" QComboBox::drop-down {{ border: none; width: 18px; }}"
    f" QComboBox QAbstractItemView {{ background: white; border: 1px solid {OUTLINE}; outline: 0;"
    f" selection-background-color: {PRIMARY}; selection-color: white; }}"
)


def field(text="", width=58, placeholder="", square=True):
    edit = QLineEdit(text)
    edit.setFont(ui_font(9, mono=True))
    edit.setPlaceholderText(placeholder)
    edit.setMaximumWidth(width)
    edit.setStyleSheet(FIELD_STYLE.replace("RADIUS", "0" if square else "6"))
    return edit


def combo(square=True):
    box = QComboBox()
    box.setFont(ui_font(8))
    box.setStyleSheet(COMBO_STYLE.replace("RADIUS", "0" if square else "6"))
    return box


class MaterialButton(QPushButton):
    """Material 'tonal' button (filled with a light tint, primary text)."""

    def __init__(self, text, color=PRIMARY, filled=False, parent=None, square=True):
        super().__init__(text, parent)
        self.setFont(ui_font(8, True))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(26)
        light = _tint(color, 0.14) if not filled else color
        hover = _tint(color, 0.24) if not filled else QColor(color).lighter(115).name()
        pressed = _tint(color, 0.34) if not filled else QColor(color).darker(115).name()
        text_color = "white" if filled else QColor(color).darker(115).name()
        self.setStyleSheet(
            f"QPushButton {{ background: {light}; color: {text_color}; border: none; border-radius: {0 if square else 13}px;"
            f" padding: 3px 12px; }}"
            f" QPushButton:hover {{ background: {hover}; }}"
            f" QPushButton:pressed {{ background: {pressed}; }}"
            f" QPushButton:disabled {{ background: #F2F2F2; color: {DISABLED}; }}"
        )


# ----------------------------------------------------------------------
# LED
# ----------------------------------------------------------------------


class Led(QWidget):
    """A round LED with a glow when lit, and an optional label below it."""

    def __init__(self, label="", color=RED, diameter=18, parent=None):
        super().__init__(parent)
        self._on = False
        self._label = label
        self._color = QColor(color)
        self.diameter = diameter
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def sizeHint(self):
        label_height = 14 if self._label else 0
        label_width = QFontMetrics(ui_font(7, True)).horizontalAdvance(self._label) + 6 if self._label else 0
        return QSize(max(self.diameter + 10, 26, label_width), self.diameter + 8 + label_height)

    def minimumSizeHint(self):
        return self.sizeHint()

    # API -------------------------------------------------------------
    def set_on(self, on):
        on = bool(on)
        if on != self._on:
            self._on = on
            self.update()

    def is_on(self):
        return self._on

    def set_color(self, color):
        color = QColor(color)
        if color != self._color:
            self._color = color
            self.update()

    def text(self):
        return self._label

    def setText(self, text):
        if text != self._label:
            self._label = text
            self.updateGeometry()
            self.update()

    # Painting ---------------------------------------------------------
    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        d = self.diameter
        center = QPointF(self.width() / 2, 4 + d / 2)
        color = self._color if self.isEnabled() else QColor(DISABLED)
        if self._on and self.isEnabled():
            glow = QRadialGradient(center, d * 0.95)
            halo = QColor(color)
            halo.setAlpha(110)
            glow.setColorAt(0.0, halo)
            halo.setAlpha(0)
            glow.setColorAt(1.0, halo)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(glow))
            painter.drawEllipse(center, d * 0.95, d * 0.95)
            body = QRadialGradient(center - QPointF(d * 0.15, d * 0.18), d * 0.62)
            body.setColorAt(0.0, color.lighter(165))
            body.setColorAt(0.55, color)
            body.setColorAt(1.0, color.darker(125))
        else:
            off = _off_color(color)
            body = QRadialGradient(center - QPointF(d * 0.15, d * 0.18), d * 0.62)
            body.setColorAt(0.0, off.lighter(170))
            body.setColorAt(1.0, off)
        painter.setBrush(QBrush(body))
        painter.setPen(QPen(QColor(0, 0, 0, 70), 1))
        painter.drawEllipse(center, d / 2, d / 2)
        # Specular highlight
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 170 if self._on else 70))
        painter.drawEllipse(center - QPointF(d * 0.16, d * 0.18), d * 0.16, d * 0.11)
        if self._label:
            painter.setFont(ui_font(7, self._on))
            painter.setPen(QColor(TEXT if self._on else TEXT_2))
            painter.drawText(QRectF(0, 6 + d, self.width(), 14), Qt.AlignmentFlag.AlignHCenter, self._label)
        painter.end()


# ----------------------------------------------------------------------
# Switch
# ----------------------------------------------------------------------


class ToggleSwitch(QAbstractButton):
    """
    Material switch (a checkable button). Horizontal with its text on the
    right, or vertical (thumb up = 1) with its text below, like one lever of
    a DIP switch.
    """

    def __init__(self, text="", color=TEAL, vertical=False, parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.color = QColor(color)
        self.vertical = vertical
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(lambda _v: self.update())
        self.toggled.connect(self._animate)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def _animate(self, checked):
        self._anim.stop()
        self._anim.setStartValue(0.0 if checked else 1.0)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def _position(self):
        if self._anim.state() == QVariantAnimation.State.Running:
            return float(self._anim.currentValue())
        return 1.0 if self.isChecked() else 0.0

    def sizeHint(self):
        metrics = QFontMetrics(ui_font(8))
        if self.vertical:
            return QSize(max(28, metrics.horizontalAdvance(self.text()) + 6), 36 + (14 if self.text() else 0))
        return QSize(40 + (metrics.horizontalAdvance(self.text()) + 8 if self.text() else 0), 24)

    def setText(self, text):
        super().setText(text)
        self.updateGeometry()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        position = self._position()
        enabled = self.isEnabled()
        on_color = self.color if enabled else QColor(DISABLED)
        if self.vertical:
            track = QRectF(self.width() / 2 - 7, 3, 14, 30)
            thumb_center = QPointF(track.center().x(), track.bottom() - 7 - position * (track.height() - 14))
        else:
            track = QRectF(3, self.height() / 2 - 7, 34, 14)
            thumb_center = QPointF(track.left() + 7 + position * (track.width() - 14), track.center().y())
        track_color = QColor(on_color)
        track_color.setAlpha(int(90 * position + 0))
        base = QColor("#BDBDBD") if enabled else QColor("#E0E0E0")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(base)
        painter.drawRoundedRect(track, 7, 7)
        painter.setBrush(track_color)
        painter.drawRoundedRect(track, 7, 7)
        # Thumb with a small shadow
        painter.setBrush(QColor(0, 0, 0, 45))
        painter.drawEllipse(thumb_center + QPointF(0, 1.2), 9.5, 9.5)
        thumb = QColor(on_color) if position > 0.5 else QColor("#FAFAFA")
        if not enabled and position <= 0.5:
            thumb = QColor("#EEEEEE")
        painter.setBrush(thumb)
        painter.setPen(QPen(QColor(0, 0, 0, 30), 1))
        painter.drawEllipse(thumb_center, 9, 9)
        if self.underMouse() and enabled:
            ripple = QColor(on_color)
            ripple.setAlpha(35)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(ripple)
            painter.drawEllipse(thumb_center, 14, 14)
        if self.text():
            painter.setFont(ui_font(8, self.isChecked()))
            painter.setPen(QColor(TEXT if enabled else DISABLED))
            if self.vertical:
                painter.drawText(QRectF(0, 36, self.width(), 14), Qt.AlignmentFlag.AlignHCenter, self.text())
            else:
                painter.drawText(QRectF(44, 0, self.width() - 44, self.height()), Qt.AlignmentFlag.AlignVCenter,
                                 self.text())
        painter.end()

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()


# ----------------------------------------------------------------------
# Port pin (8255)
# ----------------------------------------------------------------------


class PinCell(QAbstractButton):
    """
    One port pin: a switch you can flip when the pin is an input, an LED when
    the chip drives it (red for data, amber for handshake/control outputs).
    The label above shows the bit number or the pin's handshake role.
    """

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setCheckable(True)
        self.driven = False
        self.control = False
        self._state = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(36, 58)

    def show_state(self, text, level, driven, tip, control=False):
        state = (text, bool(level), bool(driven), tip, control)
        if state == self._state:
            return  # nothing changed
        self._state = state
        self.driven = bool(driven)
        self.control = control
        self.setText(text)
        self.setToolTip(tip)
        self.blockSignals(True)
        self.setChecked(bool(level))
        self.blockSignals(False)
        self.setEnabled(not driven)
        self.setCursor(Qt.CursorShape.ArrowCursor if driven else Qt.CursorShape.PointingHandCursor)
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        level = self.isChecked()
        w = self.width()
        # Label (bit number or role)
        painter.setFont(ui_font(7, True))
        painter.setPen(QColor(AMBER if self.control and self.driven else (TEXT if level else TEXT_2)))
        painter.drawText(QRectF(0, 0, w, 13), Qt.AlignmentFlag.AlignHCenter, self.text())
        if self.driven:
            color = QColor(AMBER if self.control else RED)
            center = QPointF(w / 2, 31)
            d = 16
            if level:
                glow = QRadialGradient(center, d)
                halo = QColor(color)
                halo.setAlpha(100)
                glow.setColorAt(0, halo)
                halo.setAlpha(0)
                glow.setColorAt(1, halo)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(glow))
                painter.drawEllipse(center, d, d)
                body = QRadialGradient(center - QPointF(3, 3), d * 0.7)
                body.setColorAt(0, color.lighter(160))
                body.setColorAt(1, color.darker(120))
            else:
                off = _off_color(color)
                body = QRadialGradient(center - QPointF(3, 3), d * 0.7)
                body.setColorAt(0, off.lighter(170))
                body.setColorAt(1, off)
            painter.setBrush(QBrush(body))
            painter.setPen(QPen(QColor(0, 0, 0, 70), 1))
            painter.drawEllipse(center, d / 2, d / 2)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 160 if level else 60))
            painter.drawEllipse(center - QPointF(2.5, 3), 2.6, 1.8)
        else:
            enabled = self.isEnabled()
            color = QColor(TEAL if enabled else DISABLED)
            track = QRectF(w / 2 - 6, 16, 12, 28)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#C8C8C8"))
            painter.drawRoundedRect(track, 6, 6)
            if level:
                tint = QColor(color)
                tint.setAlpha(110)
                painter.setBrush(tint)
                painter.drawRoundedRect(track, 6, 6)
            y = track.top() + 6 if level else track.bottom() - 6
            painter.setBrush(QColor(0, 0, 0, 45))
            painter.drawEllipse(QPointF(w / 2, y + 1), 7.5, 7.5)
            painter.setBrush(color if level else QColor("#FAFAFA"))
            painter.setPen(QPen(QColor(0, 0, 0, 35), 1))
            painter.drawEllipse(QPointF(w / 2, y), 7, 7)
        # Level digit at the bottom
        painter.setFont(ui_font(7))
        painter.setPen(QColor(TEXT_2))
        painter.drawText(QRectF(0, 46, w, 12), Qt.AlignmentFlag.AlignHCenter, "1" if level else "0")
        painter.end()
