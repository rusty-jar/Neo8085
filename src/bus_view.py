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
Bus cycle views: the machine-cycle table, the T-state timing diagram and the
"Bus Cycles" side panel with its history of recorded instructions.
"""

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from bus import CYCLE_TYPES, SIGNALS, waveform
import hw_widgets as hw

MAX_RECORDS = 200
# The most machine cycles one step can have: CALL, Ccc taken, SHLD, LHLD, XTHL
# and an INTR acknowledge with CALL each have five
MAX_MACHINE_CYCLES = 5
TABLE_ROW_HEIGHT = 22

CYCLE_COLORS = {
    "OF": "#E8DDF5",
    "MR": "#DDEBF7",
    "MW": "#FCE4D6",
    "IOR": "#E2EFDA",
    "IOW": "#FFF2CC",
    "INA": "#F8D7DA",
    "BI": "#EDEDED",
    "BIA": "#F8D7DA",
    "HALT": "#D9D9D9",
}
ADDRESS_COLOR = QColor("#1F5FBF")
DATA_COLOR = QColor("#107C10")
LINE_COLOR = QColor("#202020")
FLOAT_COLOR = QColor("#9A9A9A")
GRID_COLOR = QColor("#C8C8C8")


def _bit(value):
    return "Z" if value is None else str(value)


def status_text(cycle):
    io_m, s1, s0 = cycle.status
    return f"{_bit(io_m)} {s1} {s0}"


def explain(cycle, label):
    """What happens on the bus during one T-state (shown as a tool tip)."""
    io_m, s1, s0 = cycle.status
    status = f"IO/M={_bit(io_m)} S1={s1} S0={s0}"
    address = "" if cycle.address is None else f"{cycle.address:04X}H"
    data = "--" if cycle.data is None else f"{cycle.data:02X}H"
    kind = cycle.kind
    strobe = cycle.strobe

    if kind == "HALT":
        return (f"{label}: HALT state. A15-A8, AD7-AD0, RD, WR and IO/M are high impedance "
                f"(S1 S0 = 00). The CPU waits for an interrupt or RESET.")
    if label == "T1":
        if kind == "BI":
            return f"T1: bus idle ({status}). No ALE and no address: the ALU works internally."
        text = f"T1: {status}. ALE is high; address {address} is output"
        if kind in ("IOR", "IOW"):
            text += " (the port address appears on both A15-A8 and AD7-AD0)"
        return text + " and is latched on the falling edge of ALE."
    if label in ("T2", "T3"):
        if strobe is None:
            return f"{label}: no data transfer (RD, WR and INTA stay high)."
        if strobe == "WR":
            if label == "T2":
                return f"T2: WR goes low; the CPU drives data {data} on AD7-AD0."
            return f"T3: data {data} is written; WR returns high at the end of T3."
        source = {"OF": "memory places the opcode", "MR": "memory places the data",
                  "IOR": "the input port places its data",
                  "INA": "the interrupting device places the instruction byte"}[kind]
        if label == "T2":
            return f"T2: {strobe} goes low; AD7-AD0 floats and {source} on the bus."
        target = "the instruction register" if kind in ("OF", "INA") else "the CPU"
        return f"T3: {data} is read from AD7-AD0 into {target}; {strobe} returns high."
    if label == "T4":
        return "T4: the opcode is decoded. A15-A8 unspecified, AD7-AD0 high impedance."
    return f"{label}: internal operation (16-bit register / stack pointer update). AD7-AD0 high impedance."


class TimingDiagram(QWidget):
    """Paints CLK, the buses, ALE, the status lines and RD/WR/INTA for a list of machine cycles."""

    def __init__(self, parent=None, column_width=46):
        super().__init__(parent)
        self.cycles = []
        self.title = ""
        self.column_width = column_width
        self.setMouseTracking(True)
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(self.backgroundRole(), QColor("white"))
        self.setPalette(palette)
        self._states = []
        self._update_geometry()

    # Layout -----------------------------------------------------------
    @property
    def label_width(self):
        return 78

    @property
    def row_height(self):
        return max(18, int(self.column_width * 0.5))

    def _header_rows(self):
        return 2  # machine cycle band, T-state labels

    def set_cycles(self, cycles, title=""):
        self.cycles = list(cycles or [])
        self.title = title
        self._states = waveform(self.cycles)
        self._update_geometry()
        self.update()

    def set_column_width(self, width):
        self.column_width = max(24, min(120, width))
        self._update_geometry()
        self.update()

    def _update_geometry(self):
        columns = max(len(self._states), 4)
        width = self.label_width + columns * self.column_width + 12
        height = (self._header_rows() + len(SIGNALS)) * self.row_height + self.row_height + 10
        self.setMinimumSize(width, height)
        self.resize(width, height)

    def _top(self):
        return self.row_height  # title line

    def _signal_y(self, index):
        return self._top() + (self._header_rows() + index) * self.row_height

    def _state_at(self, x):
        column = int((x - self.label_width) // self.column_width)
        if 0 <= column < len(self._states):
            return column
        return None

    # Tool tips --------------------------------------------------------
    def event(self, event):
        if event.type() == event.Type.ToolTip:
            column = self._state_at(event.pos().x())
            if column is not None:
                index, label, _ = self._states[column]
                cycle = self.cycles[index]
                QToolTip.showText(
                    event.globalPos(),
                    f"M{index + 1} {cycle.name} ({cycle.t_states} T)\n{explain(cycle, label)}",
                    self,
                )
            else:
                QToolTip.hideText()
            return True
        return super().event(event)

    # Painting ---------------------------------------------------------
    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        font = QFont("Segoe UI", 8)
        painter.setFont(font)
        metrics = QFontMetrics(font)
        rh = self.row_height
        cw = self.column_width
        lw = self.label_width
        top = self._top()

        painter.setPen(LINE_COLOR)
        title = self.title or "No machine cycles recorded yet - step an instruction"
        painter.drawText(QRectF(4, 0, self.width() - 8, rh), Qt.AlignmentFlag.AlignVCenter, title)
        if not self._states:
            return

        n = len(self._states)
        bottom = self._signal_y(len(SIGNALS))

        # Machine-cycle band and T-state labels
        column = 0
        for index, cycle in enumerate(self.cycles):
            x = lw + column * cw
            width = cycle.t_states * cw
            painter.fillRect(QRectF(x, top, width, rh), QColor(CYCLE_COLORS[cycle.kind]))
            painter.setPen(LINE_COLOR)
            text = f"M{index + 1}: {cycle.name}"
            if metrics.horizontalAdvance(text) > width - 6:
                text = f"M{index + 1} {cycle.short_name}"
            painter.drawText(QRectF(x, top, width, rh), Qt.AlignmentFlag.AlignCenter, text)
            column += cycle.t_states
        for column, (_, label, _) in enumerate(self._states):
            x = lw + column * cw
            painter.drawText(QRectF(x, top + rh, cw, rh), Qt.AlignmentFlag.AlignCenter, label)

        # Alternate row shading keeps neighbouring signals apart
        for index in range(0, len(SIGNALS), 2):
            y = self._signal_y(index)
            painter.fillRect(QRectF(0, y, lw + n * self.column_width, rh), QColor("#F6F6F9"))

        # Grid: thin lines per T-state, strong lines at machine-cycle boundaries
        column = 0
        boundaries = {0}
        for cycle in self.cycles:
            column += cycle.t_states
            boundaries.add(column)
        for column in range(n + 1):
            x = lw + column * cw
            if column in boundaries:
                painter.setPen(QPen(QColor("#7F7F7F"), 1.2))
            else:
                painter.setPen(QPen(GRID_COLOR, 1, Qt.PenStyle.DotLine))
            painter.drawLine(QPointF(x, top), QPointF(x, bottom))

        # Signal names
        painter.setPen(LINE_COLOR)
        bold = QFont(font)
        bold.setBold(True)
        painter.setFont(bold)
        for index, name in enumerate(SIGNALS):
            y = self._signal_y(index)
            painter.drawText(QRectF(4, y, lw - 8, rh), Qt.AlignmentFlag.AlignVCenter, name)
        painter.setFont(font)

        # Waveforms
        for index, name in enumerate(SIGNALS):
            y = self._signal_y(index)
            if name == "CLK":
                self._draw_clock(painter, y, n)
            else:
                halves = []
                for cycle_index, _, signals in self._states:
                    if name in ("A15-A8", "AD7-AD0"):
                        # a new machine cycle always starts a new bus segment
                        halves.extend((cycle_index, value) for value in signals[name])
                    else:
                        halves.extend(signals[name])
                if name in ("A15-A8", "AD7-AD0"):
                    self._draw_bus(painter, y, halves, metrics)
                else:
                    self._draw_line(painter, y, halves)
        painter.end()

    def _levels(self, y):
        rh = self.row_height
        return y + rh * 0.2, y + rh * 0.8, y + rh * 0.5  # high, low, middle

    def _draw_clock(self, painter, y, columns):
        high, low, _ = self._levels(y)
        cw = self.column_width
        painter.setPen(QPen(LINE_COLOR, 1.4))
        points = []
        for column in range(columns):
            x = self.label_width + column * cw
            points += [QPointF(x, low), QPointF(x, high), QPointF(x + cw / 2, high),
                       QPointF(x + cw / 2, low), QPointF(x + cw, low)]
        painter.drawPolyline(QPolygonF(points))

    def _runs(self, halves):
        """Merges equal consecutive half-T-state values into (start half, end half, value)."""
        runs = []
        start = 0
        for i in range(1, len(halves) + 1):
            if i == len(halves) or halves[i] != halves[start]:
                runs.append((start, i, halves[start]))
                start = i
        return runs

    def _draw_line(self, painter, y, halves):
        high, low, middle = self._levels(y)
        half = self.column_width / 2
        x0 = self.label_width
        previous_y = None
        for start, end, value in self._runs(halves):
            xa, xb = x0 + start * half, x0 + end * half
            if value == "Z":
                painter.setPen(QPen(FLOAT_COLOR, 1.2, Qt.PenStyle.DashLine))
                level = middle
            elif value == "X":
                self._hatch(painter, xa, xb, high, low)
                previous_y = None
                continue
            else:
                painter.setPen(QPen(LINE_COLOR, 1.6))
                level = high if value else low
            if previous_y is not None and previous_y != level:
                painter.drawLine(QPointF(xa, previous_y), QPointF(xa, level))
            painter.drawLine(QPointF(xa, level), QPointF(xb, level))
            previous_y = level

    def _hatch(self, painter, xa, xb, high, low):
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor("#BFBFBF"), Qt.BrushStyle.BDiagPattern))
        painter.drawRect(QRectF(xa, high, xb - xa, low - high))
        painter.setPen(QPen(FLOAT_COLOR, 1))
        painter.drawLine(QPointF(xa, high), QPointF(xb, high))
        painter.drawLine(QPointF(xa, low), QPointF(xb, low))
        painter.restore()

    def _draw_bus(self, painter, y, halves, metrics):
        high, low, middle = self._levels(y)
        half = self.column_width / 2
        x0 = self.label_width
        slant = min(4.0, half / 3)
        for start, end, (_, value) in self._runs(halves):
            xa, xb = x0 + start * half, x0 + end * half
            if value == "Z":
                painter.setPen(QPen(FLOAT_COLOR, 1.2, Qt.PenStyle.DashLine))
                painter.drawLine(QPointF(xa, middle), QPointF(xb, middle))
                continue
            if value == "X":
                self._hatch(painter, xa, xb, high, low)
                continue
            kind, byte = value
            color = ADDRESS_COLOR if kind == "A" else DATA_COLOR
            shape = QPolygonF([
                QPointF(xa, middle), QPointF(xa + slant, high), QPointF(xb - slant, high),
                QPointF(xb, middle), QPointF(xb - slant, low), QPointF(xa + slant, low),
            ])
            fill = QColor(color)
            fill.setAlpha(28)
            painter.setPen(QPen(color, 1.4))
            painter.setBrush(fill)
            painter.drawPolygon(shape)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            text = "data" if byte is None else f"{byte:02X}H"
            if byte is not None:  # hex values in the fixed-width font
                painter.setFont(QFont("Consolas", 8))
                metrics = QFontMetrics(painter.font())
            if metrics.horizontalAdvance(text) > xb - xa - 2 * slant:
                text = "" if byte is None else f"{byte:02X}"
            painter.drawText(QRectF(xa, high, xb - xa, low - high), Qt.AlignmentFlag.AlignCenter, text)
            painter.setFont(QFont("Segoe UI", 8))


class TimingDiagramWindow(QWidget):
    """Separate, resizable window with a large timing diagram that follows the panel's selection."""

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("8085 Timing Diagram")
        self.resize(1100, 520)
        layout = QVBoxLayout(self)
        controls = QHBoxLayout()
        self.caption = QLabel("")
        self.caption.setFont(QFont("Segoe UI", 10))
        controls.addWidget(self.caption, 1)
        narrower = QPushButton("−")
        wider = QPushButton("+")
        for button, step in ((narrower, -8), (wider, 8)):
            button.setFixedWidth(32)
            button.clicked.connect(lambda _=False, s=step: self.diagram.set_column_width(self.diagram.column_width + s))
            controls.addWidget(button)
        layout.addLayout(controls)

        self.diagram = TimingDiagram(column_width=64)
        scroll = QScrollArea()
        scroll.setWidget(self.diagram)
        scroll.setWidgetResizable(False)
        scroll.setStyleSheet("background: white;")
        layout.addWidget(scroll, 1)

        legend = QLabel(
            "<span style='color:#1F5FBF'>■ address</span> &nbsp; "
            "<span style='color:#107C10'>■ data</span> &nbsp; "
            "<span style='color:#9A9A9A'>- - high impedance</span> &nbsp; "
            "▨ unspecified &nbsp;&nbsp; Hover over a T-state for an explanation. "
            "Status (IO/M, S1, S0) is valid for the whole machine cycle; "
            "wait states (READY) and HOLD are not simulated."
        )
        legend.setWordWrap(True)
        legend.setFont(QFont("Segoe UI", 8))
        layout.addWidget(legend)

    def show_record(self, title, cycles):
        total = sum(c.t_states for c in cycles)
        self.caption.setText(f"{title}  -  {len(cycles)} machine cycles, {total} T-states")
        self.diagram.set_cycles(cycles, title)


class BusCyclePanel(QWidget):
    """Side panel: history of recorded instructions, their machine cycles and a timing diagram."""

    COLUMNS = ("M", "Machine cycle", "T", "IO/M S1 S0", "Address", "Data", "Operation")
    record_selected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.records = []  # (title, cycles)
        self.window = None
        # The page scrolls as a whole when the tab is short; the table and the
        # diagram are always shown at their full height (only horizontal scrolling)
        page = hw.scroll_page(self)

        card = hw.Card("Machine cycles", "recorded while stepping and in runs at 200 Hz or less")
        top = QHBoxLayout()
        top.setSpacing(6)
        self.summary_label = QLabel("Step an instruction to see its machine cycles")
        self.summary_label.setFont(QFont("Segoe UI", 8))
        self.summary_label.setStyleSheet("background: transparent; color: #212121;")
        self.summary_label.setWordWrap(True)
        top.addWidget(self.summary_label, 1)
        self.diagram_button = hw.MaterialButton("Timing Diagram", hw.PRIMARY, filled=True)
        self.diagram_button.setToolTip("Open a large timing diagram window (Ctrl+T)")
        self.diagram_button.clicked.connect(self.show_diagram_window)
        self.clear_button = hw.MaterialButton("Clear", hw.PRIMARY)
        self.clear_button.clicked.connect(self.clear)
        top.addWidget(self.diagram_button, 0, Qt.AlignmentFlag.AlignTop)
        top.addWidget(self.clear_button, 0, Qt.AlignmentFlag.AlignTop)
        card.body.addLayout(top)

        self.trace_note = QLabel("")
        self.trace_note.setFont(QFont("Segoe UI", 8))
        self.trace_note.setStyleSheet("color: #8A6D00; background: #FFF8E1; padding: 3px 6px;")
        self.trace_note.setWordWrap(True)
        self.trace_note.hide()
        card.body.addWidget(self.trace_note)

        boxed = f"border: 1px solid {hw.BORDER}; background: white;"
        self.history = QListWidget()
        self.history.setFont(QFont("Consolas", 9))  # address + assembly code
        self.history.setStyleSheet(
            f"QListWidget {{ {boxed} }} QListWidget::item:selected {{ background: {hw.PRIMARY}; color: white; }}"
        )
        self.history.setMinimumHeight(70)
        self.history.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        self.history.currentRowChanged.connect(self._show_row)
        self.history.setToolTip("Instructions and interrupt acknowledges recorded so far")
        card.body.addWidget(self.history, 1)

        # Machine-cycle table: tall enough for the longest instruction, so it
        # never scrolls vertically; columns fit their contents and scroll sideways
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.verticalHeader().setDefaultSectionSize(TABLE_ROW_HEIGHT)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setFont(QFont("Segoe UI", 9))
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.table.setStyleSheet(
            f"QTableWidget {{ {boxed} }}"
            " QHeaderView::section { background: white; color: #6B6B6B; border: none;"
            " border-bottom: 1px solid #DDDDDD; padding: 3px; font: bold 8pt 'Segoe UI'; }"
        )
        header = self.table.horizontalHeader()
        last = len(self.COLUMNS) - 1
        for column in range(last):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(last, QHeaderView.ResizeMode.Fixed)  # sized by _fit_columns
        header.setStretchLastSection(False)
        self.table.horizontalScrollBar().rangeChanged.connect(lambda *_: self._fit_table_height())
        self.table.installEventFilter(self)
        card.body.addWidget(self.table)

        # Timing diagram: always its full height, scrolled sideways only
        self.diagram = TimingDiagram(column_width=34)
        self.diagram_scroll = QScrollArea()
        self.diagram_scroll.setWidget(self.diagram)
        self.diagram_scroll.setWidgetResizable(False)
        self.diagram_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.diagram_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.diagram_scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.diagram_scroll.setStyleSheet(f"QScrollArea {{ {boxed} }}")
        self.diagram_scroll.horizontalScrollBar().rangeChanged.connect(lambda *_: self._fit_diagram_height())
        card.body.addWidget(self.diagram_scroll)
        self._fit_table_height()
        self._fit_diagram_height()
        page.addWidget(card, 1)

    def eventFilter(self, watched, event):
        if watched is self.table and event.type() == event.Type.Resize:
            self._fit_columns()
        return super().eventFilter(watched, event)

    def _fit_columns(self):
        """The Operation column is as wide as its text, or wider to fill the table."""
        header = self.table.horizontalHeader()
        last = len(self.COLUMNS) - 1
        content = max(header.sectionSizeHint(last), self.table.sizeHintForColumn(last)) + 8
        others = sum(header.sectionSize(column) for column in range(last))
        width = max(content, self.table.viewport().width() - others)
        if header.sectionSize(last) != width:
            header.resizeSection(last, width)

    # Heights: content plus the horizontal scroll bar while it is shown ---
    @staticmethod
    def _scrollbar_room(area):
        bar = area.horizontalScrollBar()
        return bar.sizeHint().height() if bar.maximum() > 0 else 0

    def _fit_table_height(self):
        header = self.table.horizontalHeader()
        height = (max(header.height(), header.sizeHint().height())
                  + MAX_MACHINE_CYCLES * TABLE_ROW_HEIGHT
                  + 2 * self.table.frameWidth()
                  + self._scrollbar_room(self.table))
        if self.table.height() != height or self.table.minimumHeight() != height:
            self.table.setFixedHeight(height)

    def _fit_diagram_height(self):
        height = self.diagram.height() + 2 * self.diagram_scroll.frameWidth() + self._scrollbar_room(self.diagram_scroll)
        if self.diagram_scroll.minimumHeight() != height:
            self.diagram_scroll.setFixedHeight(height)

    # Records ----------------------------------------------------------
    def add_record(self, title, cycles):
        if not cycles:
            return
        self.records.append((title, list(cycles)))
        total = sum(c.t_states for c in cycles)
        self.history.addItem(f"{title}  ({total} T)")
        if len(self.records) > MAX_RECORDS:
            self.records.pop(0)
            self.history.takeItem(0)
        self.history.setCurrentRow(len(self.records) - 1)

    def clear(self):
        self.records.clear()
        self.history.clear()
        self._show(None)

    def set_trace_note(self, text):
        self.trace_note.setText(text)
        self.trace_note.setVisible(bool(text))

    def _show_row(self, row):
        self._show(self.records[row] if 0 <= row < len(self.records) else None)
        self.record_selected.emit(row)

    def _show(self, record):
        if record is None:
            self.summary_label.setText("Step an instruction to see its machine cycles")
            self.table.setRowCount(0)
            self.diagram.set_cycles([], "")
            if self.window is not None:
                self.window.show_record("", [])
            return
        title, cycles = record
        total = sum(c.t_states for c in cycles)
        sequence = " ".join(c.short_name + ("6" if c.kind in ("OF", "INA", "BIA") and c.t_states == 6 else "")
                            for c in cycles)
        self.summary_label.setText(f"<b>{title}</b><br>{len(cycles)} machine cycles, {total} T-states: {sequence}")
        self.table.setRowCount(len(cycles))
        for row, cycle in enumerate(cycles):
            values = (
                f"M{row + 1}",
                cycle.name,
                str(cycle.t_states),
                status_text(cycle),
                "" if cycle.address is None else f"{cycle.address:04X}H",
                "" if cycle.data is None else f"{cycle.data:02X}H",
                cycle.note,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setBackground(QColor(CYCLE_COLORS[cycle.kind]))
                if column in (4, 5):  # Address and Data: hex values
                    item.setFont(QFont("Consolas", 9))
                self.table.setItem(row, column, item)
        self._fit_columns()
        self._fit_table_height()
        self.diagram.set_cycles(cycles, title)
        self._fit_diagram_height()
        if self.window is not None:
            self.window.show_record(title, cycles)

    def current_record(self):
        row = self.history.currentRow()
        return self.records[row] if 0 <= row < len(self.records) else None

    def show_diagram_window(self):
        if self.window is None:
            self.window = TimingDiagramWindow(self)
        record = self.current_record()
        self.window.show_record(*(record or ("", [])))
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()


__all__ = ["BusCyclePanel", "TimingDiagram", "TimingDiagramWindow", "explain", "CYCLE_TYPES"]
