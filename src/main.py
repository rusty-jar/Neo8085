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

# Neo8085 application: main window, run loop and hardware panels.

import json
import os
import sys
from collections import Counter

def resource_path(relative_path):
    """Path of a bundled data file, both from source and in the PyInstaller build."""
    if hasattr(sys, '_MEIPASS'):
        # PyInstaller unpacks bundled files into sys._MEIPASS
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath('.'), relative_path)

from PySide6.QtCore import (
    QDateTime,
    QSettings,
    QElapsedTimer,
    QPointF,
    QRect,
    QRegularExpression,
    QSize,
    QTimer,
    Qt,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QFontMetrics,
    QIcon,
    QKeySequence,
    QPainter,
    QPixmap,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
    QTextFormat,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QScrollArea,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListView,
    QMenu,
    QMenuBar,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplashScreen,
    QStyle,
    QStyledItemDelegate,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from assembler import Assembler8085
from bus_view import BusCyclePanel
from examples import EXAMPLES
from intel_hex import IntelHexError, hex_to_source, parse_intel_hex, to_intel_hex
from listing import SOURCE_COLUMN, build_listing
from listing_view import ListingWindow, print_text
from peripheral_view import PITPanel, PPIPanel
from peripherals import PeripheralBus
import hw_widgets as hw
from hw_widgets import Card
from processor import Processor8085
from version import version_string, display_version

# Every run mode is driven by a CPU clock locked to wall-clock time: the number
# of T-states executed always equals elapsed time x clock frequency (also while
# the CPU waits in HALT). The modes only differ in the clock frequency.
# Real-Time: 3.072 MHz, the clock of the classic 8085 trainer kits (6.144 MHz
# crystal divided by two inside the 8085).
CPU_CLOCK_HZ = 3_072_000
# Run (F5): slow-motion clock - every instruction is highlighted and logged and
# takes as long as its T-states say (4 T = 40 ms, 18 T = 180 ms)
RUN_CLOCK_HZ = 100
# Run without highlighting
FAST_CLOCK_HZ = 2_000


# Real-Time clock presets: slow-motion rates and the clocks of real 8085 parts
CLOCK_PRESETS = (
    ("1 Hz", 1),
    ("10 Hz", 10),
    ("100 Hz", 100),
    ("1 kHz", 1_000),
    ("10 kHz", 10_000),
    ("100 kHz", 100_000),
    ("1 MHz", 1_000_000),
    ("3 MHz (8085A)", 3_000_000),
    ("3.072 MHz (trainer kit)", 3_072_000),
    ("5 MHz (8085AH-2)", 5_000_000),
    ("6 MHz (8085AH-1)", 6_000_000),
)
MIN_CLOCK_HZ = 1
MAX_CLOCK_HZ = 10_000_000
# At or below this clock every instruction is highlighted and logged
VISUAL_CLOCK_LIMIT_HZ = 200
# Hex values in log messages: 3EH, 2050H, 0FFH, an address before ':' (2000:),
# and 8-bit binary values such as 00110100B
import re as _re  # noqa: E402

_HEX_TOKEN_RE = _re.compile(r"(?<![\w])(?:[0-9A-F]+H|[0-9A-F]{4}(?=:)|[01]{8}B)(?![\w])")


def _hex_span(match):
    return f"<span style='font-family:Consolas'>{match.group(0)}</span>"


# Execution log: lines shown in the widget, and entries kept in memory
LOG_VISIBLE_ENTRIES = 100
LOG_HISTORY_ENTRIES = 20000
# In fast runs, interrupts are logged one by one up to this many, then summarised once a second
INTERRUPT_LOG_DETAIL = 5


def format_frequency(hz):
    if hz >= 1_000_000:
        return f"{hz / 1e6:.4g} MHz"
    if hz >= 1_000:
        return f"{hz / 1e3:.4g} kHz"
    return f"{hz:g} Hz"


def parse_frequency(text):
    """Parses '3.072 MHz', '250 kHz', '100hz' or '1000' (Hz) into an integer frequency."""
    import re

    match = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(hz|khz|mhz)?\b", text.strip(), re.IGNORECASE)
    if not match:
        raise ValueError(f"Not a frequency: {text.strip()}")
    unit = (match.group(2) or "hz").lower()
    hz = round(float(match.group(1)) * {"hz": 1, "khz": 1_000, "mhz": 1_000_000}[unit])
    if not MIN_CLOCK_HZ <= hz <= MAX_CLOCK_HZ:
        raise ValueError(
            f"Clock must be between {format_frequency(MIN_CLOCK_HZ)} and {format_frequency(MAX_CLOCK_HZ)}"
        )
    return hz

class ZoomMixin:
    """Zoom In/Out/Reset for a widget's font; font_point_size is the size Reset Zoom restores."""

    def __init__(self, *args, **kwargs):
        font_point_size = kwargs["font_point_size"]
        del kwargs["font_point_size"]
        super(ZoomMixin, self).__init__(*args, **kwargs)
        self.font_point_size = font_point_size

    def zoom_in(self):
        current_size = self.font().pointSize()
        self.setFont(QFont(self.font().family(), current_size + 1))
        self.set_fixed_height()

    def zoom_out(self):
        current_size = self.font().pointSize()
        if current_size > (4 if self.font_point_size == 12 else (2 if self.font_point_size == 10 else 1)):
            self.setFont(QFont(self.font().family(), current_size - 1))
        self.set_fixed_height()

    def reset_zoom(self):
        self.setFont(QFont(self.font().family(), self.font_point_size))
        self.set_fixed_height()

    def set_fixed_height(self):
        if type(self) == Header:
            fm = QFontMetrics(self.font())
            self.setFixedHeight(fm.height() * 1.43)


class Label(ZoomMixin, QLabel):
    """QLabel that zooms with the rest of the interface."""

    def __init__(self, text: str, font_family="Consolas", font_point_size=12):
        super().__init__(text, font_point_size=font_point_size)
        self.setFont(QFont(font_family, font_point_size))


class Header(Label):
    """Purple section heading (REGISTERS, MEMORY, ...)."""

    def __init__(self, header: str):
        super().__init__(header, font_family="Segoe UI", font_point_size=12)
        self.setFixedHeight(30)
        self.setStyleSheet(
            "background-color: #5C2D91; color: white; border: none;"
        )
        self.setAlignment(Qt.AlignCenter)


class LineEdit(ZoomMixin, QLineEdit):
    """QLineEdit that zooms with the rest of the interface."""

    def __init__(self, place_holder_text: str):
        super().__init__(font_point_size=10)
        self.setFont(QFont("Consolas", 10))
        self.setPlaceholderText(place_holder_text)


class TextEdit(ZoomMixin, QTextEdit):
    """QTextEdit that zooms with the rest of the interface."""

    def __init__(self):
        super().__init__(font_point_size=10)
        self.setFont(QFont("Consolas", 10))


class PushButton(ZoomMixin, QPushButton):
    """QPushButton that zooms with the rest of the interface."""

    def __init__(self, text: str):
        super().__init__(text, font_point_size=10)
        self.setFont(QFont("Segoe UI", 10))


class ClockItemDelegate(QStyledItemDelegate):
    """Draws the clock selector's popup items: flat rows, a grey part name, thin separators."""

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        if index.data(Qt.ItemDataRole.AccessibleDescriptionRole) == "separator":
            return QSize(size.width(), 9)
        return QSize(size.width() + 40, 28)

    def paint(self, painter, option, index):
        painter.save()
        rect = option.rect
        if index.data(Qt.ItemDataRole.AccessibleDescriptionRole) == "separator":
            painter.setPen(QColor("#E6E6E6"))
            y = rect.center().y()
            painter.drawLine(rect.left() + 8, y, rect.right() - 8, y)
            painter.restore()
            return
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        if selected:
            painter.fillRect(rect, QColor(ClockSelector.ACCENT))
        elif hovered:
            painter.fillRect(rect, QColor("#EFE7F8"))
        text = index.data() or ""
        main, _, detail = text.partition(" (")
        font = QFont("Segoe UI", 10)
        painter.setFont(font)
        text_rect = rect.adjusted(12, 0, -12, 0)
        painter.setPen(QColor("white" if selected else "#1E1E1E"))
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, main)
        if detail:
            painter.setPen(QColor("#E8DDF5" if selected else "#8A8A8A"))
            painter.drawText(
                text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, detail.rstrip(")")
            )
        painter.restore()


class ClockSelector(QComboBox):
    """
    Flat, editable frequency selector in the style of the rest of the GUI:
    white field, light border, purple hover/focus accents, a drawn chevron and
    a styled popup list. Presets can be picked, or any frequency typed.
    """

    ACCENT = "#5C2D91"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.setFont(QFont("Segoe UI", 10))
        self.setMinimumHeight(30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.lineEdit().setCursor(Qt.CursorShape.IBeamCursor)
        view = QListView()
        view.setFont(QFont("Segoe UI", 10))
        view.setCursor(Qt.CursorShape.PointingHandCursor)
        view.setMouseTracking(True)
        self.setView(view)
        self.setItemDelegate(ClockItemDelegate(self))
        self.setMaxVisibleItems(14)
        self.setStyleSheet(
            f"""
            QComboBox {{
                background-color: white;
                color: #1E1E1E;
                border: 1px solid #DDDDDD;
                padding: 2px 34px 2px 8px;
            }}
            QComboBox:hover {{ border: 1px solid #A78BCB; }}
            QComboBox:focus, QComboBox:on {{ border: 1px solid {self.ACCENT}; }}
            QComboBox QLineEdit {{
                background: transparent;
                border: none;
                selection-background-color: {self.ACCENT};
                selection-color: white;
            }}
            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 30px;
                border: none;
                border-left: 1px solid #EEEEEE;
                background: transparent;
            }}
            QComboBox::down-arrow {{ image: none; width: 0px; height: 0px; }}
            QComboBox QAbstractItemView {{
                background-color: white;
                border: 1px solid #DDDDDD;
                outline: 0;
                padding: 4px 0px;
            }}
            QComboBox QAbstractItemView::item {{
                min-height: 26px;
                padding: 0px 10px;
                color: #1E1E1E;
            }}
            QComboBox QAbstractItemView::item:hover {{
                background-color: #EFE7F8;
                color: #1E1E1E;
            }}
            QComboBox QAbstractItemView::item:selected {{
                background-color: {self.ACCENT};
                color: white;
            }}
            QComboBox QAbstractItemView::separator {{
                height: 1px;
                background: #E6E6E6;
                margin: 4px 8px;
            }}
        """
        )

    def set_text(self, text):
        """Shows a frequency: selects the matching preset, or just shows the typed text."""
        index = self.findText(text)
        if index >= 0:
            self.setCurrentIndex(index)
        else:
            self.setCurrentText(text)

    def paintEvent(self, event):
        super().paintEvent(event)
        # Chevron in the drop-down area
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        color = QColor(self.ACCENT if (self.underMouse() or self.hasFocus()) else "#6E6E6E")
        pen = painter.pen()
        pen.setColor(color)
        pen.setWidthF(1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        cx = self.width() - 15
        cy = self.height() / 2 + 1
        size = 4.5
        tip = QPointF(cx, cy + size / 2)
        painter.drawLine(QPointF(cx - size, cy - size / 2), tip)
        painter.drawLine(tip, QPointF(cx + size, cy - size / 2))
        painter.end()

    def enterEvent(self, event):
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.update()


class TableWidgetItem(ZoomMixin, QTableWidgetItem):
    """QTableWidgetItem that zooms with the rest of the interface."""

    def __init__(self, text: str):
        super().__init__(text, font_point_size=10)
        self.setFont(QFont("Segoe UI", 10))


# Zooms through its stylesheet, which overrides any font set with setFont()
class MenuBar(QMenuBar):
    """Menu bar styled like the rest of the interface."""
    def __init__(self, parent = None):
        super().__init__(parent)
        self.font_point_size = 10
        self.__style_sheet = """
            QMenuBar {{
                font: {size}pt "Segoe UI";
                background-color: white;
                color: #1E1E1E;
                border-bottom: 1px solid #DDDDDD;
                padding: 0px;
                margin: 0px;
            }}
            QMenuBar::item {{
                background: transparent;
                padding: 4px 10px;
            }}
            QMenuBar::item:selected {{
                background-color: #CBE3F8;
            }}
            QMenu {{
                font: {size}pt "Segoe UI";
                background-color: white;
                border: 1px solid #CCCCCC;
            }}
            QMenu::item:selected {{
                background-color: #CBE3F8;
            }}
        """
        self.setStyleSheet(self.__style_sheet.format(size=self.font_point_size))

    def zoom_in(self):
        current_size = self.font().pointSize()
        self.setStyleSheet(self.__style_sheet.format(size=current_size + 1))

    def zoom_out(self):
        current_size = self.font().pointSize()
        if current_size > 2:
            self.setStyleSheet(self.__style_sheet.format(size=current_size - 1))

    def reset_zoom(self):
        self.setStyleSheet(self.__style_sheet.format(size=self.font_point_size))


class LineNumberArea(ZoomMixin, QWidget):
    """Widget for displaying line numbers and breakpoints in code editor"""

    def __init__(self, editor):
        super().__init__(editor, font_point_size=12)
        self.setFont(QFont("Consolas", 12))
        self.editor = editor
        self.simulator = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self):
        return QSize(self.editor.lineNumberAreaWidth(), 0)

    def paintEvent(self, event):
        self.editor.lineNumberAreaPaintEvent(event)

    def set_simulator(self, simulator):
        """The simulator whose log reports breakpoint errors."""
        self.simulator: Simulator = simulator

    def mousePressEvent(self, event):
        """Handle mouse clicks to toggle breakpoints on valid code lines"""
        y_position = event.position().y()
        block = self.editor.firstVisibleBlock()
        top = (
            self.editor.blockBoundingGeometry(block)
            .translated(self.editor.contentOffset())
            .top()
        )

        while block.isValid():
            block_height = self.editor.blockBoundingRect(block).height()
            bottom = top + block_height

            if top <= y_position <= bottom:
                line_number = block.blockNumber()
                # Breakpoints can only be set on lines with code
                block_text = (
                    self.editor.document().findBlockByNumber(line_number).text().strip()
                )
                if block_text and not block_text.startswith(";"):
                    self.editor.toggleBreakpoint(line_number)
                else:
                    if self.simulator:
                        self.simulator.add_to_log(
                            "Cannot add breakpoint on empty line or comment-only line",
                            "ERROR",
                        )
                break

            block = block.next()
            top = bottom


class AssemblyHighlighter(QSyntaxHighlighter):
    """Syntax highlighter for 8085 assembly language with customized color scheme"""

    def __init__(self, document):
        super().__init__(document)

        self.highlighting_rules = []

        instruction_format = QTextCharFormat()
        instruction_format.setForeground(QColor("#8A2BE2"))  # Purple
        instruction_format.setFontWeight(QFont.Weight.Bold)

        register_format = QTextCharFormat()
        register_format.setForeground(QColor("#2E8B57"))  # Sea Green

        decimal_format = QTextCharFormat()
        decimal_format.setForeground(QColor("#0000FF"))  # Blue

        hex_format = QTextCharFormat()
        hex_format.setForeground(QColor("#1E90FF"))  # Light Blue

        comment_format = QTextCharFormat()
        comment_format.setForeground(QColor("#808080"))  # Gray
        comment_format.setFontItalic(True)

        label_format = QTextCharFormat()
        label_format.setForeground(QColor("#800020"))  # Burgundy

        directive_format = QTextCharFormat()
        directive_format.setForeground(QColor("#FF6600"))  # Orange
        directive_format.setFontWeight(QFont.Weight.Bold)

        # 8085 instruction set
        instructions = [
            "MVI",
            "MOV",
            "LXI",
            "LDA",
            "STA",
            "ADD",
            "ADI",
            "SUB",
            "INR",
            "DCR",
            "JMP",
            "JZ",
            "JNZ",
            "JC",
            "JNC",
            "JP",
            "JM",
            "JPE",
            "JPO",
            "HLT",
            "INX",
            "PUSH",
            "POP",
            "CALL",
            "RET",
            "CPI",
            "DAD",
            "XCHG",
            "LDAX",
            "STAX",
            "LHLD",
            "SHLD",
            "PCHL",
            "SPHL",
            "XTHL",
            "ANA",
            "ANI",
            "ORA",
            "ORI",
            "XRA",
            "XRI",
            "CMA",
            "CMC",
            "STC",
            "RLC",
            "RRC",
            "RAL",
            "RAR",
            "ADC",
            "ACI",
            "SBB",
            "SBI",
            "DAA",
            "DCX",
            "CC",
            "CNC",
            "CZ",
            "CNZ",
            "CP",
            "CM",
            "CPE",
            "CPO",
            "RC",
            "RNC",
            "RZ",
            "RNZ",
            "RP",
            "RM",
            "RPE",
            "RPO",
            "RST",
            "CMP",
            "NOP",
            "SUI",
            "IN",
            "OUT",
            "EI",
            "DI",
            "RIM",
            "SIM",
            # Undocumented 8085 instructions
            "DSUB",
            "ARHL",
            "RDEL",
            "LDHI",
            "LDSI",
            "RSTV",
            "SHLX",
            "LHLX",
            "JNK",
            "JK",
            "JNX5",
            "JX5",
        ]

        # Assembler directives and Intel expression operators
        directives = [
            "DS", "DB", "DW", "ORG", "END", "EQU", "SET",
            "IF", "ELSE", "ENDIF", "MACRO", "ENDM", "LOCAL", "EXITM", "REPT", "IRP", "IRPC",
            "NOT", "AND", "OR", "XOR", "MOD", "SHL", "SHR", "HIGH", "LOW", "NUL",
            "EQ", "NE", "LT", "LE", "GT", "GE",
        ]

        for instruction in instructions:
            pattern = QRegularExpression(
                f"\\b{instruction}\\b", QRegularExpression.PatternOption.CaseInsensitiveOption
            )
            self.highlighting_rules.append((pattern, instruction_format))

        for directive in directives:
            pattern = QRegularExpression(
                f"\\b{directive}\\b", QRegularExpression.PatternOption.CaseInsensitiveOption
            )
            self.highlighting_rules.append((pattern, directive_format))

        registers = ["A", "B", "C", "D", "E", "H", "L", "M", "SP", "PSW"]

        for reg in registers:
            pattern = QRegularExpression(
                f"\\b{reg}\\b", QRegularExpression.PatternOption.CaseInsensitiveOption
            )
            self.highlighting_rules.append((pattern, register_format))

        # Highlighting rules for Intel number formats (must start with a digit)
        hex_pattern = QRegularExpression("\\b[0-9][0-9A-Fa-f]*[Hh]\\b")
        self.highlighting_rules.append((hex_pattern, hex_format))

        other_base_pattern = QRegularExpression("\\b(?:[01]+[Bb]|[0-7]+[OoQq])\\b")
        self.highlighting_rules.append((other_base_pattern, hex_format))

        decimal_pattern = QRegularExpression("\\b[0-9]+[Dd]?\\b")
        self.highlighting_rules.append((decimal_pattern, decimal_format))

        label_pattern = QRegularExpression("^\\s*[A-Za-z_?@][A-Za-z0-9_?@]*\\s*:")
        self.highlighting_rules.append((label_pattern, label_format))

        self.string_format = QTextCharFormat()
        self.string_format.setForeground(QColor("#A31515"))  # Dark red
        self.comment_format = comment_format

    def highlightBlock(self, text):
        """Apply highlighting rules to the code part, then strings and the comment"""
        # Find quoted strings and where the comment starts (';' outside quotes)
        strings = []
        comment_start = len(text)
        in_string = False
        string_start = 0
        for index, ch in enumerate(text):
            if ch == "'":
                if in_string:
                    strings.append((string_start, index + 1))
                else:
                    string_start = index
                in_string = not in_string
            elif ch == ";" and not in_string:
                comment_start = index
                break
        if in_string:
            strings.append((string_start, comment_start))

        code = text[:comment_start]
        for pattern, format in self.highlighting_rules:
            match = pattern.globalMatch(code)
            while match.hasNext():
                match_result = match.next()
                self.setFormat(
                    match_result.capturedStart(), match_result.capturedLength(), format
                )
        for start, end in strings:
            self.setFormat(start, end - start, self.string_format)
        if comment_start < len(text):
            self.setFormat(comment_start, len(text) - comment_start, self.comment_format)


class LineNumberedEditor(ZoomMixin, QPlainTextEdit):
    """Code editor with line numbers, syntax highlighting, and breakpoint support"""

    def __init__(self):
        super().__init__(font_point_size=12)
        self.setPlaceholderText("Enter 8085 Assembly Code Here...")
        self.setFont(QFont("Consolas", 12))

        self.container = QWidget()
        self.container_layout = QVBoxLayout(self.container)
        self.container_layout.setContentsMargins(0, 0, 0, 0)
        self.container_layout.setSpacing(0)

        self.highlighter = AssemblyHighlighter(self.document())

        self.setStyleSheet(
            """
        QPlainTextEdit {
            background-color: white;
            color: #1E1E1E;
            padding: 0px;
            selection-background-color: #0B91FF;
            selection-color: white;
        }
        QScrollBar:vertical {
            border: none;
            background: #F0F0F0;
            width: 10px;
            margin: 0px;
        }
        QScrollBar::handle:vertical {
            background: #AAAAAA;
            min-height: 30px;
        }
        QScrollBar::handle:vertical:hover {
            background: #888888;
        }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0px;
            background: none;
            border: none;
        }
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
            background: none;
        }
        """
        )

        self.status_bar = Label("Ln 1, Col 1", font_family="Segoe UI", font_point_size=9)
        self.status_bar.setStyleSheet(
            "background-color: white; padding: 2px 5px; border: none; solid #DDDDDD;"
        )
        self.status_bar.setAlignment(Qt.AlignmentFlag.AlignLeft)

        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.lineNumberArea = LineNumberArea(self)
        self.breakpoints = set()

        self.blockCountChanged.connect(self.updateLineNumberAreaWidth)
        self.updateRequest.connect(self.updateLineNumberArea)
        self.cursorPositionChanged.connect(self.updateCursorPosition)
        self.cursorPositionChanged.connect(self.highlightCurrentLine)

        self.updateLineNumberAreaWidth(0)
        self.highlightCurrentLine()
        self.updateCursorPosition()

    def updateCursorPosition(self):
        """Update status bar with current cursor position information"""
        cursor = self.textCursor()
        line = cursor.blockNumber() + 1
        col = cursor.columnNumber() + 1
        chars = len(self.toPlainText())

        self.status_bar.setText(f"Ln {line}, Col {col}, Chars: {chars}")

    def lineNumberAreaWidth(self):
        """Calculate required width for line number display area"""
        digits = len(str(self.blockCount())) + (2 if self.lineNumberArea.simulator is None
                                                 or len(self.lineNumberArea.simulator.processor.line_to_address_map) == 0
                                                   else 8)
        return 15 + self.fontMetrics().horizontalAdvance("9") * digits

    def updateLineNumberAreaWidth(self, _):
        self.setViewportMargins(self.lineNumberAreaWidth(), 0, 0, 0)

    def updateLineNumberArea(self, rect, dy):
        """Update line number area on scroll or text changes"""
        if dy:
            self.lineNumberArea.scroll(0, dy)
        else:
            self.lineNumberArea.update(
                0, rect.y(), self.lineNumberArea.width(), rect.height()
            )
        if rect.contains(self.viewport().rect()):
            self.updateLineNumberAreaWidth(0)

    def resizeEvent(self, event):
        """Handle resize events to adjust line number area dimensions"""
        super().resizeEvent(event)
        rect = self.contentsRect()
        self.lineNumberArea.setGeometry(
            QRect(rect.left(), rect.top(), self.lineNumberAreaWidth(), rect.height())
        )

    def lineNumberAreaPaintEvent(self, event):
        """Render line numbers and breakpoint indicators in the line number area"""
        painter = QPainter(self.lineNumberArea)
        painter.fillRect(event.rect(), QColor("#F0F0F0"))

        block = self.firstVisibleBlock()
        blockNumber = block.blockNumber()
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        bottom = top + self.blockBoundingRect(block).height()

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                line_to_address_map = self.lineNumberArea.simulator.processor.line_to_address_map
                line_number = blockNumber + 1
                number = (str(line_number) if len(line_to_address_map) == 0
                          else
                            (f"{line_number}      ") if line_number not in line_to_address_map
                                else f"{line_number} {line_to_address_map[line_number]:04X}H")
                painter.setPen(QColor("#6D6D6D"))

                if blockNumber in self.breakpoints:
                    painter.setPen(QColor("#DA0000"))
                    painter.setBrush(QColor("#DA0000"))
                    painter.drawEllipse(3, int(top) + 4, 8, 8)
                    painter.setPen(QColor("#6D6D6D"))

                painter.drawText(
                    0,
                    int(top),
                    self.lineNumberArea.width() - 5,
                    int(self.fontMetrics().height()),
                    Qt.AlignmentFlag.AlignRight,
                    number,
                )

            block = block.next()
            top = bottom
            bottom = top + self.blockBoundingRect(block).height()
            blockNumber += 1

    def highlightCurrentLine(self):
        """Highlight the line containing the cursor"""
        extraSelections = []
        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(QColor("#E6F2FF"))
        selection.format.setProperty(QTextFormat.FullWidthSelection, True)
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        extraSelections.append(selection)
        self.setExtraSelections(extraSelections)

    def highlightExecutedLine(self, line):
        """Highlight the currently executing line during simulation"""
        cursor = QTextCursor(self.document().findBlockByLineNumber(line))

        # Moving the cursor here must not trigger the current-line highlight
        self.cursorPositionChanged.disconnect(self.highlightCurrentLine)

        extraSelections = []
        selection = QTextEdit.ExtraSelection()
        selection.format.setBackground(QColor("#E6D9EC"))
        selection.format.setProperty(QTextFormat.FullWidthSelection, True)
        selection.cursor = cursor
        selection.cursor.clearSelection()
        extraSelections.append(selection)

        self.setExtraSelections(extraSelections)

        # Scroll the line into view
        self.setTextCursor(cursor)
        self.ensureCursorVisible()

        # Repaint now so the highlight shows during a run
        QApplication.processEvents()

        self.cursorPositionChanged.connect(self.highlightCurrentLine)

    def toggleBreakpoint(self, line):
        """Toggle breakpoint state for the specified line"""
        if line in self.breakpoints:
            self.breakpoints.remove(line)
        else:
            self.breakpoints.add(line)

        self.lineNumberArea.update()

    def zoom_in(self):
        super().zoom_in()
        self.lineNumberArea.zoom_in()

    def zoom_out(self):
        super().zoom_out()
        self.lineNumberArea.zoom_out()

    def reset_zoom(self):
        super().reset_zoom()
        self.lineNumberArea.reset_zoom()

def use_light_theme():
    """
    The interface is designed in light colours only. With Windows in dark
    mode Qt would switch the default palette to white text, which is
    invisible on the white panels (e.g. the listing window), so the light
    colour scheme is requested whatever the system setting is.
    """
    app = QApplication.instance()
    if app is not None and hasattr(app.styleHints(), "setColorScheme"):
        app.styleHints().setColorScheme(Qt.ColorScheme.Light)


class ShortScreenScrollArea(QScrollArea):
    """
    Holds a panel at its natural size and adds a vertical scroll bar only
    when the window is shorter than the panel needs, so the window still fits
    on small or highly scaled screens. Its minimum width is the panel's, so
    the pane can't be squeezed narrower than before.
    """

    MIN_HEIGHT = 200

    def __init__(self, widget, parent=None):
        super().__init__(parent)
        self.setWidget(widget)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.viewport().setAutoFillBackground(False)
        widget.setAutoFillBackground(False)

    def minimumSizeHint(self):
        width = self.widget().minimumSizeHint().width() + self.verticalScrollBar().sizeHint().width()
        return QSize(width, self.MIN_HEIGHT)

    def sizeHint(self):
        hint = self.widget().sizeHint()
        return QSize(hint.width() + self.verticalScrollBar().sizeHint().width(), hint.height())


class Simulator(QWidget):
    """Main simulator application for the 8085 microprocessor"""

    def __init__(self):
        use_light_theme()
        super().__init__()
        self.processor = Processor8085()
        # 8255 PPI at 40H-43H and 8253 PIT at 50H-53H on the I/O bus
        self.peripherals = PeripheralBus(ppi_base=0x40, pit_base=0x50)
        self.peripherals.attach(self.processor)
        self.execution_log = []
        self.execution_count = 0
        self.current_file = None
        self.document_name = None  # Name of an example or imported file not saved yet
        self._interrupt_tally = Counter()  # interrupts not yet logged in a fast run
        self._interrupt_tally_since = 0
        self._run_interrupts_logged = 0
        self.listing_window = None
        self.user_memory_addr = 0x0000
        self.follow_pc = False
        self.use_highlighting = True
        self.document_modified = False
        self.running = False
        self.realtime = False  # True while running in real-time mode
        self.run_mode = None  # "run", "fast" or "realtime" while a clocked run is active
        self.clock_hz = CPU_CLOCK_HZ  # Clock frequency of the current run
        self.selected_clock_hz = CPU_CLOCK_HZ  # Clock chosen for Real-Time runs
        self.halt_wait_logged = False
        # When execution is (re)started from a line with a breakpoint, the
        # first instruction must run instead of stopping at the same breakpoint
        self.skip_breakpoint_once = False
        # Warn only once per run when PC leaves the assembled program
        self.outside_program_warned = False

        # Simulated external hardware (kept when the program is re-assembled)
        self.led_port = 0x01  # 8 LEDs driven by this output port
        self.switch_port = 0x00  # 8 switches read through this input port
        self.switch_bits = 0x00
        self.input_values = {}  # Other input ports: port -> value driven by the device
        self.io_seen_ports = set()  # Ports accessed by IN/OUT (shown in the port table)
        self.pin_levels = {"RST6.5": False, "RST5.5": False}  # Level-triggered inputs
        self.sid_level = 0  # Serial input pin

        # Wall-clock time of the run, shown in the statistics bar
        self.elapsed_timer = QElapsedTimer()
        self.elapsed_time_ms = 0
        self.timer_running = False

        self.init_ui()

    def start_elapsed_timer(self):
        """Start or resume execution timing"""
        if not self.timer_running:
            self.elapsed_timer.start()
            self.timer_running = True

    def stop_elapsed_timer(self):
        """Stop execution timer and update elapsed time"""
        if self.timer_running:
            self.elapsed_time_ms += self.elapsed_timer.elapsed()
            self.timer_running = False
            self.update_elapsed_time_display()

    def reset_elapsed_timer(self):
        """Reset execution timer statistics"""
        self.elapsed_time_ms = 0
        self.timer_running = False
        self.update_elapsed_time_display()

    def update_elapsed_time_display(self):
        """Format and display elapsed execution time with appropriate units"""
        total_ms = self.elapsed_time_ms

        if self.timer_running:
            total_ms += self.elapsed_timer.elapsed()

        if total_ms < 1000:
            time_str = f"{total_ms} ms"
        elif total_ms < 60000:
            time_str = f"{total_ms / 1000:.2f} s"
        else:
            minutes = int(total_ms / 60000)
            seconds = (total_ms % 60000) / 1000
            time_str = f"{minutes}:{seconds:06.3f}"

        self.exec_time_label.setText(f"Elapsed Time: {time_str}")

    def init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle(
            f"Neo8085 v{display_version} - 8085 Microprocessor Simulator"
        )
        self.setGeometry(100, 50, 1280, 800)

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.menu_bar = MenuBar(self)

        file_menu = self.menu_bar.addMenu("File")

        new_action = QAction("New File", self)
        new_action.setShortcut("Ctrl+N")
        new_action.triggered.connect(self.new_file)
        file_menu.addAction(new_action)

        load_action = QAction("Open Program", self)
        load_action.setShortcut("Ctrl+O")
        load_action.triggered.connect(self.load_program)
        file_menu.addAction(load_action)

        file_menu.addSeparator()

        save_action = QAction("Save", self)
        save_action.setShortcut("Ctrl+S")
        save_action.triggered.connect(self.save_program)
        file_menu.addAction(save_action)

        save_as_action = QAction("Save As...", self)
        save_as_action.setShortcut("Ctrl+Shift+S")
        save_as_action.triggered.connect(self.save_program_as)
        file_menu.addAction(save_as_action)

        file_menu.addSeparator()

        import_hex_action = QAction("Import Intel HEX...", self)
        import_hex_action.setShortcut("Ctrl+I")
        import_hex_action.setToolTip("Load an Intel HEX object file (it is disassembled into the editor)")
        import_hex_action.triggered.connect(self.import_intel_hex)
        file_menu.addAction(import_hex_action)

        export_hex_action = QAction("Export Intel HEX...", self)
        export_hex_action.setShortcut("Ctrl+E")
        export_hex_action.setToolTip("Save the assembled object code as an Intel HEX file")
        export_hex_action.triggered.connect(self.export_intel_hex)
        file_menu.addAction(export_hex_action)

        export_hex_start_action = QAction("Export Intel HEX with Start Address...", self)
        export_hex_start_action.setToolTip(
            "Adds a Start Segment Address record (type 03). Intel's 8-bit HEX format has no start "
            "record; most tools accept this one, strict 8-bit loaders may not."
        )
        export_hex_start_action.triggered.connect(lambda: self.export_intel_hex(with_start=True))
        file_menu.addAction(export_hex_start_action)

        file_menu.addSeparator()

        listing_action = QAction("Opcode Listing", self)
        listing_action.setShortcut("Ctrl+L")
        listing_action.setToolTip("Assemble the program and show its opcode listing")
        listing_action.triggered.connect(self.show_listing)
        file_menu.addAction(listing_action)

        save_listing_action = QAction("Save Listing...", self)
        save_listing_action.triggered.connect(self.save_listing)
        file_menu.addAction(save_listing_action)

        print_listing_action = QAction("Print Listing...", self)
        print_listing_action.setShortcut("Ctrl+P")
        print_listing_action.triggered.connect(self.print_listing)
        file_menu.addAction(print_listing_action)

        file_menu.setToolTipsVisible(True)
        file_menu.addSeparator()

        exit_action = QAction("Exit", self)
        exit_action.setShortcut("Alt+F4")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        run_menu = self.menu_bar.addMenu("Simulator")

        compile_action = QAction("Assemble", self)
        compile_action.setShortcut(QKeySequence("Ctrl+B"))
        compile_action.triggered.connect(self.compile_program)

        step_action = QAction("Step", self)
        step_action.setShortcut(QKeySequence("F10"))
        step_action.triggered.connect(self.execute_single_step)

        run_action = QAction("Run", self)
        run_action.setShortcut(QKeySequence("F5"))
        run_action.triggered.connect(self.start_continuous_execution)

        run_fast_action = QAction("Run without Highlighting", self)
        run_fast_action.setShortcut(QKeySequence("Ctrl+Shift+F5"))
        run_fast_action.triggered.connect(self.start_fast_execution)

        run_realtime_action = QAction(
            f"Run Real-Time ({format_frequency(self.selected_clock_hz)})", self
        )
        run_realtime_action.setShortcut(QKeySequence("Ctrl+F5"))
        run_realtime_action.triggered.connect(self.start_realtime_execution)
        self.run_realtime_action = run_realtime_action

        stop_action = QAction("Stop", self)
        stop_action.setShortcut(QKeySequence("F8"))
        stop_action.triggered.connect(self.stop_execution)

        reset_action = QAction("Reset (keep memory)", self)
        reset_action.setShortcut(QKeySequence("Ctrl+R"))
        reset_action.triggered.connect(self.soft_reset)

        full_reset_action = QAction("Full Reset (clear everything)", self)
        full_reset_action.setShortcut(QKeySequence("Ctrl+Shift+R"))
        full_reset_action.triggered.connect(self.reset_simulation)

        run_menu.addAction(compile_action)
        run_menu.addAction(step_action)
        run_menu.addAction(run_action)
        run_menu.addAction(run_fast_action)
        run_menu.addAction(run_realtime_action)
        run_menu.addAction(stop_action)
        run_menu.addAction(reset_action)
        run_menu.addAction(full_reset_action)

        debug_menu = self.menu_bar.addMenu("Debug")
        add_bp_action = QAction("Add Breakpoint", self)
        add_bp_action.setShortcut("F9")
        add_bp_action.triggered.connect(self.add_breakpoint)
        remove_bp_action = QAction("Remove Breakpoint", self)
        remove_bp_action.triggered.connect(self.remove_breakpoint)
        remove_all_bp_action = QAction("Remove All Breakpoints", self)
        remove_all_bp_action.triggered.connect(self.remove_all_breakpoints)
        debug_menu.addAction(add_bp_action)
        debug_menu.addAction(remove_bp_action)
        debug_menu.addAction(remove_all_bp_action)
        debug_menu.addSeparator()
        timing_action = QAction("Timing Diagram", self)
        timing_action.setShortcut(QKeySequence("Ctrl+T"))
        timing_action.triggered.connect(self.show_timing_diagram)
        debug_menu.addAction(timing_action)

        # View Menu: show or hide the panes (they can also be resized and hidden
        # by dragging the handles between them)
        view_menu = self.menu_bar.addMenu("View")
        self.pane_actions = {}
        for key, text, shortcut in (
            ("lower", "Lower Panes (Log and Tabs)", "Ctrl+J"),
            ("log", "Execution Log", "Ctrl+Shift+J"),
            ("tabs", "Side Tabs (Tools, I/O, ...)", "Ctrl+Shift+K"),
            ("right", "Registers and Memory Panel", "Ctrl+Shift+M"),
        ):
            action = QAction(text, self)
            action.setCheckable(True)
            action.setChecked(True)
            action.setShortcut(shortcut)
            action.toggled.connect(lambda shown, k=key: self.set_pane_visible(k, shown))
            view_menu.addAction(action)
            self.pane_actions[key] = action
        view_menu.addSeparator()
        reset_layout_action = QAction("Reset Layout", self)
        reset_layout_action.triggered.connect(self.reset_layout)
        view_menu.addAction(reset_layout_action)

        zoom_menu = self.menu_bar.addMenu("Zoom")
        zoom_in_action = QAction("Zoom In", self)
        zoom_in_action.setShortcut("Ctrl+=")
        zoom_in_action.triggered.connect(self.zoom_in)
        zoom_out_action = QAction("Zoom Out", self)
        zoom_out_action.setShortcut("Ctrl+-")
        zoom_out_action.triggered.connect(self.zoom_out)
        reset_zoom_action = QAction("Reset Zoom", self)
        reset_zoom_action.setShortcut("Ctrl+0")
        reset_zoom_action.triggered.connect(self.reset_zoom)
        zoom_menu.addAction(zoom_in_action)
        zoom_menu.addAction(zoom_out_action)
        zoom_menu.addAction(reset_zoom_action)

        examples_menu = self.menu_bar.addMenu("Examples")
        self.examples_menu = examples_menu
        categories = list(dict.fromkeys(example.category for example in EXAMPLES))
        for category in categories:
            if not examples_menu.isEmpty():
                examples_menu.addSeparator()
            header = examples_menu.addAction(category)
            header.setEnabled(False)
            for example in EXAMPLES:
                if example.category != category:
                    continue
                action = QAction(f"    {example.title}", self)
                action.setToolTip(example.hint)
                action.triggered.connect(lambda _=False, ex=example: self.load_example(ex))
                examples_menu.addAction(action)
        examples_menu.setToolTipsVisible(True)

        help_menu = self.menu_bar.addMenu("Help")
        about_action = QAction("About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

        main_layout.addWidget(self.menu_bar)

        content_splitter = hw.GripSplitter(
            Qt.Orientation.Horizontal,
            "Drag to resize the editor side and the registers and memory panel.\n"
            "Drag to the edge to hide a side (View menu shows it again).\n"
            "Double-click to restore.",
        )
        content_splitter.setContentsMargins(0, 0, 5, 5)
        content_layout = QVBoxLayout()

        # Left side: editor, execution log and side tabs
        left_part = QWidget()
        left_panel = QVBoxLayout(left_part)

        self.setStyleSheet(
            """
            QWidget {
                background-color: #EDEDED;
                color: #1E1E1E;
            }
            QScrollBar:vertical {
                border: none;
                background: #F0F0F0;
                width: 10px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #AAAAAA;
                min-height: 30px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover {
                background: #888888;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
                background: none;
                border: none;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
            QScrollBar:horizontal {
                border: none;
                background: #F0F0F0;
                height: 10px;
                margin: 0px;
            }
            QScrollBar::handle:horizontal {
                background: #AAAAAA;
                min-width: 30px;
                border-radius: 5px;
            }
            QScrollBar::handle:horizontal:hover {
                background: #888888;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
                background: none;
                border: none;
            }
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
                background: none;
            }
        """
        )

        self.code_editor = LineNumberedEditor()

        # Lets the line number area report breakpoint errors in the log
        self.code_editor.lineNumberArea.set_simulator(self)

        editor_part = QWidget()
        editor_layout = QVBoxLayout(editor_part)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(0)
        editor_layout.addWidget(self.code_editor)
        editor_layout.addWidget(self.code_editor.status_bar)

        # The editor and the lower panes share the height: drag the handle
        # between them to resize, or to the bottom to hide the lower panes
        self.left_splitter = hw.GripSplitter(
            Qt.Orientation.Vertical,
            "Drag up or down to resize the editor and the lower panes.\n"
            "Drag to the bottom to hide the lower panes (Ctrl+J shows them again).\n"
            "Double-click to restore.",
        )
        self.left_splitter.addWidget(editor_part)
        left_panel.addWidget(self.left_splitter)

        # Context menu for breakpoints
        self.code_editor.setContextMenuPolicy(Qt.CustomContextMenu)
        self.code_editor.customContextMenuRequested.connect(
            self.show_editor_context_menu
        )

        # Execution log
        log_layout = QVBoxLayout()
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(0)

        log_header_layout = QHBoxLayout()
        log_header_layout.setContentsMargins(0, 0, 0, 0)
        log_header_layout.setSpacing(0)

        log_header = Header("EXECUTION LOG")
        log_header_layout.addWidget(log_header, 9)

        self.clear_log_button = PushButton("Clear")
        self.clear_log_button.setStyleSheet(
            """
            QPushButton {
                background-color: #8D56CA;
                color: white;
                border: 2px solid #D3BEEB;
                padding: 6px;
            }
            QPushButton:hover {
                background-color: #5C2D91;
                border: 2px solid #8D56CA;
            }
        """
        )
        log_header_layout.addWidget(self.clear_log_button, 1)
        self.clear_log_button.clicked.connect(self.clear_execution_log)

        log_layout.addLayout(log_header_layout)
        
        self.execution_log_widget = TextEdit()
        self.execution_log_widget.setFont(QFont(hw.PANEL_FONT, 10))
        self.execution_log_widget.setReadOnly(True)
        # Only the latest LOG_VISIBLE_ENTRIES lines stay in the widget
        self.execution_log_widget.document().setMaximumBlockCount(LOG_VISIBLE_ENTRIES)
        self.execution_log_widget.clear()

        self.execution_log_widget.setStyleSheet(
            """
            QTextEdit {
                background-color: white; 
                color: #1E1E1E; 
                padding: 5px;
                border: none;
            }
            QScrollBar:vertical {
                border: none;
                background: #F0F0F0;
                width: 10px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #AAAAAA;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background: #888888;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
                background: none;
                border: none;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """
        )

        log_layout.addWidget(self.execution_log_widget, 1)
        log_part = QWidget()
        log_part.setLayout(log_layout)

        # Tabs next to the log: tools (converter + memory editor), I/O devices
        # and the interrupt inputs
        tools_widget = QWidget()
        right_side_layout = hw.plain_page(tools_widget)  # no scrolling: the sections fit the tab
        right_side_layout.addWidget(self.create_converter())
        right_side_layout.addWidget(self.create_memory_editor())
        right_side_layout.addStretch(1)

        self.side_tabs = QTabWidget()
        self.side_tabs.setStyleSheet(
            """
            QTabWidget::pane { border: 1px solid #DDDDDD; background: #F0F0F0; }
            QTabBar::tab { background: #EDEDED; padding: 4px 10px; font: 9pt "Segoe UI"; }
            QTabBar::tab:selected { background: #5C2D91; color: white; }
        """
        )
        self.side_tabs.addTab(tools_widget, "Tools")
        self.side_tabs.addTab(self.create_io_panel(), "I/O")
        self.side_tabs.addTab(self.create_interrupt_panel(), "Interrupts")
        self.bus_panel = BusCyclePanel()
        self.side_tabs.addTab(self.bus_panel, "Bus Cycles")
        self.ppi_panel = PPIPanel(self)
        self.side_tabs.addTab(self.ppi_panel, "8255")
        self.pit_panel = PITPanel(self)
        self.side_tabs.addTab(self.pit_panel, "8253")
        self.side_tabs.currentChanged.connect(lambda _index: self.update_peripheral_display())

        # The execution log and the side tabs share the width of the lower
        # panes: drag the handle between them to resize either, or to hide it
        self.lower_splitter = hw.GripSplitter(
            Qt.Orientation.Horizontal,
            "Drag to resize the Execution Log and the side tabs.\n"
            "Drag to an edge to hide one of them (View menu shows it again).\n"
            "Double-click to restore.",
        )
        # Everything in the bottom panes inherits the font of the section headings
        self.lower_splitter.setFont(QFont(hw.PANEL_FONT, 9))
        self.lower_splitter.addWidget(log_part)
        self.lower_splitter.addWidget(self.side_tabs)
        self.lower_splitter.setStretchFactor(0, 1)
        self.lower_splitter.setStretchFactor(1, 1)
        self.left_splitter.addWidget(self.lower_splitter)
        self.left_splitter.setCollapsible(0, False)  # the editor always stays
        self.left_splitter.setStretchFactor(0, 4)
        self.left_splitter.setStretchFactor(1, 2)

        # Right side: controls, registers, stack and memory
        right_part = QWidget()
        right_panel = QVBoxLayout(right_part)

        simulator_header = Header("SIMULATOR OPERATIONS")
        right_panel.addWidget(simulator_header)

        control_layout = QHBoxLayout()

        self.compile_button = PushButton("Assemble")
        self.compile_button.setStyleSheet(
            """
            QPushButton {
                background-color: #458ADB; 
                color: white; 
                border: none; 
                padding: 6px;
            }
            QPushButton:hover {
                background-color: #3A75C4;
            }
        """
        )
        self.compile_button.clicked.connect(self.compile_program)

        self.step_button = PushButton("Step")
        self.step_button.setStyleSheet(
            """
            QPushButton {
                background-color: #B8A404; 
                color: white; 
                border: none; 
                padding: 6px;
            }
            QPushButton:hover {
                background-color: #9E8C03;
            }
        """
        )
        self.step_button.clicked.connect(self.execute_single_step)

        self.run_button = PushButton("Run")
        self.run_button.setStyleSheet(
            """
            QPushButton {
                background-color: #0DB000; 
                color: white; 
                border: none; 
                padding: 6px;
            }
            QPushButton:hover {
                background-color: #0A9000;
            }
        """
        )
        self.run_button.clicked.connect(self.start_continuous_execution)

        self.realtime_button = PushButton("Real-Time")
        self.realtime_button.setStyleSheet(
            """
            QPushButton {
                background-color: #0F7C8C;
                color: white;
                border: none;
                padding: 6px;
            }
            QPushButton:hover {
                background-color: #0B6470;
            }
        """
        )
        self.realtime_button.clicked.connect(self.start_realtime_execution)

        self.stop_button = PushButton("Stop")
        self.stop_button.setStyleSheet(
            """
            QPushButton {
                background-color: #C42B1C; 
                color: white; 
                border: none; 
                padding: 6px;
            }
            QPushButton:hover {
                background-color: #A82318;
            }
        """
        )
        self.stop_button.clicked.connect(self.stop_execution)
        self.stop_button.setEnabled(False)

        self.reset_button = PushButton("Reset")
        self.reset_button.setStyleSheet(
            """
            QPushButton {
                background-color: white; 
                color: #1E1E1E; 
                border: 2px solid #DDDDDD; 
                padding: 6px;
            }
            QPushButton:hover {
                background-color: #F0F0F0;
                border: 2px solid #BBBBBB;
            }
        """
        )
        self.reset_button.setToolTip(
            "8085 RESET: restart at the program's start address; registers and memory are kept (Ctrl+R)"
        )
        self.reset_button.clicked.connect(self.soft_reset)

        self.full_reset_button = PushButton("Full Reset")
        self.full_reset_button.setStyleSheet(
            """
            QPushButton {
                background-color: white;
                color: #A82318;
                border: 2px solid #E8B4AE;
                padding: 6px;
            }
            QPushButton:hover {
                background-color: #FDE7E9;
                border: 2px solid #C42B1C;
            }
        """
        )
        self.full_reset_button.setToolTip(
            "Clear registers, flags and all memory and unload the program (Ctrl+Shift+R)"
        )
        self.full_reset_button.clicked.connect(self.reset_simulation)

        control_layout.addWidget(self.compile_button)
        control_layout.addWidget(self.step_button)
        control_layout.addWidget(self.run_button)
        control_layout.addWidget(self.realtime_button)
        control_layout.addWidget(self.stop_button)
        control_layout.addWidget(self.reset_button)
        control_layout.addWidget(self.full_reset_button)

        right_panel.addLayout(control_layout)

        # CPU clock selector (used by Real-Time runs)
        clock_layout = QHBoxLayout()
        clock_label = Label("CPU clock (Real-Time):", font_family="Segoe UI", font_point_size=10)
        self.clock_selector = ClockSelector()
        for name, hz in CLOCK_PRESETS:
            if hz == 3_000_000:  # slow-motion clocks above, real 8085 parts below
                self.clock_selector.insertSeparator(self.clock_selector.count())
            self.clock_selector.addItem(name)
        self.clock_selector.set_text(
            next(name for name, hz in CLOCK_PRESETS if hz == self.selected_clock_hz)
        )
        self.clock_selector.setMinimumWidth(190)
        self.clock_selector.setToolTip(
            "Clock frequency for Real-Time runs. Pick a preset or type a value such as "
            "'250 kHz'. At 200 Hz or less every instruction is highlighted and logged. "
            "Takes effect immediately, also during a run."
        )
        self.clock_selector.activated.connect(lambda _index: self.apply_clock_selection())
        self.clock_selector.lineEdit().editingFinished.connect(self.apply_clock_selection)
        clock_layout.addWidget(clock_label)
        clock_layout.addWidget(self.clock_selector, 1)
        right_panel.addLayout(clock_layout)
        self._update_clock_texts()

        self.status_label = Label("Ready", font_family="Segoe UI", font_point_size=10)
        self.status_label.setStyleSheet(
            "background-color: white; color: #1E1E1E; padding: 5px; border: 1px solid #DDDDDD;"
        )
        self.status_label.setAlignment(Qt.AlignCenter)
        self.set_status("Ready", "normal")
        right_panel.addWidget(self.status_label)

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setStyleSheet("background-color: #555;")
        right_panel.addWidget(separator)

        registers_stack_layout = QHBoxLayout()

        self.register_labels = {}

        self.registers_grid = QGridLayout()

        register_header = Header("REGISTERS")
        self.registers_grid.addWidget(register_header, 0, 0, 1, 2)

        # Grid: A and the flags, PSW, the register pairs, then SP and PC
        self.add_register("A", 1, 0)
        self.flags_group = Flags(self)
        self.registers_grid.addWidget(self.flags_group, 1, 1)

        self.add_register("PSW", 2, 0, 1, 2)

        self.add_register("B", 3, 0)
        self.add_register("C", 3, 1)
        self.add_register("D", 4, 0)
        self.add_register("E", 4, 1)
        self.add_register("H", 5, 0)
        self.add_register("L", 5, 1)

        self.add_register("SP", 6, 0, 1, 2)
        self.add_register("PC", 7, 0, 1, 2)

        self.stack = Stack(self)

        registers_stack_layout.addLayout(self.registers_grid, 1)
        registers_stack_layout.addLayout(self.stack, 1)
        
        right_panel.addLayout(registers_stack_layout)
        self.update_registers_display()

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setStyleSheet("background-color: #555;")
        right_panel.addWidget(separator)

        memory_header = Header("MEMORY")
        right_panel.addWidget(memory_header)

        memory_search_layout = QHBoxLayout()

        self.memory_search = LineEdit("Enter memory address (e.g., 8000, 2000H)")
        self.memory_search.setStyleSheet(
            "background-color: white; color: #1E1E1E; border: 1px solid #DDDDDD; padding: 5px;"
        )
        self.memory_search.returnPressed.connect(self.load_memory_address)
        self.memory_search.textChanged.connect(self.validate_memory_address)
        self.memory_search.setValidator(None)
        memory_search_layout.addWidget(self.memory_search, 4)

        self.memory_enter_button = PushButton("Enter")
        self.memory_enter_button.setStyleSheet(
            """
            QPushButton {
                background-color: white;
                color: #1E1E1E;
                border: 1px solid #DDDDDD;
                padding: 5px;
            }
            QPushButton:hover {
                background-color: #E6F2FF;
                border: 1px solid #BBBBBB;
            }
        """
        )
        self.memory_enter_button.clicked.connect(self.load_memory_address)
        memory_search_layout.addWidget(self.memory_enter_button, 1)

        self.follow_pc_button = PushButton("Follow PC")
        self.follow_pc_button.setCheckable(True)
        self.follow_pc_button.setChecked(False)
        self.follow_pc_button.setStyleSheet(
            """
            QPushButton {
                background-color: white;
                color: #1E1E1E;
                border: 1px solid #DDDDDD;
                padding: 5px;
            }
            QPushButton:checked {
                background-color: #007ACC;
                color: white;
            }
            QPushButton:hover:!checked {
                background-color: #E6F2FF;
                border: 1px solid #BBBBBB;
            }
        """
        )
        self.follow_pc_button.clicked.connect(self.toggle_follow_pc)
        memory_search_layout.addWidget(self.follow_pc_button, 1)

        right_panel.addLayout(memory_search_layout)

        # Memory Table of 16 rows, 18 columns (decimal+hex address + 16 bytes)
        self.memory_table = MemoryTableWidget(16, 18, self)
        right_panel.addWidget(self.memory_table)

        stats_layout = QHBoxLayout()

        self.instr_count_label = Label("Instructions: 0", font_family="Segoe UI", font_point_size=10)
        self.instr_count_label.setStyleSheet(
            "background-color: white; color: #1E1E1E; padding: 5px; border: 1px solid #DDDDDD;"
        )

        self.exec_time_label = Label("Elapsed Time: 0 ms", font_family="Segoe UI", font_point_size=10)
        self.exec_time_label.setStyleSheet(
            "background-color: white; color: #1E1E1E; padding: 5px; border: 1px solid #DDDDDD;"
        )

        self.tstate_label = Label("T-States: 0", font_family="Segoe UI", font_point_size=10)
        self.tstate_label.setStyleSheet(
            "background-color: white; color: #1E1E1E; padding: 5px; border: 1px solid #DDDDDD;"
        )
        self.tstate_label.setToolTip("Total 8085 clock cycles (T-states) executed")

        stats_layout.addWidget(self.instr_count_label)
        stats_layout.addWidget(self.tstate_label)
        stats_layout.addWidget(self.exec_time_label)

        right_panel.addLayout(stats_layout)

        content_splitter.addWidget(left_part)
        # Scrolls only on screens too short for the panel (e.g. 1080p at 150% scaling)
        content_splitter.addWidget(ShortScreenScrollArea(right_part))
        content_splitter.setStretchFactor(0, 55)
        content_splitter.setStretchFactor(1, 45)
        self.content_splitter = content_splitter
        self._setup_pane_splitters()

        # Stretch so the splitter fills all the height below the menu bar
        content_layout.addWidget(content_splitter, 1)
        main_layout.addLayout(content_layout)

        self.setLayout(main_layout)

        # Clock-driven execution: each 10 ms tick executes as many T-states as
        # the wall clock says the CPU clock has produced since the run started
        self.realtime_timer = QTimer()
        self.realtime_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.realtime_timer.timeout.connect(self.execute_clock_slice)
        self.realtime_clock = QElapsedTimer()
        self.realtime_start_tstates = 0
        self.realtime_executed_tstates = 0
        self.realtime_wall_ns = 0
        self.realtime_last_refresh_ns = 0

        self.load_memory_display(0x0000)

        # Welcome text
        self.code_editor.setPlainText(
            rf"""; +===================================================================+
;     _   __           ____  ____  ____  ______
;    / | / /__  ____  ( __ )/ __ \( __ )/ ____/
;   /  |/ / _ \/ __ \/ __  / / / / __  /___ \  
;  / /|  /  __/ /_/ / /_/ / /_/ / /_/ /___/ /  
; /_/ |_/\___/\____/\____/\____/\____/_____/  
;
; Version: {display_version}
;
; Copyright 2026 (c) Shahibur Rahaman
; Licensed under GNU GPL v3.0
;
; +==================================================================+
; |       Welcome to Neo8085 - 8085 Microprocessor Simulator         |
; +==================================================================+
;
; SIMULATOR USAGE INSTRUCTIONS:
; ----------------------------
; 1. EDITING & SAVING:
;    - Type your assembly code in this editor
;    - Save/Open files using File menu or Ctrl+S / Ctrl+O
;    - Modified files show an asterisk (*) in the title bar
;
; 2. ASSEMBLING & EXECUTION:
;    - Click "Assemble
;    - "Step" (F10) to execute one instruction at a time
;    - Every run mode is driven by a CPU clock that follows real time: each
;      instruction takes exactly its T-states, and HLT keeps the clock running
;    - "Run" (F5): 100 Hz slow-motion clock with highlighting (4 T = 40 ms)
;    - "Fast mode" (Ctrl+Shift+F5): 2 kHz clock without highlighting
;    - "Real-Time" (Ctrl+F5): the real speed of a 3.072 MHz 8085
;    - "Stop" (F8) to pause continuous execution
;    - "Reset" (Ctrl+R) restarts at the program start; registers and memory are kept
;    - "Full Reset" (Ctrl+Shift+R) clears registers, flags and all memory
;
; 3. DEBUGGING FEATURES:
;    - Add breakpoints by clicking in the line number margin
;    - Or use F9 to add a breakpoint at the current line
;    - Use the Memory Editor to modify memory
;    - Use Memory table view to inspect and analyze the memory during execution
;    - Follow PC button (toggle) tracks the Program Counter in memory
;
; 4. LAYOUT:
;    - Drag the dotted dividers between the panes to resize them
;    - Drag a divider to the edge to hide a pane; double-click it to restore
;    - View menu: show/hide each pane (Ctrl+J: lower panes), Reset Layout
;
; 5. INTERRUPTS AND I/O (tabs next to the Execution Log):
;    - Interrupts tab: TRAP, RST 7.5, RST 6.5, RST 5.5 and INTR inputs with the
;      real 8085 rules (priority, EI/DI, SIM masks, edge/level triggering).
;      Vectors: TRAP 0024H, RST 5.5 002CH, RST 6.5 0034H, RST 7.5 003CH.
;      With EI, "Run" waits in HLT until an interrupt arrives.
;    - I/O tab: 8 LEDs on an output port, 8 switches on an input port, input
;      port values for IN, the port latch table and the SID/SOD serial pins.
;    - Bus Cycles tab: the machine cycles (opcode fetch, memory/I/O read and
;      write, interrupt acknowledge, bus idle) of each stepped instruction with
;      addresses, data and status lines. Ctrl+T opens the T-state timing
;      diagram (CLK, A15-A8, AD7-AD0, ALE, IO/M, S1, S0, RD, WR, INTA).
;    - 8255 and 8253 tabs: an 8255 PPI at ports 40H-43H and an 8253 PIT at
;      50H-53H, with their pins, handshakes, counter clocks and interrupt
;      wiring. See Examples > Peripherals.
;
; 6. DIRECTIVE USAGE:
;    - ORG: Set starting address - e.g., "ORG 2000H"
;    - EQU / SET: Define constants - e.g., "COUNT EQU 5 * 5" (SET can be redefined)
;    - DS: Reserve memory space - e.g., "BUFFER: DS 10"
;    - DB / DW: Define bytes / words - e.g., "MSG: DB 'Hello', 0DH, 0AH"
;    - IF / ELSE / ENDIF, MACRO / ENDM, REPT, IRP, IRPC: Intel conditional assembly and macros
;    - END: Marks the end of the program (optionally "END START" sets the start address)
;    - Numbers: 25, 25D, 19H (hex must start with a digit: 0FFH), 11001B, 31Q, 'A', $
;    - Operators follow Intel precedence: * / MOD SHL SHR before + - , then
;      EQ NE LT LE GT GE, NOT, AND, OR XOR (also HIGH, LOW and parentheses)
;    - NOTE! Like a real 8085, the CPU executes whatever bytes PC reaches. Jump over
;      "DS" areas, otherwise the reserved bytes are executed as instructions (00H = NOP).
;
; EXAMPLE PROGRAM BELOW DEMONSTRATES:
; - EQU nested directives with arithmetic
; - Memory operations
; - Register manipulation
; - Program logic and looping
; +===================================================================+
;
; ===================================================================
;              FIBONACCI SERIES CALCULATION AND STORAGE
; ===================================================================

; - After assembling the code use the memory table view's search field
;   to locate the loaded program (e.g., 2000H for our example program).
; - Use "Follow PC" (toggle) to easily locate the current row of memory
;   that is being executed (16 bytes per row). 

ORG 2000H		; Due to presence of 'H' suffix this is treated as HEX value

JMP START

FIRST_ELEMENT:	EQU 0	; Treated as DECIMAL value due to lack of 'H' suffix
SECOND_ELEMENT:	EQU 1	; Treated as DECIMAL value due to lack of 'H' suffix
ELEMENTS_COUNT: 	EQU 0AH  ; 10 ELEMENTS (Treated as HEX value due to presence of 'H' suffix)
LOOP_COUNTER:	EQU ELEMENTS_COUNT - 1 ; FIRST ONE ELEMENT IS NOT NEEDED FOR LOOPING

; RESERVING MEMORY SPACE FOR STORING FIBONACCI SERIES
DATA_AREA: DS ELEMENTS_COUNT

START:	JMP FIBONACCI_SERIES_SETUP	; Jump to the respective label

FIBONACCI_SERIES_SETUP:
	MVI A, FIRST_ELEMENT
	MVI B, SECOND_ELEMENT
	MVI D, LOOP_COUNTER
	LXI H, DATA_AREA
	MOV M, A		; STORING THE FIRST ELEMENT IN MEMORY
	INX H		; INCREASING MEMORY ADDRESS REGISTER VALUE (H-L REGISTER PAIR)
	JMP FIBONACCI_CALC_LOOP

FIBONACCI_CALC_LOOP:
	MOV C, A
	ADD B
	MOV B, C
	DCR D		; DECREASE THE VALUE OF THE LOOP COUNTER REGISTER
	MOV M, A
	INX H
	JNZ FIBONACCI_CALC_LOOP
	JMP END_OF_PROGRAM

END_OF_PROGRAM:
	HLT

END

"""
        )

        self.code_editor.textChanged.connect(self.document_was_modified)

    def add_register(self, name, row, col, rowspan=1, colspan=1):
        """Add a register display to the UI"""
        value = "00H" if name not in ["SP", "PC", "PSW"] else "0000H"
        label = Label(f"{name}: {value}")
        label.setStyleSheet(
            "background-color: white; color: #1E1E1E; padding: 5px; border: 1px solid #DDDDDD;"
        )
        label.setAlignment(Qt.AlignCenter)
        self.registers_grid.addWidget(label, row, col, rowspan, colspan)
        self.register_labels[name] = label

    def update_registers_display(self):
        """Update register display from processor state"""
        for reg, value in self.processor.registers.items():
            if reg in self.register_labels:
                if reg in ["SP", "PC"]:
                    hex_value = f"{value:04X}H"
                else:
                    hex_value = f"{value:02X}H"
                self.register_labels[reg].setText(f"{reg}: {hex_value}")

        self.flags_group.update_display()
        self.stack.update_display()
        if hasattr(self, "interrupt_indicators"):
            self.update_interrupt_display()
            self.update_io_display()

        if "PSW" in self.register_labels:
            psw_value = self.processor.get_psw()
            self.register_labels["PSW"].setText(f"PSW: {psw_value:04X}H")

    def start_fast_execution(self):
        """Run without highlighting, on a FAST_CLOCK_HZ CPU clock."""
        self._start_clocked_run("fast")

    def _set_running_ui(self, running):
        """Enable/disable the control buttons while a run mode is active."""
        for button in (self.compile_button, self.step_button, self.run_button, self.realtime_button):
            button.setEnabled(not running)
        self.stop_button.setEnabled(running)

    def start_realtime_execution(self):
        """Run at the real speed of an 8085 clocked at CPU_CLOCK_HZ."""
        self._start_clocked_run("realtime")

    # Run modes: (clock frequency, highlight and log every instruction, description)
    def _run_modes(self):
        return {
            "run": (RUN_CLOCK_HZ, True, "slow-motion clock"),
            "fast": (FAST_CLOCK_HZ, False, "clock, no highlighting"),
            "realtime": (
                self.selected_clock_hz,
                self.selected_clock_hz <= VISUAL_CLOCK_LIMIT_HZ,
                "real time",
            ),
        }

    def _update_clock_texts(self):
        clock = format_frequency(self.selected_clock_hz)
        self.run_realtime_action.setText(f"Run Real-Time ({clock})")
        self.realtime_button.setToolTip(
            f"Run in real time on a {clock} CPU clock (Ctrl+F5). "
            f"Change the clock with the CPU clock selector."
        )

    def apply_clock_selection(self):
        """Reads the clock selector (preset or typed value) and applies it."""
        text = self.clock_selector.currentText()
        try:
            hz = parse_frequency(text)
        except ValueError as e:
            self.add_to_log(f"Error: {e}", "ERROR")
            self.clock_selector.set_text(self._clock_preset_text(self.selected_clock_hz))
            return
        if hz != self.selected_clock_hz:
            self.set_clock(hz)
        self.clock_selector.set_text(self._clock_preset_text(hz))

    @staticmethod
    def _clock_preset_text(hz):
        for name, preset_hz in CLOCK_PRESETS:
            if preset_hz == hz:
                return name
        return format_frequency(hz)

    def set_clock(self, hz):
        """
        Sets the Real-Time CPU clock. During a Real-Time run the change takes
        effect at once: everything up to now runs at the old clock, and the
        clock continues from the current T-state at the new frequency.
        """
        running_clocked = self.running and self.run_mode == "realtime"
        if running_clocked:
            self._sync_clock()
        self.selected_clock_hz = hz
        self._update_clock_texts()
        self.add_to_log(f"CPU clock set to {format_frequency(hz)}", "SYSTEM")
        if running_clocked and self.running:
            self.clock_hz = hz
            self.use_highlighting = hz <= VISUAL_CLOCK_LIMIT_HZ
            self._update_trace_note()
            self.realtime_start_tstates = self.processor.t_states
            self.realtime_executed_tstates = 0
            self.realtime_wall_ns = 0
            self.realtime_last_refresh_ns = 0
            self.realtime_clock.restart()
            self.update_statistics()

    def _start_clocked_run(self, mode):
        """
        Starts a run driven by a CPU clock that is locked to wall-clock time.
        Each timer tick executes exactly the T-states the clock has produced
        since the run started, so instructions take as long as their T-states
        say and the T-state count always equals elapsed time x frequency.
        """
        if not self.processor.parsed_program:
            if not self.compile_program():
                return

        if self.processor.halted and not self.processor.can_resume():
            self.add_to_log(
                "Cannot run - program has halted with interrupts disabled. "
                "Raise TRAP, Reset or assemble again.",
                "SYSTEM",
            )
            self.set_status("Program halted - Reset to run again", "warning")
            return

        clock_hz, verbose, description = self._run_modes()[mode]
        self._run_interrupts_logged = 0
        self._interrupt_tally.clear()
        self._interrupt_tally_since = 0
        self.run_mode = mode
        self.realtime = mode == "realtime"
        self.clock_hz = clock_hz
        self.use_highlighting = verbose
        self._update_trace_note()
        self.running = True
        self.skip_breakpoint_once = True
        self.halt_wait_logged = False
        self.realtime_start_tstates = self.processor.t_states
        self.realtime_executed_tstates = 0
        self.realtime_wall_ns = 0
        self.realtime_last_refresh_ns = 0
        self.realtime_clock.start()
        self.start_elapsed_timer()
        self.realtime_timer.start(10)

        self._set_running_ui(True)
        self.set_status(f"Running @ {format_frequency(clock_hz)} ({description})", "success")
        self.add_to_log(
            f"Execution started: CPU clock {format_frequency(clock_hz)} ({description})", "SYSTEM"
        )
        if verbose:
            self.highlight_current_instruction()

    def execute_clock_slice(self):
        """
        Executes everything the CPU clock has produced up to now. Called by the
        10 ms timer, and before any external input changes (interrupt pins,
        switches, input ports, SID) so the change happens at the right T-state.
        """
        if not self.running:
            return

        cpu = self.processor
        step = cpu.step
        regs = cpu.registers
        address_to_line = cpu.address_to_line_map
        breakpoints = self.code_editor.breakpoints
        breakpoint_addresses = {
            address for address, line in address_to_line.items() if (line - 1) in breakpoints
        }
        verbose = self.use_highlighting  # slow-motion Run: log and highlight everything
        clock_hz = self.clock_hz
        cpu.trace_bus = verbose  # machine cycles are recorded only in slow-motion runs

        # T-states the CPU clock has produced by now
        elapsed_ns = self.realtime_clock.nsecsElapsed()
        target = self.realtime_start_tstates + (elapsed_ns * clock_hz) // 1_000_000_000
        # If the host cannot keep up, do not try to catch up more than 50 ms of
        # backlog: the clock's start moves back by the time that is given up
        max_backlog = max(clock_hz // 20, 32)
        if target - cpu.t_states > max_backlog:
            self.realtime_start_tstates -= target - cpu.t_states - max_backlog
            target = cpu.t_states + max_backlog

        start_tstates = cpu.t_states
        deadline_ns = elapsed_ns + 9_000_000  # stay within the 10 ms tick so the UI always gets time
        executed = 0
        result = "OK"
        breakpoint_line = None
        halted_before = cpu.halted
        # Up to 100 kHz an instruction runs only once all of its T-states have
        # elapsed, so its result appears exactly when it completes. In real time
        # (3.072 MHz) that is at most a few microseconds - far below the 10 ms
        # tick - so the cheaper "start when due" rule keeps the host fast enough.
        exact = clock_hz <= 100_000
        peek = cpu.peek_t_states

        check_pc = bool(breakpoint_addresses) or verbose
        pc = regs["PC"]

        while cpu.t_states < target:
            if exact:
                needed = peek()
                if needed is not None and cpu.t_states + needed > target:
                    break
            if check_pc:
                pc = regs["PC"]
                if pc in breakpoint_addresses and not self.skip_breakpoint_once:
                    breakpoint_line = address_to_line[pc]
                    break
                self.skip_breakpoint_once = False
            result = step()
            if result != "OK":
                if result == "HALT":
                    if not (halted_before and executed == 0):  # not an idle HALT cycle
                        executed += 1  # the HLT instruction itself
                        if verbose:
                            self._log_executed_step(pc, result)
                    if cpu.interrupt_enable:
                        # HALT state with INTE set: the clock keeps running while
                        # the CPU waits for an interrupt
                        cpu.idle(target - cpu.t_states)
                        result = "OK"
                        if not self.halt_wait_logged:
                            self.halt_wait_logged = True
                            self.add_to_log(
                                "CPU halted - waiting for an interrupt (the clock keeps running)",
                                "SYSTEM",
                            )
                        if cpu.pending_interrupt(sampled=True) is not None:
                            # A chip output (e.g. an 8253 OUT) raised an interrupt
                            # during HALT: acknowledge it at that very T-state
                            continue
                elif verbose:
                    self._log_executed_step(pc, result)
                break
            executed += 1
            if verbose:
                self._log_executed_step(pc, result)
            if not executed & 0x3FF and self.realtime_clock.nsecsElapsed() > deadline_ns:
                break

        if executed:
            self.skip_breakpoint_once = False

        # "Left the program" warning, sampled once per tick to keep the loop fast
        if not self.outside_program_warned and not cpu.halted:
            pc = regs["PC"]
            if pc not in address_to_line and cpu.last_address not in address_to_line:
                self.outside_program_warned = True
                self.add_to_log(
                    f"PC at {pc:04X}H is outside the assembled program - executing raw memory contents",
                    "SYSTEM",
                )

        if verbose:
            self._report_interrupts()
        else:
            self._report_interrupts(summarize=True)
        self.execution_count += executed
        self.realtime_executed_tstates += cpu.t_states - start_tstates
        self.realtime_wall_ns = self.realtime_clock.nsecsElapsed()

        # Refresh the display after every instruction in slow-motion Run, about
        # 20 times per second otherwise, and whenever the run stops
        stopping = breakpoint_line is not None or result != "OK"
        if (
            stopping
            or (verbose and executed)
            or self.realtime_wall_ns - self.realtime_last_refresh_ns >= 50_000_000
        ):
            self.realtime_last_refresh_ns = self.realtime_wall_ns
            self.update_statistics()
            self.update_registers_display()
            self.update_memory_view()
            if verbose and executed and not stopping:
                self.highlight_current_instruction()

        if breakpoint_line is not None:
            self.add_to_log(f"Breakpoint hit at line {breakpoint_line}", "SYSTEM")
            self.stop_execution()
            self.code_editor.highlightExecutedLine(breakpoint_line - 1)
        elif result == "HALT":
            if not verbose:
                self.add_to_log(f"{cpu.last_address:04X}: {cpu.last_instruction}", "HALT")
            self.set_status("Program halted", "warning")
            self.stop_execution()
            self.highlight_current_instruction()
        elif result == "ERROR":
            if not verbose:
                self.add_to_log(f"{cpu.last_address:04X}: {cpu.last_instruction}", "ERROR")
            self.set_status(f"Error: {cpu.error}", "error")
            self.stop_execution()
            self.highlight_current_instruction()

    # Former name of execute_clock_slice
    execute_realtime_slice = execute_clock_slice

    def _log_executed_step(self, pc, result):
        """Log one executed instruction or interrupt acknowledge (slow-motion Run)."""
        cpu = self.processor
        if cpu.last_interrupt is not None:
            self._report_interrupts()
        else:
            self.add_to_log(f"{pc:04X}: {cpu.last_instruction}", result)
            if not self.outside_program_warned and pc not in cpu.address_to_line_map:
                self.outside_program_warned = True
                self.add_to_log(
                    f"PC at {pc:04X}H is outside the assembled program - executing raw memory contents",
                    "SYSTEM",
                )
        self._record_io(log=True)
        self._record_bus_cycles(pc)

    # ------------------------------------------------------------------
    # Resizable / hideable panes
    # ------------------------------------------------------------------

    # pane key -> (splitter attribute, index of the pane in it)
    _PANES = {
        "lower": ("left_splitter", 1),
        "log": ("lower_splitter", 0),
        "tabs": ("lower_splitter", 1),
        "right": ("content_splitter", 1),
    }

    def _setup_pane_splitters(self):
        self._saved_pane_sizes = {}
        self._layout_initialized = False
        # Starting width ratio: editor side / registers and memory side
        self._content_ratio = (2, 1)
        for splitter in (self.content_splitter, self.left_splitter, self.lower_splitter):
            splitter.on_double_click = self._restore_split
            splitter.splitterMoved.connect(lambda _pos, _index: self._sync_pane_actions())
        self._default_pane_sizes = None

    def _pane_shown(self, key):
        splitter_name, index = self._PANES[key]
        return getattr(self, splitter_name).sizes()[index] > 0

    def _sync_pane_actions(self):
        """Keeps the View menu checkmarks in step with panes hidden or shown by dragging."""
        if not hasattr(self, "pane_actions"):
            return
        for key, action in self.pane_actions.items():
            shown = self._pane_shown(key)
            if action.isChecked() != shown:
                action.blockSignals(True)
                action.setChecked(shown)
                action.blockSignals(False)

    def set_pane_visible(self, key, shown):
        """Shows or hides a pane (View menu), restoring its previous size when shown."""
        splitter_name, index = self._PANES[key]
        splitter = getattr(self, splitter_name)
        sizes = splitter.sizes()
        if shown == (sizes[index] > 0):
            return
        total = sum(sizes)
        if not shown:
            self._saved_pane_sizes[key] = sizes[index]
            sizes[index] = 0
        else:
            size = self._saved_pane_sizes.get(key) or max(total // 3, 120)
            size = min(size, max(total - 60, 1))
            others = [i for i in range(len(sizes)) if i != index]
            remaining = total - size
            share = sum(sizes[i] for i in others) or len(others)
            for i in others:
                sizes[i] = max(1, remaining * (sizes[i] or 1) // share)
            sizes[index] = size
        splitter.setSizes(sizes)
        self._sync_pane_actions()

    # Starting proportions: editor / lower panes, and log / side tabs
    EDITOR_LOWER_RATIO = (1, 1)
    LOG_TABS_RATIO = (1, 1)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._layout_initialized:
            # Set the starting split once the window has its real size (the
            # side tabs' size hints would otherwise squeeze the editor)
            self._layout_initialized = True
            QTimer.singleShot(0, self._initial_layout)

    def _initial_layout(self):
        if not self.restore_pane_layout():
            self._apply_layout()

    # Pane sizes are remembered between sessions

    LAYOUT_KEY = "layout/panes"
    LAYOUT_VERSION = 1

    @staticmethod
    def _settings():
        """
        Per-user settings (the registry on Windows). NEO8085_SETTINGS_FILE can
        point to an INI file instead, e.g. to keep test runs separate.
        """
        path = os.environ.get("NEO8085_SETTINGS_FILE")
        if path:
            return QSettings(path, QSettings.Format.IniFormat)
        return QSettings("Neo8085", "Neo8085")

    def _layout_splitters(self):
        return {"content": self.content_splitter, "left": self.left_splitter, "lower": self.lower_splitter}

    def save_pane_layout(self):
        """Stores the pane sizes (as proportions, hidden panes as 0) and the sizes hidden panes return to."""
        if not self._layout_initialized:
            return
        data = {"version": self.LAYOUT_VERSION}
        for name, splitter in self._layout_splitters().items():
            sizes = splitter.sizes()
            total = sum(sizes)
            if not total:
                return  # not laid out (e.g. never shown): keep what was saved before
            data[name] = [size / total for size in sizes]
        data["restore"] = {}
        for key, size in self._saved_pane_sizes.items():
            splitter_name, _ = self._PANES[key]
            total = sum(getattr(self, splitter_name).sizes()) or 1
            data["restore"][key] = size / total
        settings = self._settings()
        settings.setValue(self.LAYOUT_KEY, json.dumps(data))
        settings.sync()

    def restore_pane_layout(self):
        """Applies the pane sizes saved in the last session. Returns False if there are none."""
        try:
            data = json.loads(self._settings().value(self.LAYOUT_KEY, "") or "{}")
        except (TypeError, ValueError):
            return False
        if data.get("version") != self.LAYOUT_VERSION:
            return False
        splitters = self._layout_splitters()
        layouts = {}
        for name, splitter in splitters.items():
            fractions = data.get(name)
            if (not isinstance(fractions, list) or len(fractions) != splitter.count()
                    or not all(isinstance(f, (int, float)) and 0 <= f <= 1 for f in fractions)
                    or sum(fractions) <= 0):
                return False
            layouts[name] = fractions
        if layouts["left"][0] == 0:
            return False  # the editor is never hidden
        for name, fractions in layouts.items():
            splitter = splitters[name]
            total = sum(splitter.sizes()) or 1
            splitter.setSizes([round(total * f) for f in fractions])
        self._saved_pane_sizes = {}
        for key, fraction in (data.get("restore") or {}).items():
            if key in self._PANES and isinstance(fraction, (int, float)) and 0 < fraction <= 1:
                splitter_name, _ = self._PANES[key]
                total = sum(getattr(self, splitter_name).sizes()) or 1
                self._saved_pane_sizes[key] = round(total * fraction)
        self._sync_pane_actions()
        return True

    def closeEvent(self, event):
        self.save_pane_layout()
        super().closeEvent(event)

    def _apply_layout(self, include_content=True):
        splitters = [
            (self.left_splitter, self.EDITOR_LOWER_RATIO),
            (self.lower_splitter, self.LOG_TABS_RATIO),
        ]
        if include_content:
            splitters.insert(0, (self.content_splitter, self._content_ratio))
        for splitter, ratios in splitters:
            total = sum(splitter.sizes()) or 1
            splitter.setSizes([total * r // sum(ratios) for r in ratios])
        self._saved_pane_sizes.clear()
        self._sync_pane_actions()

    def _restore_split(self, splitter, _index):
        """Double-click on a divider: show the panes on both sides with their starting proportions."""
        ratios = {
            self.content_splitter: self._content_ratio,
            self.left_splitter: self.EDITOR_LOWER_RATIO,
            self.lower_splitter: self.LOG_TABS_RATIO,
        }[splitter]
        total = sum(splitter.sizes()) or 1
        splitter.setSizes([total * r // sum(ratios) for r in ratios])
        for key, (name, _) in self._PANES.items():
            if getattr(self, name) is splitter:
                self._saved_pane_sizes.pop(key, None)
        self._sync_pane_actions()

    def reset_layout(self):
        """Shows all panes again with their starting proportions."""
        self._apply_layout()

    def _wait_in_halt_for_chip(self, limit=50_000_000):
        """Step mode: let the clock run in HALT until a wired chip output raises an interrupt."""
        cpu = self.processor
        start = cpu.t_states
        while cpu.t_states - start < limit:
            if cpu.pending_interrupt(sampled=True) is not None:
                waited = cpu.t_states - start
                self.add_to_log(
                    f"HALT: waited {waited} T-states until a peripheral raised an interrupt", "SYSTEM"
                )
                self.update_statistics()
                return True
            if cpu._io_deadline == float("inf") and cpu.pending_interrupt() is None:
                return False  # nothing that could wake the CPU
            if cpu.idle(limit - (cpu.t_states - start)) == 0:
                return False
        return False

    # ------------------------------------------------------------------
    # 8255 / 8253
    # ------------------------------------------------------------------

    def after_peripheral_change(self):
        """Refresh everything a chip or its wiring may have changed."""
        self.update_peripheral_display(force=True)
        self.update_interrupt_display()
        self._after_pin_change()

    def update_peripheral_display(self, force=False):
        """Refreshes the 8255/8253 panel that is on screen (or both with force)."""
        if not hasattr(self, "pit_panel"):
            return
        if not force and (self.side_tabs.width() == 0 or self.side_tabs.height() == 0):
            return  # the side tabs are collapsed: nothing on screen to refresh
        current = self.side_tabs.currentWidget()
        panels = [p for p in (self.ppi_panel, self.pit_panel) if force or p is current]
        if not panels:
            return
        self.peripherals.sync(self.processor.t_states)
        for panel in panels:
            panel.refresh()

    def set_peripheral_wiring(self, source, pin):
        self._sync_clock()
        self.peripherals.set_wiring(source, pin)
        target = pin.replace("RST", "RST ") if pin else "nothing"
        self.add_to_log(f"{source} connected to {target}", "SYSTEM")
        self.after_peripheral_change()

    def set_counter_source(self, index, source):
        self._sync_clock()
        bus = self.peripherals
        bus.sync(self.processor.t_states)
        bus.pit.sources[index] = source
        bus.pit._phase[index] = 0
        bus._update_deadline()
        label = {"CLK OUT": "CPU CLK OUT", "CLK OUT / 2": "CPU CLK OUT / 2",
                 "OUT of previous counter": f"OUT{index - 1}"}.get(source, source)
        self.add_to_log(f"8253 counter {index} CLK from {label}", "SYSTEM")
        self.after_peripheral_change()

    def set_counter_gate(self, index, level):
        self._sync_clock()
        self.peripherals.set_gate(index, level)
        self.add_to_log(f"8253 GATE{index} {'HIGH' if level else 'LOW'}", "SYSTEM")
        self.after_peripheral_change()

    def pulse_counter_clock(self, index):
        self._sync_clock()
        self.peripherals.manual_clock(index)
        out = self.peripherals.pit.counters[index].out
        self.add_to_log(f"8253 CLK{index} pulse - OUT{index} = {out}", "SYSTEM")
        self.after_peripheral_change()

    def _apply_example_setup(self, example):
        """Board wiring and clock sources an example program expects."""
        bus = self.peripherals
        setup = example.setup
        bus.wiring = dict(setup.get("wiring", {}))
        for index in range(3):
            bus.pit.sources[index] = setup.get("sources", {}).get(index, "CLK OUT")
            bus.pit._phase[index] = 0
        bus._drive_pins()
        bus._update_deadline()
        for source, pin in bus.wiring.items():
            self.add_to_log(f"Board set-up: {source} connected to {pin.replace('RST', 'RST ')}", "SYSTEM")
        self.update_peripheral_display(force=True)

    def _record_bus_cycles(self, pc):
        """Adds the machine cycles of the last step to the Bus Cycles panel."""
        cpu = self.processor
        if cpu.trace_bus and cpu.bus_cycles:
            if cpu.last_interrupt is not None:
                title = cpu.last_instruction
            else:
                title = f"{pc:04X}: {cpu.last_instruction}"
            self.bus_panel.add_record(title, cpu.bus_cycles)

    def _update_trace_note(self):
        """Tells the user when a run is too fast for machine cycles to be recorded."""
        if self.use_highlighting:
            self.bus_panel.set_trace_note("")
        else:
            self.bus_panel.set_trace_note(
                f"Machine cycles are not recorded at {format_frequency(self.clock_hz)}. "
                f"Step (F10), use Run (F5), or choose a CPU clock of "
                f"{VISUAL_CLOCK_LIMIT_HZ} Hz or less to record them."
            )

    def show_timing_diagram(self):
        """Opens the timing diagram window for the selected (or last) instruction."""
        self.bus_panel.show_diagram_window()

    def _sync_clock(self):
        """
        Before an external input changes during a run, execute the CPU up to
        the current clock cycle, so the change takes effect at the right T-state
        instead of at the next timer tick.
        """
        if self.running:
            self.execute_clock_slice()

    def _input_time(self):
        """
        T-state of an input change made now (a button, switch or pin), or None
        when the clock is stopped (step mode: the change is there before the
        next instruction). The CPU uses it to sample interrupts in the
        next-to-last clock cycle of an instruction.
        """
        if not (self.running and self.run_mode):
            return None
        elapsed_ns = self.realtime_clock.nsecsElapsed()
        return int(self.realtime_start_tstates + (elapsed_ns * self.clock_hz) // 1_000_000_000)

    def realtime_speed_percent(self):
        """Achieved emulation speed relative to the run's CPU clock frequency."""
        if self.realtime_wall_ns <= 0:
            return 0.0
        simulated_ns = self.realtime_executed_tstates * 1_000_000_000 / self.clock_hz
        return 100.0 * simulated_ns / self.realtime_wall_ns

    def update_statistics(self):
        """Update instruction count and T-state/simulated-time display."""
        self.instr_count_label.setText(f"Instructions: {self.execution_count}")
        self.tstate_label.setText(f"T-States: {self.processor.t_states}")
        self.update_elapsed_time_display()
        if self.running and self.run_mode:
            clock = format_frequency(self.clock_hz)
            if self.processor.halted:
                self.set_status(
                    f"HALT - waiting for an interrupt (INTE = 1), clock running @ {clock}", "warning"
                )
            elif self.realtime:
                self.set_status(
                    f"Running in real time @ {clock} ({self.realtime_speed_percent():.0f}% speed)",
                    "success",
                )
            else:
                description = self._run_modes()[self.run_mode][2]
                self.set_status(f"Running @ {clock} ({description})", "success")

    def parse_address(self, addr_text):
        """Parse address text using 8085 conventions.
        - With 'H' or 'h' suffix: hexadecimal
        - Otherwise: decimal
        Returns the parsed integer address.
        """
        addr_text = addr_text.strip()
        if addr_text.upper().endswith("H"):
            try:
                return int(addr_text[:-1], 16)
            except ValueError:
                raise ValueError(f"Invalid hexadecimal address: {addr_text}")
        else:
            try:
                return int(addr_text, 10)
            except ValueError:
                raise ValueError(f"Invalid decimal address: {addr_text}")

    def load_memory_display(self, base_addr=0x0000):
        """Load memory view starting at base_addr"""
        # Address is aligned to 16-byte boundary; the 16-row view must not run past FFFFH
        base_addr = min(base_addr & 0xFFF0, 0xFF00)

        for row in range(16):
            row_addr = base_addr + (row * 16)
            self.memory_table.setItem(row, 0, QTableWidgetItem(f"{row_addr}"))
            self.memory_table.setItem(row, 1, QTableWidgetItem(f"{row_addr:04X}H"))

            for col in range(16):
                addr = row_addr + col
                value = (
                    self.processor.memory[addr]
                    if hasattr(self.processor, "memory")
                    else 0
                )
                self.memory_table.setItem(
                    row, col + 2, QTableWidgetItem(f"{value:02X}")
                )

    def load_memory_address(self):
        """Jump to a specific memory address in the memory view"""
        addr_text = self.memory_search.text().strip()
        if not addr_text:
            return

        try:
            base_addr = self.parse_address(addr_text)

            if base_addr < 0:
                base_addr = 0
                self.add_to_log("Address adjusted to minimum (0)", "SYSTEM")
            elif base_addr > 0xFFFF:
                base_addr = 0xFFFF
                self.add_to_log("Address adjusted to maximum (65535/FFFFH)", "SYSTEM")

            # Near the end of memory, show the last full 256-byte page
            if base_addr > 0xFF00:
                base_addr = 0xFF00
                self.add_to_log(
                    "Address adjusted to show last memory page (65280/FF00H)", "SYSTEM"
                )

            self.user_memory_addr = base_addr
            self.follow_pc = (
                False  # an address was requested: stop following PC
            )
            self.follow_pc_button.setChecked(False)
            self.load_memory_display(base_addr)

            if addr_text.upper().endswith("H"):
                self.add_to_log(f"Viewing memory at {base_addr:04X}H (hex)", "SYSTEM")
            else:
                self.add_to_log(f"Viewing memory at {base_addr} (decimal)", "SYSTEM")

        except ValueError as e:
            self.memory_search.setText("Invalid Address")
            self.memory_search.selectAll()
            self.add_to_log(f"Error: {str(e)}", "ERROR")

    def validate_memory_address(self, text):
        """Validate memory address input as user types"""
        if not text:
            return

        if text.upper().endswith("H"):
            hex_val = text[:-1]
            try:
                value = int(hex_val, 16)
                if value > 0xFFFF:
                    self.memory_search.setText(hex_val[:-1] + text[-1])
            except ValueError:
                # the validator rejects invalid characters
                pass
        else:
            try:
                value = int(text)
                if value > 65535:
                    self.memory_search.setText(text[:-1])
            except ValueError:
                # the validator rejects invalid characters
                pass

    def compile_program(self):
        """Assembles the editor contents and loads the program into a fresh processor."""
        code = self.code_editor.toPlainText().splitlines()

        try:
            assembler = Assembler8085()
            assembly_output = assembler.assemble(code)

            self.processor = Processor8085()
            self.processor.load_program(assembly_output)
            self.peripherals.power_on()
            self._apply_devices()

            self.update_registers_display()
            self.code_editor.updateLineNumberAreaWidth(0)
            # The ORG address in the search field makes switching between it and Follow PC easy
            self.memory_search.setText(f"{assembly_output.starting_address:04X}H")
            self.memory_enter_button.click()

            self.add_to_log("Program assembled successfully", "SYSTEM")
            self.add_to_log("Machine code loaded into memory", "SYSTEM")
            self.set_status("Assembled - Ready to Execute", "success")

            self.execution_count = 0
            self.instr_count_label.setText("Instructions: 0")
            self.tstate_label.setText("T-States: 0")
            self.outside_program_warned = False
            self.reset_elapsed_timer()
            self.bus_panel.clear()

            self.highlight_current_instruction()

            return True

        except SyntaxError as e:
            error_msg = str(e)
            self.add_to_log(f"Assembly error: {error_msg}", "ERROR")
            self.set_status("Assembly Failed: Syntax Error", "error")

            QMessageBox.critical(self, "Assembly Error", error_msg)
            return False

        except Exception as e:
            self.add_to_log(f"Assembly error: {str(e)}", "ERROR")
            self.set_status("Assembly Failed: Unknown Error", "error")

            QMessageBox.critical(
                self, "Assembly Error", f"An unexpected error occurred:\n{str(e)}"
            )
            return False

    def execute_single_step(self):
        """Execute a single instruction"""
        if (
                not hasattr(self.processor, "parsed_program")
                or not self.processor.parsed_program
        ):
            self.compile_program()
            return

        # A halted CPU only continues when an interrupt is acknowledged. In
        # step mode, a HALT with interrupts enabled waits for the next interrupt
        # from a chip output wired to an interrupt pin (e.g. an 8253 timer)
        if (not self.running and self.processor.halted and self.processor.interrupt_enable
                and self.processor.pending_interrupt() is None):
            self._wait_in_halt_for_chip()
        if self.processor.halted and self.processor.pending_interrupt() is None:
            if self.running and self.processor.interrupt_enable:
                # Stay in HALT and wait for an interrupt
                self.set_status("HALT - waiting for an interrupt (INTE = 1)", "warning")
            elif self.running:
                self.stop_execution()
            else:
                self.add_to_log(
                    "CPU is halted - raise an interrupt (Interrupts tab) or Reset to continue",
                    "SYSTEM",
                )
            return "HALT"

        self.start_elapsed_timer()

        last_pc = self.processor.registers["PC"]
        last_line_num = self.processor.address_to_line_map.get(last_pc)

        # Check for breakpoints when running continuously. The instruction the
        # run was started from is always executed, so Run can resume from a
        # breakpoint instead of stopping on it again immediately.
        skip_breakpoint = self.skip_breakpoint_once
        self.skip_breakpoint_once = False
        if (
                self.running
                and not skip_breakpoint
                and last_line_num is not None
                and (last_line_num - 1) in self.code_editor.breakpoints
        ):
            self.add_to_log(f"Breakpoint hit at line {last_line_num}", "SYSTEM")
            self.stop_execution()
            # Always highlight on breakpoint hit, even in fast mode
            self.code_editor.highlightExecutedLine(
                last_line_num - 1
            )  # Convert to 0-indexed for highlighting
            return

        # The CPU executes whatever is in memory; let the user know when PC
        # has left the assembled program (e.g. ran into a DS area or past the end)
        if last_line_num is None and not self.outside_program_warned:
            self.outside_program_warned = True
            self.add_to_log(
                f"PC at {last_pc:04X}H is outside the assembled program - "
                f"executing raw memory contents",
                "SYSTEM",
            )

        # Record the machine cycles for the Bus Cycles tab
        self.processor.trace_bus = True
        result = self.processor.step()
        self._record_bus_cycles(last_pc)

        self.highlight_current_instruction()

        self.execution_count += 1
        self.update_statistics()

        # In single-step mode the timer only runs during the step
        if not hasattr(self, "running") or not self.running:
            self.stop_elapsed_timer()

        # Log interrupts always, instructions only in slow-motion runs or when they stop the run
        if self.processor.last_interrupt is not None:
            self._report_interrupts()
        elif self.processor.last_instruction and (
                self.use_highlighting or result != "OK"
        ):
            self.add_to_log(f"{last_pc:04X}: {self.processor.last_instruction}", result)
        self._record_io(log=self.use_highlighting)

        self.update_registers_display()
        self.update_memory_view()

        if result == "HALT":
            if self.running and self.processor.interrupt_enable:
                # HLT with interrupts enabled: the CPU waits for an interrupt
                self.set_status("HALT - waiting for an interrupt (INTE = 1)", "warning")
                self.add_to_log("CPU halted - waiting for an interrupt", "SYSTEM")
            else:
                self.set_status("Program halted", "warning")
                self.stop_execution()
            # Show where execution ended, even in fast mode
            self.highlight_current_instruction()
        elif result == "ERROR":
            self.set_status(f"Error: {self.processor.error}", "error")
            self.stop_execution()
            self.highlight_current_instruction()

        return result

    def highlight_current_instruction(self):
        """Highlight current instruction"""
        # After HLT the PC points past the HLT instruction, so keep the HLT
        # line highlighted instead.
        current_pc = self.processor.registers["PC"]
        if self.processor.halted and self.processor.last_address is not None:
            current_pc = self.processor.last_address
        line_num = self.processor.address_to_line_map.get(current_pc)

        if self.use_highlighting and line_num is not None:
            self.code_editor.highlightExecutedLine(
                line_num - 1
            )  # Convert to 0-indexed for highlighting

    def start_continuous_execution(self):
        """Run with highlighting, on a slow-motion RUN_CLOCK_HZ CPU clock."""
        self._start_clocked_run("run")

    def stop_execution(self):
        """Stop continuous execution"""
        if self.running:
            self._report_interrupts(summarize=True)
            self._flush_interrupt_summary(force=True)
        was_realtime = self.realtime and self.running
        self.running = False
        self.realtime_timer.stop()
        self.realtime = False
        self.run_mode = None

        self.stop_elapsed_timer()

        self.use_highlighting = True
        self.bus_panel.set_trace_note("")

        self._set_running_ui(False)

        if was_realtime and self.realtime_wall_ns > 0:
            self.add_to_log(
                f"Real-time run @ {format_frequency(self.clock_hz)}: "
                f"{self.realtime_executed_tstates} T-states "
                f"({self.realtime_executed_tstates * 1000 / self.clock_hz:.3f} ms of CPU time) "
                f"at {self.realtime_speed_percent():.0f}% of the clock speed",
                "SYSTEM",
            )

        if not self.processor.halted and not self.processor.error:
            self.set_status("Execution Paused", "warning")
            self.add_to_log("Execution paused", "SYSTEM")

    def update_memory_view(self):
        """Update memory view based on current state"""
        pc = self.processor.registers["PC"]

        if self.follow_pc:
            base_addr = pc & 0xFFF0
            self.load_memory_display(base_addr)
        else:
            self.update_memory_values()

    def update_memory_values(self):
        """Update memory values without changing the current view"""
        try:
            base_addr_text = self.memory_table.item(0, 1).text()

            if base_addr_text.upper().endswith("H"):
                base_addr = int(base_addr_text[:-1], 16)
            else:
                base_addr = int(base_addr_text, 16)

            # Only the byte columns (2-17) change
            for row in range(16):
                row_addr = base_addr + (row * 16)

                for col in range(16):
                    addr = row_addr + col
                    value = self.processor.memory[addr]
                    self.memory_table.item(row, col + 2).setText(f"{value:02X}")
        except (ValueError, AttributeError) as e:
            # The table may not be set up yet
            self.add_to_log(f"Memory view update error: {str(e)}", "ERROR")

    def add_breakpoint(self):
        """Add breakpoint at the current line if not empty"""
        cursor = self.code_editor.textCursor()
        line_num = cursor.blockNumber()

        # Only lines with code can have a breakpoint
        block_text = (
            self.code_editor.document().findBlockByNumber(line_num).text().strip()
        )
        if block_text and not block_text.startswith(";"):
            if line_num in self.code_editor.breakpoints:
                self.add_to_log(
                    f"Breakpoint already exists at line {line_num + 1}", "SYSTEM"
                )
            else:
                self.code_editor.toggleBreakpoint(line_num)
                self.add_to_log(f"Breakpoint added at line {line_num + 1}", "SYSTEM")
        else:
            self.add_to_log(
                "Cannot add breakpoint on empty line or comment-only line", "ERROR"
            )

    def remove_breakpoint(self):
        """Remove breakpoint from the current line if one exists"""
        cursor = self.code_editor.textCursor()
        line_num = cursor.blockNumber()

        if line_num in self.code_editor.breakpoints:
            self.code_editor.toggleBreakpoint(line_num)
            self.add_to_log(f"Breakpoint removed from line {line_num + 1}", "SYSTEM")
        else:
            self.add_to_log("No breakpoint on current line", "SYSTEM")

    def remove_all_breakpoints(self):
        """Remove all breakpoints"""
        if self.code_editor.breakpoints:
            self.code_editor.breakpoints.clear()
            self.code_editor.lineNumberArea.update()
            self.add_to_log("All breakpoints removed", "SYSTEM")
        else:
            self.add_to_log("No breakpoints to remove", "SYSTEM")

    def add_to_log(self, message, status="OK"):
        """Add a message to the execution log"""
        timestamp = QDateTime.currentDateTime().toString("hh:mm:ss")

        status_color = {
            "OK": "#00AA00",
            "HALT": "#AAAA00",
            "ERROR": "#AA0000",
            "SYSTEM": "#00AAAA",
        }.get(status, "white")

        log_entry = f"<span style='color:{status_color}'>[{timestamp}] {message}</span>"

        # Append only (the widget keeps the last LOG_VISIBLE_ENTRIES lines): rebuilding
        # the whole log for every message is slow when messages are frequent, e.g. timer
        # interrupts
        self.execution_log.append(log_entry)
        if len(self.execution_log) > LOG_HISTORY_ENTRIES:
            del self.execution_log[: len(self.execution_log) - LOG_HISTORY_ENTRIES // 2]
        # Shown with the hex values (and binary bytes) in a fixed-width font
        shown = _HEX_TOKEN_RE.sub(_hex_span, message)
        self.execution_log_widget.append(f"<span style='color:{status_color}'>[{timestamp}] {shown}</span>")

        self.execution_log_widget.verticalScrollBar().setValue(
            self.execution_log_widget.verticalScrollBar().maximum()
        )

    def clear_execution_log(self):
        """Clear execution log"""
        self.execution_log.clear()
        self.execution_log_widget.clear()

    def show_editor_context_menu(self, pos):
        """Show context menu for the code editor"""
        cursor = self.code_editor.cursorForPosition(pos)
        line_num = cursor.blockNumber()

        menu = QMenu(self)

        if line_num in self.code_editor.breakpoints:
            action = menu.addAction("Remove Breakpoint")
        else:
            action = menu.addAction("Add Breakpoint")

        action.triggered.connect(lambda: self.toggle_breakpoint(line_num))
        menu.exec(self.code_editor.viewport().mapToGlobal(pos))

    def toggle_breakpoint(self, line_num):
        """Toggle breakpoint at the specified line"""
        # Only lines with code can have a breakpoint
        block_text = (
            self.code_editor.document().findBlockByNumber(line_num).text().strip()
        )
        if block_text and not block_text.startswith(";"):
            self.code_editor.toggleBreakpoint(line_num)
        else:
            self.add_to_log(
                "Cannot add breakpoint on empty line or comment-only line", "ERROR"
            )

    def save_program(self):
        """Save the current program to the current file or prompt for location"""
        if self.current_file:
            return self.save_to_file(self.current_file)
        else:
            return self.save_program_as()

    def save_program_as(self):
        """Save the program to a new file"""
        from PySide6.QtWidgets import QFileDialog

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Assembly Program", "", "Assembly Files (*.asm);;All Files (*.*)"
        )

        if file_path:
            return self.save_to_file(file_path)
        return True  # User canceled

    def save_to_file(self, file_path):
        """Save content to the specified file"""
        try:
            with open(file_path, "w") as f:
                f.write(self.code_editor.toPlainText())

            self.current_file = file_path
            self.document_modified = False
            self.update_window_title()
            self.add_to_log(f"Program saved to {file_path}", "SYSTEM")
            return False  # No errors
        except Exception as e:
            self.add_to_log(f"Error saving program: {str(e)}", "ERROR")
            QMessageBox.critical(
                self, "Save Error", f"Could not save the file:\n{str(e)}"
            )
            return True  # Error occurred

    def load_program(self):
        """Load a program from a file"""
        if self.check_save_current():
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self, "Open Assembly Program", "", "Assembly Files (*.asm);;All Files (*.*)"
        )

        if file_path:
            try:
                with open(file_path, "r") as f:
                    content = f.read()

                self.code_editor.setPlainText(content)
                self.current_file = file_path
                self.document_name = None
                self.document_modified = False
                self.update_window_title()
                self.add_to_log(f"Program loaded from {file_path}", "SYSTEM")

                self.reset_simulation()

            except Exception as e:
                self.add_to_log(f"Error loading program: {str(e)}", "ERROR")
                QMessageBox.critical(
                    self, "Load Error", f"Could not load the file:\n{str(e)}"
                )

    def load_example(self, example):
        """Loads an example program into the editor and assembles it."""
        if self.document_modified and self.check_save_current():
            return
        self.reset_simulation()
        self.code_editor.setPlainText(example.source)
        self.current_file = None
        self.document_name = f"Example - {example.title}"
        self.document_modified = False
        self.update_window_title()
        self.setWindowTitle(f"Neo8085 v{display_version} - Example: {example.title}")
        self.add_to_log(f"Example loaded: {example.title}", "SYSTEM")
        self._apply_example_setup(example)
        if self.compile_program():
            self.add_to_log(f"How to run: {example.hint}", "SYSTEM")

    # ------------------------------------------------------------------
    # Opcode listing, Intel HEX and printing
    # ------------------------------------------------------------------

    def _document_title(self):
        if self.current_file:
            return os.path.basename(self.current_file)
        return self.document_name or "Untitled"

    def _default_path(self, extension):
        """Suggested file name for an export: the program's name with a new extension."""
        if self.current_file:
            return os.path.splitext(self.current_file)[0] + extension
        name = self.document_name or "program"
        if name.lower().endswith(".asm"):
            name = name[:-4]
        name = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in name).strip() or "program"
        return name + extension

    def _assemble_editor(self, purpose):
        """
        Assembles the editor contents without touching the running simulation.
        Returns the AssemblyOutput, or None after reporting the error.
        """
        try:
            return Assembler8085().assemble(self.code_editor.toPlainText().splitlines())
        except SyntaxError as e:
            self.add_to_log(f"{purpose}: assembly error: {e}", "ERROR")
            QMessageBox.critical(self, "Assembly Error", f"{purpose} needs a program that assembles.\n\n{e}")
        except Exception as e:  # defensive
            self.add_to_log(f"{purpose}: {e}", "ERROR")
            QMessageBox.critical(self, "Assembly Error", f"An unexpected error occurred:\n{e}")
        return None

    def _listing(self):
        output = self._assemble_editor("Opcode listing")
        if output is None:
            return None, None
        return output, build_listing(output, self._document_title())

    def show_listing(self):
        """Assembles the program and shows its opcode listing (Ctrl+L)."""
        output, text = self._listing()
        if output is None:
            return False
        if self.listing_window is None:
            self.listing_window = ListingWindow(self)
        title = self._document_title()
        self.listing_window.set_listing(
            text,
            title,
            f"{title}: {len(output.source_lines)} lines, {len(output.object_addresses)} bytes of "
            f"object code, start address {output.starting_address:04X}H",
        )
        self.listing_window.show()
        self.listing_window.raise_()
        self.listing_window.activateWindow()
        self.add_to_log("Opcode listing generated", "SYSTEM")
        return True

    def save_listing(self):
        """Saves the opcode listing as a text file."""
        output, text = self._listing()
        if output is None:
            return False
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Listing", self._default_path(".lst"),
            "Listing Files (*.lst);;Text Files (*.txt);;All Files (*.*)",
        )
        if not file_path:
            return False
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError as e:
            self.add_to_log(f"Error saving listing: {e}", "ERROR")
            QMessageBox.critical(self, "Save Error", f"Could not save the listing:\n{e}")
            return False
        self.add_to_log(f"Listing saved to {file_path}", "SYSTEM")
        return True

    def print_listing(self):
        """Prints the opcode listing (Ctrl+P)."""
        output, text = self._listing()
        if output is None:
            return False
        title = f"Listing of {self._document_title()}"
        if print_text(self, text, title, SOURCE_COLUMN):
            self.add_to_log(f"{title} sent to the printer", "SYSTEM")
            return True
        return False

    def export_intel_hex(self, with_start=False):
        """
        Saves the assembled object code as an Intel HEX file (Ctrl+E): Intel's
        8-bit format (data and end-of-file records). with_start adds a Start
        Segment Address record with the program's start address.
        """
        output = self._assemble_editor("Intel HEX export")
        if output is None:
            return False
        addresses = output.object_addresses
        if not addresses:
            QMessageBox.information(self, "Export Intel HEX", "The program produces no object code to export.")
            return False
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export Intel HEX", self._default_path(".hex"),
            "Intel HEX Files (*.hex *.ihx);;All Files (*.*)",
        )
        if not file_path:
            return False
        text = to_intel_hex(output.memory, addresses, start=output.starting_address if with_start else None)
        try:
            # Intel HEX files traditionally use CR LF line endings
            with open(file_path, "w", encoding="ascii", newline="\r\n") as f:
                f.write(text)
        except OSError as e:
            self.add_to_log(f"Error writing Intel HEX file: {e}", "ERROR")
            QMessageBox.critical(self, "Export Error", f"Could not write the file:\n{e}")
            return False
        records = text.count(":") - 1 - (1 if with_start else 0)
        start_note = "start address record included" if with_start else "8-bit format, no start record"
        self.add_to_log(
            f"Intel HEX written to {file_path}: {len(addresses)} bytes in {records} data records "
            f"(program start {output.starting_address:04X}H; {start_note})",
            "SYSTEM",
        )
        return True

    def import_intel_hex(self):
        """Loads an Intel HEX file: disassembles it into the editor and assembles it (Ctrl+I)."""
        if self.document_modified and self.check_save_current():
            return False
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Import Intel HEX", "", "Intel HEX Files (*.hex *.ihx);;All Files (*.*)"
        )
        if not file_path:
            return False
        try:
            with open(file_path, "r", encoding="ascii", errors="replace") as f:
                data, start = parse_intel_hex(f.read())
        except (OSError, IntelHexError) as e:
            self.add_to_log(f"Cannot import {os.path.basename(file_path)}: {e}", "ERROR")
            QMessageBox.critical(self, "Import Intel HEX", f"Could not import the file:\n{e}")
            return False
        name = os.path.basename(file_path)
        self.reset_simulation()
        self.code_editor.setPlainText(hex_to_source(data, start, name))
        self.current_file = None
        self.document_name = os.path.splitext(name)[0] + ".asm"
        self.document_modified = False
        self.update_window_title()
        self.setWindowTitle(f"Neo8085 v{display_version} - {self.document_name} (from {name})")
        self.add_to_log(
            f"Intel HEX imported from {file_path}: {len(data)} bytes, disassembled into the editor", "SYSTEM"
        )
        self.compile_program()
        return True

    def new_file(self):
        """Create a new file, checking if current work should be saved"""
        if self.check_save_current():
            return  # User canceled

        self.code_editor.setPlainText("")
        self.reset_simulation()
        self.current_file = None
        self.document_name = None
        self.document_modified = False
        self.update_window_title()
        self.add_to_log("New file created", "SYSTEM")

    def check_save_current(self):
        """Check if current work should be saved before proceeding"""
        if self.code_editor.toPlainText().strip():
            reply = QMessageBox.question(
                self,
                "Save Changes?",
                "Do you want to save changes to the current program?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )

            if reply == QMessageBox.Save:
                return self.save_program()
            elif reply == QMessageBox.Cancel:
                return True  # User canceled operation

        return False  # No need to save or user discarded changes

    def zoom_in(self):
        self.menu_bar.zoom_in()
        self.code_editor.zoom_in()
        self.execution_log_widget.zoom_in()
        self.memory_table.zoom_in()
        for button in self.findChildren(PushButton):
            button.zoom_in()
        for label in self.findChildren(Label):
            label.zoom_in()
        for line_edit in self.findChildren(LineEdit):
            line_edit.zoom_in()

    def zoom_out(self):
        self.menu_bar.zoom_out()
        self.code_editor.zoom_out()
        self.execution_log_widget.zoom_out()
        self.memory_table.zoom_out()
        for button in self.findChildren(PushButton):
            button.zoom_out()
        for label in self.findChildren(Label):
            label.zoom_out()
        for line_edit in self.findChildren(LineEdit):
            line_edit.zoom_out()

    def reset_zoom(self):
        self.menu_bar.reset_zoom()
        self.code_editor.reset_zoom()
        self.execution_log_widget.reset_zoom()
        self.memory_table.reset_zoom()
        for button in self.findChildren(PushButton):
            button.reset_zoom()
        for label in self.findChildren(Label):
            label.reset_zoom()
        for line_edit in self.findChildren(LineEdit):
            line_edit.reset_zoom()

    def show_about(self):
        """Show about dialog"""
        QMessageBox.information(
            self,
            "About Neo8085",
            f"Neo8085 - 8085 Microprocessor Simulator\n\n"
            f"Copyright (C) 2026 Shahibur Rahaman\n"
            f"Licensed under the GNU General Public License v3.0\n\n"
            f"A simulator for the 8085 microprocessor.\n"
            f"Version: {version_string}\n\n"
            f"This program is free software: you can redistribute it and/or modify "
            f"it under the terms of the GNU General Public License as published by "
            f"the Free Software Foundation, either version 3 of the License, or "
            f"(at your option) any later version.\n\n"
            f"Intel is a trademark of Intel Corporation. Neo8085 is an independent "
            f"project and is not affiliated with or endorsed by Intel.",
        )

    def soft_reset(self):
        """
        Normal reset, like pressing RESET on an 8085 trainer: the CPU restarts
        at the program's start address with interrupts disabled. Registers,
        flags, the stack pointer and all memory keep their contents.
        """
        self.stop_execution()
        self.processor.reset()

        self.execution_count = 0
        self.outside_program_warned = False
        self.reset_elapsed_timer()
        self.update_statistics()
        self.update_registers_display()
        self.update_memory_view()

        start = self.processor.registers["PC"]
        self.set_status(f"Reset - PC = {start:04X}H (registers and memory kept)", "normal")
        self.add_to_log(f"CPU reset: PC = {start:04X}H, registers and memory kept", "SYSTEM")

        self.code_editor.highlightCurrentLine()
        self.highlight_current_instruction()

    def reset_simulation(self):
        """Full reset: clear registers, flags and all memory, unload the program"""
        self.stop_execution()

        # New processor; the external devices stay connected
        self.processor = Processor8085()
        self.peripherals.power_on()
        self._apply_devices()

        self.update_registers_display()
        self.load_memory_display(0x0000)
        self.memory_search.setText("")

        self.execution_count = 0
        self.instr_count_label.setText("Instructions: 0")
        self.tstate_label.setText("T-States: 0")
        self.outside_program_warned = False
        self.reset_elapsed_timer()
        self.bus_panel.clear()

        self.set_status("Full reset - Ready to Assemble", "normal")

        self.add_to_log("Full reset: registers, flags and memory cleared", "SYSTEM")

        self.code_editor.highlightCurrentLine()
        self.code_editor.updateLineNumberAreaWidth(0)

    def set_status(self, text, status_type="normal"):
        """Set status text with consistent styling

        Parameters:
        text (str): The status message to display
        status_type (str): One of 'normal', 'success', 'warning', 'error'
        """
        self.status_label.setText(text)

        base_style = """
            background-color: {bg_color};
            color: #1E1E1E; 
            padding: 4px; 
            border: 1px solid #DDDDDD;
            border-radius: 3px;
        """

        bg_colors = {
            "normal": "white",
            "success": "#DFF6DD",
            "warning": "#FFF4CE",
            "error": "#FDE7E9",
        }

        bg_color = bg_colors.get(status_type, "white")

        self.status_label.setStyleSheet(base_style.format(bg_color=bg_color))

    def toggle_follow_pc(self):
        """Toggle whether memory view should follow PC"""
        self.follow_pc = self.follow_pc_button.isChecked()
        if self.follow_pc:
            pc = self.processor.registers["PC"]
            self.load_memory_display(pc)
        else:
            self.load_memory_display(self.user_memory_addr)

    def _tool_form(self):
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(4)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return form

    @staticmethod
    def _tool_label(text):
        label = Label(text, font_family="Segoe UI", font_point_size=9)
        label.setStyleSheet("background: transparent; color: #212121;")
        return label

    @staticmethod
    def _tool_field(field):
        field.setStyleSheet(hw.FIELD_STYLE.replace("RADIUS", "0"))
        field.setFont(QFont(hw.PANEL_FONT, 10))
        field.setFixedHeight(24)
        return field

    def create_converter(self):
        """Number format converter section (Tools tab)."""
        card = Card("Number converter", "type in any field")
        form = self._tool_form()

        self.hex_input = self._tool_field(LineEdit("Enter hex value"))
        self.hex_input.textChanged.connect(lambda: self.convert_number("hex"))
        self.bin_input = self._tool_field(LineEdit("Enter binary value"))
        self.bin_input.textChanged.connect(lambda: self.convert_number("bin"))
        self.dec_input = self._tool_field(LineEdit("Enter decimal value"))
        self.dec_input.textChanged.connect(lambda: self.convert_number("dec"))
        for numeric in (self.hex_input, self.bin_input, self.dec_input):
            numeric.setFont(QFont(hw.HEX_FONT, 10))
        self.ascii_input = self._tool_field(LineEdit("Enter ASCII character"))
        self.ascii_input.setMaxLength(1)
        self.ascii_input.textChanged.connect(lambda: self.convert_number("ascii"))

        form.addRow(self._tool_label("Hex"), self.hex_input)
        form.addRow(self._tool_label("Binary"), self.bin_input)
        form.addRow(self._tool_label("Decimal"), self.dec_input)
        form.addRow(self._tool_label("ASCII"), self.ascii_input)
        card.body.addLayout(form)
        return card

    def convert_number(self, source):
        """Convert number between hex, binary, decimal and ASCII formats"""
        # Filling the other fields must not trigger this handler again
        self.hex_input.blockSignals(True)
        self.bin_input.blockSignals(True)
        self.dec_input.blockSignals(True)
        self.ascii_input.blockSignals(True)

        try:
            if source == "hex":
                hex_value = self.hex_input.text().strip()
                if hex_value:
                    value = int(hex_value, 16)
                    self.bin_input.setText(bin(value)[2:])
                    self.dec_input.setText(str(value))
                    # ASCII only for 0-127
                    if 0 <= value <= 127:
                        self.ascii_input.setText(chr(value))
                    else:
                        self.ascii_input.setText("X")
                else:
                    self.bin_input.setText("")
                    self.dec_input.setText("")
                    self.ascii_input.setText("")

            elif source == "bin":
                bin_value = self.bin_input.text().strip()
                if bin_value:
                    value = int(bin_value, 2)
                    self.hex_input.setText(hex(value)[2:].upper())
                    self.dec_input.setText(str(value))
                    # ASCII only for 0-127
                    if 0 <= value <= 127:
                        self.ascii_input.setText(chr(value))
                    else:
                        self.ascii_input.setText("X")
                else:
                    self.hex_input.setText("")
                    self.dec_input.setText("")
                    self.ascii_input.setText("")

            elif source == "dec":
                dec_value = self.dec_input.text().strip()
                if dec_value:
                    value = int(dec_value)
                    self.hex_input.setText(hex(value)[2:].upper())
                    self.bin_input.setText(bin(value)[2:])
                    # ASCII only for 0-127
                    if 0 <= value <= 127:
                        self.ascii_input.setText(chr(value))
                    else:
                        self.ascii_input.setText("X")
                else:
                    self.hex_input.setText("")
                    self.bin_input.setText("")
                    self.ascii_input.setText("")

            elif source == "ascii":
                ascii_value = self.ascii_input.text()
                if ascii_value and ascii_value != "X":
                    if len(ascii_value) > 0:
                        value = ord(ascii_value[0])
                        self.hex_input.setText(hex(value)[2:].upper())
                        self.bin_input.setText(bin(value)[2:])
                        self.dec_input.setText(str(value))
                else:
                    if ascii_value != "X":  # Only clear if not showing "X"
                        self.hex_input.setText("")
                        self.bin_input.setText("")
                        self.dec_input.setText("")

        except ValueError:
            # incomplete or invalid input
            pass

        self.hex_input.blockSignals(False)
        self.bin_input.blockSignals(False)
        self.dec_input.blockSignals(False)
        self.ascii_input.blockSignals(False)

    def create_memory_editor(self):
        """Memory editor section (Tools tab)."""
        card = Card("Memory editor", "write a byte to any address")
        form = self._tool_form()
        self.memory_addr_input = self._tool_field(LineEdit("Memory address (0-65535)[H]"))
        self.memory_value_input = self._tool_field(LineEdit("Value (0-255)[H]"))
        for numeric in (self.memory_addr_input, self.memory_value_input):
            numeric.setFont(QFont(hw.HEX_FONT, 10))
        self.write_memory_button = hw.MaterialButton("Write to Memory", hw.PRIMARY, filled=True)
        self.write_memory_button.setFixedHeight(24)
        self.write_memory_button.clicked.connect(self.write_memory_value)
        value_row = QHBoxLayout()
        value_row.setSpacing(6)
        value_row.addWidget(self.memory_value_input, 1)
        value_row.addWidget(self.write_memory_button)
        form.addRow(self._tool_label("Address"), self.memory_addr_input)
        form.addRow(self._tool_label("Value"), value_row)
        card.body.addLayout(form)
        return card

    def write_memory_value(self):
        """Write a value to a specific memory address"""
        try:
            addr_text = self.memory_addr_input.text().strip()
            value_text = self.memory_value_input.text().strip()

            if not addr_text or not value_text:
                self.add_to_log("Please enter both address and value", "ERROR")
                return

            address = self.parse_address(addr_text)
            value = self.parse_address(value_text)

            if not (0 <= address < 65536):
                self.add_to_log(
                    "Address must be in range 0-65535 (0000H-FFFFH)", "ERROR"
                )
                return

            if not (0 <= value <= 255):
                self.add_to_log("Value must be in range 0-255 (00H-FFH)", "ERROR")
                return

            # Program code is in RAM: it can be patched by hand (hand-assembled
            # opcodes) and the CPU executes the new byte
            if self.processor.is_program_memory(address):
                self.add_to_log(
                    f"Note: {address:04X}H holds program code - the CPU will execute the new byte",
                    "SYSTEM",
                )

            self.processor.memory[address] = value

            # Refresh the memory view if the address is on screen
            base_addr = 0
            if hasattr(self, "memory_table") and self.memory_table.rowCount() > 0:
                base_addr = int(
                    self.memory_table.item(0, 1).text()[:-1], 16
                )

            if base_addr <= address < base_addr + 256:
                row = (address - base_addr) // 16
                col = (
                              address - base_addr
                      ) % 16 + 2  # columns 0 and 1 hold the address

                if (
                        row < self.memory_table.rowCount()
                        and col < self.memory_table.columnCount()
                ):
                    self.memory_table.item(row, col).setText(f"{value:02X}")

            if addr_text.upper().endswith("H"):
                addr_display = f"{address:04X}H"
            else:
                addr_display = str(address)

            if value_text.upper().endswith("H"):
                value_display = f"{value:02X}H"
            else:
                value_display = str(value)

            self.add_to_log(
                f"Memory updated: [{addr_display}] = {value_display}", "SYSTEM"
            )

        except ValueError as e:
            self.add_to_log(f"Error: {str(e)}", "ERROR")
        except Exception as e:
            self.add_to_log(f"Error writing to memory: {str(e)}", "ERROR")

    # ------------------------------------------------------------------
    # External hardware: I/O devices and interrupt inputs
    # ------------------------------------------------------------------

    def _small_button(self, text, checkable=False, color="#5C2D91"):
        button = PushButton(text)
        button.setCheckable(checkable)
        button.setStyleSheet(
            f"""
            QPushButton {{
                background-color: white; color: {color};
                border: 1px solid {color}; padding: 3px;
            }}
            QPushButton:hover {{ background-color: #F3ECFA; }}
            QPushButton:checked {{ background-color: {color}; color: white; }}
        """
        )
        return button

    @staticmethod
    def _indicator_style(on, on_color="lightgreen"):
        return (
            f"background-color: black; color: {on_color if on else 'grey'}; "
            f"border: 1px solid #DDDDDD; padding: 1px;"
        )

    def create_io_panel(self):
        """I/O devices: 8 LEDs on an output port, 8 switches on an input port,
        any other input port value, the serial pins and the port latch table."""
        widget = QWidget()
        layout = hw.scroll_page(widget)

        card = Card("LEDs", "driven by the OUT port latch")
        card.bar_actions.addWidget(hw.caption("port", "#DCCBF0"))
        self.led_port_input = hw.field(f"{self.led_port:02X}H")
        self.led_port_input.setToolTip("Output port the LEDs are connected to")
        self.led_port_input.editingFinished.connect(self.set_led_port)
        card.bar_actions.addWidget(self.led_port_input)
        self.led_value_chip = hw.Chip("00H", "red")
        card.bar_actions.addWidget(self.led_value_chip)
        leds = QHBoxLayout()
        leds.setSpacing(0)
        self.led_labels = []
        self._led_value = None
        for bit in range(7, -1, -1):
            led = hw.Led(f"D{bit}", hw.RED, 20)
            led.setToolTip(f"LED driven by bit {bit} of the output port latch")
            leds.addWidget(led)
            self.led_labels.append(led)
        card.body.addLayout(leds)
        layout.addWidget(card)

        card = Card("Switches", "read by IN (up = 1)")
        card.bar_actions.addWidget(hw.caption("port", "#DCCBF0"))
        self.switch_port_input = hw.field(f"{self.switch_port:02X}H")
        self.switch_port_input.setToolTip("Input port the switches drive")
        self.switch_port_input.editingFinished.connect(self.set_switch_port)
        card.bar_actions.addWidget(self.switch_port_input)
        self.switch_value_chip = hw.Chip("00H", "teal")
        card.bar_actions.addWidget(self.switch_value_chip)
        switches = QHBoxLayout()
        switches.setSpacing(0)
        self.switch_buttons = []
        for bit in range(7, -1, -1):
            button = hw.ToggleSwitch(f"D{bit}", hw.TEAL, vertical=True)
            button.setToolTip(f"Switch for bit {bit} of the input port (up = 1)")
            button.toggled.connect(self._switches_changed)
            switches.addWidget(button, 1, Qt.AlignmentFlag.AlignHCenter)
            self.switch_buttons.append(button)
        card.body.addLayout(switches)
        layout.addWidget(card)

        card = Card("Input device and serial pins")
        row = QHBoxLayout()
        row.setSpacing(6)
        self.in_port_input = hw.field("", 70, "IN port")
        self.in_value_input = hw.field("", 70, "value")
        set_button = hw.MaterialButton("Set input", hw.TEAL)
        set_button.setToolTip("Value an input device drives onto this port (read by IN)")
        set_button.clicked.connect(self.set_input_port_value)
        row.addWidget(self.in_port_input)
        row.addWidget(self.in_value_input)
        row.addWidget(set_button)
        row.addStretch(1)
        card.body.addLayout(row)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.sid_button = hw.ToggleSwitch("SID = 0", hw.TEAL)
        self.sid_button.setToolTip("Serial input pin, read by RIM (bit 7)")
        self.sid_button.toggled.connect(self.set_sid)
        self.sod_label = hw.Led("SOD = 0", hw.AMBER, 16)
        self.sod_label.setToolTip("Serial output pin, set by SIM (bit 7 when SDE, bit 6, = 1)")
        row.addWidget(self.sid_button)
        row.addWidget(self.sod_label)
        row.addStretch(1)
        card.body.addLayout(row)
        layout.addWidget(card)

        card = Card("Port latches", "IN = what the device drives, OUT = latch written by OUT")
        self.port_table = QTableWidget(0, 3)
        self.port_table.setHorizontalHeaderLabels(["Port", "IN (device)", "OUT (latch)"])
        self.port_table.verticalHeader().setVisible(False)
        self.port_table.verticalHeader().setDefaultSectionSize(20)
        self.port_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.port_table.setShowGrid(False)
        self.port_table.setAlternatingRowColors(True)
        self.port_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.port_table.setFont(QFont(hw.HEX_FONT, 9))
        self.port_table.setMinimumHeight(140)
        self.port_table.setStyleSheet(
            "QTableWidget { border: none; background: white; alternate-background-color: #F8F6FB; }"
            " QHeaderView::section { background: white; color: #6B6B6B; border: none;"
            " border-bottom: 1px solid #E3E3E3; padding: 3px; font: bold 8pt 'Segoe UI'; }"
        )
        card.body.addWidget(self.port_table)
        layout.addWidget(card)
        layout.addStretch(1)
        return widget

    def create_interrupt_panel(self):
        """The five 8085 interrupt inputs and the interrupt system status."""
        widget = QWidget()
        layout = hw.scroll_page(widget)

        card = Card("Interrupt inputs", "highest priority first")
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        self.pin_leds = {}
        rows = (
            ("TRAP", "TRAP", "non-maskable · rising edge + high level · 0024H"),
            ("RST7.5", "RST 7.5", "rising edge, latched in R7.5 · mask M7.5 · 003CH"),
            ("RST6.5", "RST 6.5", "high level · mask M6.5 · 0034H"),
            ("RST5.5", "RST 5.5", "high level · mask M5.5 · 002CH"),
            ("INTR", "INTR", "high level · device supplies RST n or CALL"),
        )
        for row, (pin, title, description) in enumerate(rows):
            badge = hw.Chip(str(row + 1), "red" if pin == "TRAP" else "primary", mono=False)
            badge.setToolTip("Priority (1 = highest)")
            grid.addWidget(badge, row, 0)
            text = QVBoxLayout()
            text.setSpacing(0)
            text.addWidget(hw.caption(title, hw.TEXT, 9, True))
            text.addWidget(hw.caption(description, hw.TEXT_2, 7))
            grid.addLayout(text, row, 1)
            led = hw.Led("", hw.GREEN, 14)
            led.setToolTip(f"{title} pin level")
            grid.addWidget(led, row, 2)
            self.pin_leds[pin] = led
        self.trap_button = hw.MaterialButton("Raise", hw.RED)
        self.trap_button.setToolTip(
            "Non-maskable, highest priority, vector 0024H. Edge and level sensitive: "
            "the pin is raised and held high until the CPU acknowledges it."
        )
        self.trap_button.clicked.connect(self.raise_trap)
        grid.addWidget(self.trap_button, 0, 3)
        self.rst75_button = hw.MaterialButton("Pulse ↑", hw.PRIMARY)
        self.rst75_button.setToolTip(
            "Rising edge, remembered in the R7.5 flip-flop. Needs EI and M7.5 = 0. Vector 003CH."
        )
        self.rst75_button.clicked.connect(self.pulse_rst75)
        grid.addWidget(self.rst75_button, 1, 3)
        self.rst65_button = hw.ToggleSwitch("", hw.TEAL)
        self.rst65_button.setToolTip(
            "Level sensitive: stays high until you switch it off. Needs EI and M6.5 = 0. Vector 0034H."
        )
        self.rst65_button.toggled.connect(lambda level: self.set_level_pin("RST6.5", level))
        grid.addWidget(self.rst65_button, 2, 3, Qt.AlignmentFlag.AlignLeft)
        self.rst55_button = hw.ToggleSwitch("", hw.TEAL)
        self.rst55_button.setToolTip(
            "Level sensitive: stays high until you switch it off. Needs EI and M5.5 = 0. Vector 002CH."
        )
        self.rst55_button.toggled.connect(lambda level: self.set_level_pin("RST5.5", level))
        grid.addWidget(self.rst55_button, 3, 3, Qt.AlignmentFlag.AlignLeft)
        self.intr_button = hw.MaterialButton("Raise", hw.PRIMARY)
        self.intr_button.setToolTip(
            "Lowest priority, needs EI (not affected by SIM masks). During INTA the device "
            "supplies the selected instruction and then drops INTR."
        )
        self.intr_button.clicked.connect(self.raise_intr)
        grid.addWidget(self.intr_button, 4, 3)
        grid.setColumnStretch(1, 1)
        card.body.addLayout(grid)

        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(hw.caption("INTA supplies", hw.TEXT, 8, True))
        self.intr_combo = hw.combo()
        self.intr_combo.addItems([f"RST {n}" for n in range(8)] + ["CALL"])
        self.intr_combo.setCurrentIndex(7)
        self.intr_combo.setToolTip("Instruction placed on the data bus during INTA")
        self.intr_combo.currentIndexChanged.connect(self._intr_mode_changed)
        self.intr_address_input = hw.field("", 90, "CALL addr")
        self.intr_address_input.setEnabled(False)
        row.addWidget(self.intr_combo)
        row.addWidget(self.intr_address_input)
        row.addStretch(1)
        card.body.addLayout(row)
        layout.addWidget(card)

        card = Card("Interrupt system", "INTE, SIM masks and pending requests")
        self.interrupt_indicators = {}
        tooltips = {
            "INTE": "Interrupt enable flip-flop (EI sets, DI and any acknowledge clear)",
            "M7.5": "RST 7.5 mask (lit = masked)", "M6.5": "RST 6.5 mask (lit = masked)",
            "M5.5": "RST 5.5 mask (lit = masked)",
            "TRAP": "TRAP request (edge seen and pin still high)",
            "I7.5": "R7.5 flip-flop: RST 7.5 pending", "I6.5": "RST 6.5 pin level",
            "I5.5": "RST 5.5 pin level", "INTR": "INTR pin level",
        }
        groups = (
            ("Enable", (("INTE", hw.GREEN),)),
            ("Masks", (("M7.5", hw.AMBER), ("M6.5", hw.AMBER), ("M5.5", hw.AMBER))),
            ("Pending", (("TRAP", hw.RED), ("I7.5", hw.GREEN), ("I6.5", hw.GREEN), ("I5.5", hw.GREEN),
                         ("INTR", hw.GREEN))),
        )
        row = QHBoxLayout()
        row.setSpacing(4)
        for index, (title, names) in enumerate(groups):
            group = QVBoxLayout()
            group.setSpacing(0)
            group.addWidget(hw.caption(title, hw.TEXT_2, 7, True), 0, Qt.AlignmentFlag.AlignHCenter)
            leds = QHBoxLayout()
            leds.setSpacing(0)
            for name, color in names:
                led = hw.Led(name, color, 16)
                led.setToolTip(tooltips[name])
                leds.addWidget(led)
                self.interrupt_indicators[name] = led
            group.addLayout(leds)
            row.addLayout(group)
            if index < len(groups) - 1:
                line = QFrame()
                line.setFrameShape(QFrame.Shape.VLine)
                line.setStyleSheet("color: #E6E6E6;")
                row.addWidget(line)
        row.addStretch(1)
        card.body.addLayout(row)

        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(hw.caption("RIM reads", hw.TEXT, 8, True))
        self.rim_chip = hw.Chip("00H", "primary")
        self.rim_chip.setToolTip("The byte RIM would load into A now")
        row.addWidget(self.rim_chip)
        self.rim_bits = []
        for name in ("SID", "I7.5", "I6.5", "I5.5", "IE", "M7.5", "M6.5", "M5.5"):
            led = hw.Led(name, hw.PRIMARY, 10)
            led.setToolTip(f"RIM bit {7 - len(self.rim_bits)}: {name}")
            row.addWidget(led)
            self.rim_bits.append(led)
        row.addStretch(1)
        card.body.addLayout(row)

        self.interrupt_status_label = hw.caption("No interrupt acknowledged yet", hw.TEXT_2, 8)
        self.interrupt_status_label.setWordWrap(True)
        card.body.addWidget(self.interrupt_status_label)
        layout.addWidget(card)
        layout.addStretch(1)
        return widget

    def _parse_byte(self, text, what):
        value = self.parse_address(text)
        if not 0 <= value <= 0xFF:
            raise ValueError(f"{what} must be 0-255 (00H-FFH)")
        return value

    def _write_input_ports(self):
        """Drive the CPU's input port latches from the simulated input devices."""
        ports = self.processor.input_ports
        ports[:] = bytes(0x100)
        for port, value in self.input_values.items():
            ports[port] = value
        ports[self.switch_port] = self.switch_bits

    def _apply_devices(self):
        """Connect the simulated external hardware to a (new) processor."""
        cpu = self.processor
        self.peripherals.attach(cpu)
        self._write_input_ports()
        cpu.sid = self.sid_level
        for name, level in self.pin_levels.items():
            cpu.set_pin(name, level)
        if hasattr(self, "intr_combo"):
            try:
                cpu.set_intr_instruction(self._intr_instruction_bytes())
            except ValueError:
                pass

    def set_led_port(self):
        try:
            self.led_port = self._parse_byte(self.led_port_input.text(), "LED port")
            self.add_to_log(f"LEDs connected to output port {self.led_port:02X}H", "SYSTEM")
        except ValueError as e:
            self.add_to_log(f"Error: {e}", "ERROR")
        self.led_port_input.setText(f"{self.led_port:02X}H")
        self._led_value = None
        self.update_io_display()

    def set_switch_port(self):
        try:
            port = self._parse_byte(self.switch_port_input.text(), "Switch port")
            if port != self.switch_port:
                self.switch_port = port
                self.add_to_log(f"Switches connected to input port {port:02X}H", "SYSTEM")
        except ValueError as e:
            self.add_to_log(f"Error: {e}", "ERROR")
        self.switch_port_input.setText(f"{self.switch_port:02X}H")
        self._write_input_ports()
        self.update_io_display()

    def _switches_changed(self, _checked=False):
        self._sync_clock()
        bits = 0
        for index, button in enumerate(self.switch_buttons):
            if button.isChecked():
                bits |= 1 << (7 - index)
        self.switch_bits = bits
        self._write_input_ports()
        self.add_to_log(
            f"Switches (IN port {self.switch_port:02X}H) = {bits:08b}B ({bits:02X}H)", "SYSTEM"
        )
        self.update_io_display()

    def set_input_port_value(self):
        try:
            port = self._parse_byte(self.in_port_input.text().strip(), "Port")
            value = self._parse_byte(self.in_value_input.text().strip(), "Value")
        except ValueError as e:
            self.add_to_log(f"Error: {e}", "ERROR")
            return
        self._sync_clock()
        if port == self.switch_port:
            # The switches drive this port: show the value on them
            for index, button in enumerate(self.switch_buttons):
                button.blockSignals(True)
                button.setChecked(bool((value >> (7 - index)) & 1))
                button.blockSignals(False)
                button.update()
            self.switch_bits = value
        else:
            self.input_values[port] = value
        self._write_input_ports()
        self.add_to_log(f"Input device drives IN port {port:02X}H = {value:02X}H ({value:08b}B)", "SYSTEM")
        self.update_io_display()

    def set_sid(self, checked):
        self._sync_clock()
        self.sid_level = 1 if checked else 0
        self.processor.sid = self.sid_level
        self.sid_button.setText(f"SID = {self.sid_level}")
        self.add_to_log(f"SID (serial input) pin = {self.sid_level}", "SYSTEM")

    def _record_io(self, log):
        """Remember ports used by IN/OUT and optionally log the transfer."""
        io = self.processor.last_io
        if io is None:
            return
        kind, port, value = io
        self.io_seen_ports.add(port)
        for counter in self.peripherals.pit.counters:
            if counter.warning:
                self.add_to_log(f"Warning: {counter.warning}", "ERROR")
                counter.warning = None
        if log:
            chip = self._chip_register(port)
            if chip:
                verb = "wrote" if kind == "OUT" else "read"
                self.add_to_log(f"{kind} {port:02X}H: {verb} {value:02X}H ({value:08b}B) - {chip}", "SYSTEM")
            elif kind == "OUT":
                self.add_to_log(f"OUT {port:02X}H: output latch = {value:02X}H ({value:08b}B)", "SYSTEM")
            else:
                self.add_to_log(f"IN {port:02X}H: read {value:02X}H ({value:08b}B) from the input device", "SYSTEM")

    def _chip_register(self, port):
        """Name of the 8255/8253 register at an I/O port, or None."""
        entry = self.peripherals.ports().get(port)
        if entry is None:
            return None
        device, offset = entry
        if device is self.peripherals.ppi:
            return ("8255 port A", "8255 port B", "8255 port C", "8255 control register")[offset]
        return ("8253 counter 0", "8253 counter 1", "8253 counter 2", "8253 control register")[offset]

    def update_io_display(self):
        self.update_peripheral_display()
        cpu = self.processor
        value = cpu.output_ports[self.led_port]
        if value != self._led_value:
            self._led_value = value
            for index, led in enumerate(self.led_labels):
                led.set_on((value >> (7 - index)) & 1)
            hw.set_text(self.led_value_chip, f"{value:02X}H")
        hw.set_text(self.switch_value_chip, f"{self.switch_bits:02X}H")

        ports = {self.led_port, self.switch_port} | set(self.input_values) | self.io_seen_ports
        ports |= {p for p in range(0x100) if cpu.output_ports[p] or cpu.input_ports[p]}
        ports = sorted(ports)
        if self.port_table.rowCount() != len(ports):
            self.port_table.setRowCount(len(ports))
        for row, port in enumerate(ports):
            texts = (f"{port:02X}H", f"{cpu.input_ports[port]:02X}H", f"{cpu.output_ports[port]:02X}H")
            for column, text in enumerate(texts):
                item = self.port_table.item(row, column)
                if item is None:
                    item = QTableWidgetItem(text)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.port_table.setItem(row, column, item)
                elif item.text() != text:
                    item.setText(text)

        self.sod_label.setText(f"SOD = {cpu.sod}")
        self.sod_label.set_on(cpu.sod)

    # Interrupt inputs

    def _intr_mode_changed(self, index):
        self.intr_address_input.setEnabled(index == 8)

    def _intr_instruction_bytes(self):
        index = self.intr_combo.currentIndex()
        if index < 8:
            return [0xC7 | (index << 3)]
        address = self.parse_address(self.intr_address_input.text())
        if not 0 <= address <= 0xFFFF:
            raise ValueError("CALL address must be 0000H-FFFFH")
        return [0xCD, address & 0xFF, address >> 8]

    def _after_pin_change(self):
        self.update_interrupt_display()
        cpu = self.processor
        if cpu.halted and not self.running and cpu.pending_interrupt() is not None:
            self.add_to_log("The halted CPU will service the interrupt on the next Step or Run", "SYSTEM")

    def raise_trap(self):
        self._sync_clock()
        self.processor.set_pin("TRAP", 1, auto_release=True, at=self._input_time())
        self.add_to_log("TRAP pin raised (held high until acknowledged)", "SYSTEM")
        self._after_pin_change()

    def pulse_rst75(self):
        self._sync_clock()
        self.processor.pulse_rst75(at=self._input_time())
        self.add_to_log("RST 7.5: rising edge latched in the R7.5 flip-flop", "SYSTEM")
        self._after_pin_change()

    def set_level_pin(self, name, level):
        self._sync_clock()
        self.pin_levels[name] = bool(level)
        self.processor.set_pin(name, level, at=self._input_time())
        pretty = name[:3] + " " + name[3:]
        self.add_to_log(f"{pretty} pin {'HIGH' if level else 'LOW'}", "SYSTEM")
        self._after_pin_change()

    def raise_intr(self):
        try:
            data = self._intr_instruction_bytes()
            self.processor.set_intr_instruction(data)
        except ValueError as e:
            self.add_to_log(f"Error: {e}", "ERROR")
            return
        self._sync_clock()
        self.processor.set_pin("INTR", 1, auto_release=True, at=self._input_time())
        supplied = self.intr_combo.currentText()
        if supplied == "CALL":
            supplied = f"CALL {(data[2] << 8) | data[1]:04X}H"
        self.add_to_log(f"INTR raised - the device will supply {supplied} during INTA", "SYSTEM")
        self._after_pin_change()

    def update_interrupt_display(self):
        cpu = self.processor
        self.peripherals.sync(cpu.t_states)  # chip outputs on the pins up to date
        masks = cpu.interrupt_masks
        states = {
            "INTE": cpu.interrupt_enable,
            "M7.5": (masks >> 2) & 1,
            "M6.5": (masks >> 1) & 1,
            "M5.5": masks & 1,
            "TRAP": cpu.trap_ff and cpu.pins["TRAP"],
            "I7.5": cpu.rst75_ff,
            "I6.5": cpu.pins["RST6.5"],
            "I5.5": cpu.pins["RST5.5"],
            "INTR": cpu.pins["INTR"],
        }
        for name, led in self.interrupt_indicators.items():
            led.set_on(states[name])
        for name, led in self.pin_leds.items():
            led.set_on(cpu.pins[name])
        rim = cpu.rim_value()
        hw.set_text(self.rim_chip, f"{rim:02X}H")
        for index, led in enumerate(self.rim_bits):
            led.set_on((rim >> (7 - index)) & 1)
        for name, button in (("RST6.5", self.rst65_button), ("RST5.5", self.rst55_button)):
            # The switch shows the panel's own level (chip outputs may also drive the pin)
            level = bool(cpu.pin_source_level(name, "panel"))
            if button.isChecked() != level:
                button.blockSignals(True)
                button.setChecked(level)
                button.blockSignals(False)
                button.update()
                self.pin_levels[name] = level

    _INTERRUPT_NAMES = {"TRAP": "TRAP", "RST7.5": "RST 7.5", "RST6.5": "RST 6.5", "RST5.5": "RST 5.5",
                        "INTR": "INTR"}

    def _report_interrupts(self, summarize=False):
        """
        Logs the interrupts acknowledged since the last report. In fast runs
        (summarize) the first few of a run are logged one by one; after that
        they are counted and summarised once a second (see
        _flush_interrupt_summary), so a timer interrupting every few
        milliseconds does not flood the log.
        """
        log = self.processor.interrupt_log
        if not log:
            if summarize:
                self._flush_interrupt_summary()
            return
        entries = list(log)
        log.clear()
        names = self._INTERRUPT_NAMES
        detailed = entries
        if summarize:
            room = max(0, INTERRUPT_LOG_DETAIL - self._run_interrupts_logged)
            detailed = entries[:room]
            self._run_interrupts_logged += len(detailed)
            for name, _, _ in entries[len(detailed):]:
                self._interrupt_tally[name] += 1
        for name, return_address, target in detailed:
            self.add_to_log(
                f"Interrupt {names[name]} acknowledged: return address {return_address:04X}H "
                f"pushed, jump to {target:04X}H (INTE cleared)",
                "SYSTEM",
            )
        if summarize:
            self._flush_interrupt_summary()
        name, return_address, target = entries[-1]
        self.interrupt_status_label.setText(
            f"Last: {names[name]} -> {target:04X}H (return to {return_address:04X}H)"
        )

    def _flush_interrupt_summary(self, force=False):
        """Logs how many interrupts were acknowledged since the last summary (at most once a second)."""
        if not self._interrupt_tally:
            return
        now = self.realtime_clock.nsecsElapsed() if self.realtime_clock.isValid() else 0
        if not force and now - self._interrupt_tally_since < 1_000_000_000:
            return
        counts = ", ".join(
            f"{self._INTERRUPT_NAMES[name]} x{count}" for name, count in self._interrupt_tally.items()
        )
        self.add_to_log(f"Interrupts acknowledged since the last report: {counts}", "SYSTEM")
        self._interrupt_tally.clear()
        self._interrupt_tally_since = now

    def document_was_modified(self):
        """Mark the document as modified and update the window title"""
        if not self.document_modified:
            self.document_modified = True
            self.update_window_title()

    def update_window_title(self):
        """Update window title to show the modification state"""
        title = f"Neo8085 v{display_version} - "
        if self.current_file:
            filename = os.path.basename(self.current_file)
            if self.document_modified:
                title += f"{filename}* [Changes not saved]"
            else:
                title += filename
        else:
            title += "Untitled"
            if self.document_modified:
                title += (
                    "* [Changes not saved]"
                )

        self.setWindowTitle(title)


class Flags(QWidget):
    def __init__(self, simulator: Simulator):
        super().__init__()
        self.simulator = simulator
        vbox_layout = QVBoxLayout()
        vbox_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        vbox_layout.setContentsMargins(0, 0, 0, 0)
        vbox_layout.setSpacing(0)
        self.setLayout(vbox_layout)
        self.header = Label("Flags")
        self.header.setFont(QFont("Consolas", 12))
        self.header.setStyleSheet(
            "background-color: white; color: #1E1E1E; border: 1px solid #DDDDDD;"
        )
        self.header.setAlignment(Qt.AlignCenter)
        vbox_layout.addWidget(self.header)
        hbox_layout = QHBoxLayout()
        hbox_layout.setContentsMargins(0, 0, 0, 0)
        hbox_layout.setSpacing(0)
        # Flag register bit order: S Z K AC 0 P V CY (K and V are the undocumented 8085 flags)
        self.flags: dict[str, Label] = {"S": None, "Z": None, "K": None, "AC": None, " ": None, "X3": None, "P": None, "V": None, "C": None}
        tooltips = {
            "S": "Sign (bit 7)", "Z": "Zero (bit 6)",
            "K": "K / X5 (bit 5, undocumented): V XOR S; carry/borrow of INX/DCX",
            "AC": "Auxiliary carry (bit 4)", "X3": "Bit 3 (always 0)", "P": "Parity (bit 2)",
            "V": "Overflow (bit 1, undocumented): two's complement overflow", "C": "Carry (bit 0)",
        }
        for flag in self.flags:
            self.flags[flag] = Label(flag)
            if flag != " ":
                self.flags[flag].setStyleSheet("background-color: black; color: grey; border: 1px solid #DDDDDD;")
                self.flags[flag].setToolTip(tooltips[flag])
            hbox_layout.addWidget(self.flags[flag])
        vbox_layout.addLayout(hbox_layout)

    def update_display(self):
        """Update flags display from processor state"""
        if self.simulator is None:
            return
        flags_byte = self.simulator.processor.get_flags_byte()
        self.header.setText(f"Flags (bin): {(flags_byte >> 4) & 0xF:04b} {flags_byte & 0xF:04b}")
        for flag, value in self.simulator.processor.flags.items():
            if flag in self.flags:
                self.flags[flag].setStyleSheet(f"background-color: black; color: {'lightgreen' if value == 1 else 'grey'}; border: 1px solid #DDDDDD;")
                self.flags[flag].update()

    def zoom_in(self):
        self.header.zoom_in()
        for flag in self.flags:
            self.flags[flag].zoom_in()

    def zoom_out(self):
        self.header.zoom_out()
        for flag in self.flags:
            self.flags[flag].zoom_out()

    def reset_zoom(self):
        self.header.reset_zoom()
        for flag in self.flags:
            self.flags[flag].reset_zoom()


class Stack(QGridLayout):
    """Stack display: the 8 words from SP upward."""
    def __init__(self, simulator: Simulator):
        super().__init__()
        self.simulator = simulator
        self.header = Header("STACK")
        self.addWidget(self.header, 0, 0, 1, 2)
        self.mem_locations: list[Label] = []
        for i in range(16):
            label = Label(f"Stack {i}")
            label.setStyleSheet(
                "background-color: white; color: #1E1E1E; padding: 5px; border: 1px solid #DDDDDD;"
            )
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.mem_locations.append(label)
            self.addWidget(self.mem_locations[i], (i // 2) + 1, i % 2)

    def update_display(self):
        """
        Show the 8 words at the top of the stack (SP, SP+2, ...). Stack
        addresses wrap around at FFFFH, so a word at FFFFH takes its high
        byte from 0000H.
        """
        if self.simulator is None:
            return
        memory = self.simulator.processor.memory
        sp = self.simulator.processor.registers["SP"]
        for i in range(8):
            addr = (sp + i * 2) & 0xFFFF
            lsb = memory[addr]
            msb = memory[(addr + 1) & 0xFFFF]
            self.mem_locations[i * 2].setText(f"[{addr:04X}H]")
            self.mem_locations[i * 2 + 1].setText(f"{msb:02X}{lsb:02X}H")

    def zoom_in(self):
        for mem_location in self.mem_locations:
            mem_location.zoom_in()

    def zoom_out(self):
        for mem_location in self.mem_locations:
            mem_location.zoom_out()

    def reset_zoom(self):
        for mem_location in self.mem_locations:
            mem_location.reset_zoom()


class MemoryTableWidget(ZoomMixin, QTableWidget):
    """Custom QTableWidget that clears selection when losing focus"""

    def __init__(self, rows, columns, simulator: Simulator, parent=None):
        super().__init__(rows, columns, parent, font_point_size=10)
        self.simulator = simulator
        self.setFont(QFont("Consolas", 10))
        self.setStyleSheet(
            """
            QTableWidget {
            background-color: white;
            border: 1px solid #DDDDDD;
            border-radius: 4px;
            color: #1E1E1E;
            }
            QHeaderView::section {
                background-color: #F0F0F0;
                color: #1E1E1E;
                padding: 5px;
                border: 1px solid #DDDDDD;
            }
            QTableWidget::item {
                border: 1px solid #F0F0F0;
                padding: 2px;
            }
            QTableWidget::item:selected {
                background-color: #0B91FF;
                color: white;
            }
        """
        )

        self.horizontalHeader().setDefaultSectionSize(45)
        self.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        self.setColumnWidth(1, 80)
        self.verticalHeader().setDefaultSectionSize(28)

        self.setHorizontalHeaderItem(0, TableWidgetItem("Dec"))
        self.setHorizontalHeaderItem(1, TableWidgetItem("Hex"))
        for i in range(16):
            self.setHorizontalHeaderItem(
                i + 2, TableWidgetItem(f"+{i:X}")
            )

        self.horizontalHeader().setStretchLastSection(True)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.cellClicked.connect(self.display_value)

    def display_value(self, row, column):
        if column >= 2:
            lsb_addr = int(self.item(row, 0).text()) + column - 2
            memory = self.simulator.processor.memory
            lsb = f"{memory[lsb_addr]:02X}H"
            msb = f"{memory[(lsb_addr + 1) & 0xFFFF]:02X}"  # 16-bit addresses wrap
            self.simulator.add_to_log(f"Byte value at {lsb_addr:04X}H is {lsb}")
            self.simulator.add_to_log(f"Word value at {lsb_addr:04X}H is {msb}{lsb}")
        
    def focusOutEvent(self, event):
        self.clearSelection()
        super().focusOutEvent(event)

    def zoom_in(self):
        super().zoom_in()
        for i in range(self.columnCount()):
            self.horizontalHeaderItem(i).zoom_in()

    def zoom_out(self):
        super().zoom_out()
        for i in range(self.columnCount()):
            self.horizontalHeaderItem(i).zoom_out()

    def reset_zoom(self):
        super().reset_zoom()
        for i in range(self.columnCount()):
            self.horizontalHeaderItem(i).reset_zoom()


def main():
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(resource_path("8085-logo.ico")))

    splash_pix = QPixmap(resource_path("8085-splash-screen.png"))
    
    if not splash_pix.isNull():
        splash = QSplashScreen(splash_pix, Qt.WindowType.WindowStaysOnTopHint)
        splash.show()
        QTimer.singleShot(2000, splash.close)

    window = Simulator()

    for button in window.findChildren(QPushButton):
        button.setCursor(Qt.CursorShape.PointingHandCursor)

    QTimer.singleShot(2000, window.show)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
