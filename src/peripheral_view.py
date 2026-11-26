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

"""Side panels for the 8255 PPI and the 8253 PIT."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QVBoxLayout, QWidget

from hw_widgets import (
    AMBER,
    Card,
    Chip,
    Led,
    MaterialButton,
    PinCell,
    TEAL,
    ToggleSwitch,
    caption,
    combo,
    field,
    scroll_page,
    set_text,
)
from peripherals import MODE_NAMES, PIT8253

PIN_CHOICES = (("not connected", None), ("TRAP", "TRAP"), ("RST 7.5", "RST7.5"),
               ("RST 6.5", "RST6.5"), ("RST 5.5", "RST5.5"))
PANEL_BACKGROUND = "#F7F5FA"


def _wiring_combo():
    box = combo(square=True)
    for text, pin in PIN_CHOICES:
        box.addItem(text, pin)
    return box


def _select_data(box, data):
    index = box.findData(data)
    if box.currentIndex() != index:
        box.blockSignals(True)
        box.setCurrentIndex(index)
        box.blockSignals(False)


def _divider():
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet("color: #ECECEC;")
    return line


def _scroll_page(widget):
    return scroll_page(widget)


def _chip_header(card, enabled, base_value, on_enable, on_base):
    """Connected switch on the title row; base port field and port address chips in the body."""
    switch = ToggleSwitch("Connected", color="#5C2D91")
    switch.setChecked(enabled)
    switch.setToolTip("Connect or disconnect the chip from the I/O bus")
    switch.toggled.connect(on_enable)
    row = QHBoxLayout()
    row.setSpacing(4)
    row.addWidget(caption("Base port"))
    base = field(f"{base_value:02X}H", square=True)
    base.setToolTip("Base I/O port address (the chip uses this and the next three ports)")
    base.editingFinished.connect(on_base)
    row.addWidget(base)
    chips = [Chip("", "grey", square=True) for _ in range(4)]
    for chip in chips:
        row.addWidget(chip)
    row.addStretch(1)
    row.addWidget(switch)
    card.body.addLayout(row)
    return switch, base, chips


# ======================================================================
# 8255
# ======================================================================


class PPIPanel(QWidget):
    """8255 PPI: configuration, the 24 port pins, handshake pulses and interrupt wiring."""

    def __init__(self, simulator):
        super().__init__()
        self.sim = simulator
        layout = _scroll_page(self)
        bus = simulator.peripherals

        # Chip card -----------------------------------------------------
        card = Card("8255 PPI", "Programmable Peripheral Interface", square=True)
        self.enabled, self.base, self.address_chips = _chip_header(
            card, bus.ppi_enabled, bus.ppi_base, self._enable, self._set_base)
        row = QHBoxLayout()
        row.setSpacing(4)
        self.control_chip = Chip("CW 9BH", "primary", square=True)
        self.control_chip.setToolTip("Last mode-set control word")
        self.group_a_chip = Chip("", "grey", mono=False, square=True)
        self.group_b_chip = Chip("", "grey", mono=False, square=True)
        for chip in (self.control_chip, self.group_a_chip, self.group_b_chip):
            row.addWidget(chip)
        row.addStretch(1)
        card.body.addLayout(row)
        self.config_label = caption("")
        self.config_label.setWordWrap(True)
        card.body.addWidget(self.config_label)
        layout.addWidget(card)

        # Ports card ----------------------------------------------------
        card = Card("Port pins", "PA7 ... PA0, PB7 ... PB0, PC7 ... PC0", square=True)
        grid = QGridLayout()
        grid.setHorizontalSpacing(2)
        grid.setVerticalSpacing(4)
        self.port_labels = []
        self.direction_chips = []
        self.value_chips = []
        self.bits = []
        for port, name in enumerate("ABC"):
            info = QVBoxLayout()
            info.setSpacing(2)
            label = caption(f"Port {name}", "#212121", 9, True)
            direction = Chip("", "grey", mono=False, square=True)
            value = Chip("00H", "primary", square=True)
            info.addWidget(label)
            row = QHBoxLayout()
            row.setSpacing(3)
            row.addWidget(direction)
            row.addWidget(value)
            row.addStretch(1)
            info.addLayout(row)
            holder = QWidget()
            holder.setObjectName("portInfo")
            holder.setStyleSheet("#portInfo { background: transparent; }")
            holder.setLayout(info)
            holder.setMinimumWidth(104)
            grid.addWidget(holder, port, 0)
            self.port_labels.append(label)
            self.direction_chips.append(direction)
            self.value_chips.append(value)
            cells = []
            for column, bit in enumerate(range(7, -1, -1)):
                cell = PinCell(str(bit))
                cell.toggled.connect(lambda checked, p=port, b=bit: self._pin_toggled(p, b, checked))
                grid.addWidget(cell, port, column + 1)
                cells.append(cell)
            self.bits.append(cells)
        card.body.addLayout(grid)
        legend = QHBoxLayout()
        legend.setSpacing(10)
        for text, color in (("switch = input pin (click to drive it)", TEAL), ("red = output pin", "#E53935"),
                            ("amber = handshake output", AMBER)):
            legend.addWidget(caption("● " + text, color, 7))
        legend.addStretch(1)
        card.body.addLayout(legend)
        layout.addWidget(card)

        # Handshake card ------------------------------------------------
        card = Card("Handshake and interrupts", "modes 1 and 2", square=True)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.handshake = {}
        for key, tip in (("STB A", "Input device strobes the data on port A into the 8255 (mode 1 input, mode 2)"),
                         ("ACK A", "Output device takes the data from port A (mode 1 output, mode 2)"),
                         ("STB B", "Input device strobes the data on port B into the 8255 (mode 1 input)"),
                         ("ACK B", "Output device takes the data from port B (mode 1 output)")):
            button = MaterialButton(key, TEAL, square=True)
            button.setToolTip(tip)
            button.clicked.connect(lambda _=False, k=key: self._handshake(k))
            row.addWidget(button)
            self.handshake[key] = button
        row.addStretch(1)
        card.body.addLayout(row)
        self.wiring = {}
        self.intr_leds = {}
        for source, pin in (("INTR-A", "PC3"), ("INTR-B", "PC0")):
            row = QHBoxLayout()
            row.setSpacing(6)
            led = Led("", AMBER, 14)
            led.setToolTip(f"{source.replace('-', ' ')} output ({pin})")
            row.addWidget(led)
            row.addWidget(caption(f"{source.replace('-', ' ')} ({pin})  →", "#212121", 8, True))
            box = _wiring_combo()
            box.setToolTip("Connect the 8255 interrupt request output to an 8085 interrupt input")
            box.currentIndexChanged.connect(lambda _i, s=source, c=box: self.sim.set_peripheral_wiring(s, c.currentData()))
            row.addWidget(box)
            row.addStretch(1)
            card.body.addLayout(row)
            self.wiring[source] = box
            self.intr_leds[source] = led
        layout.addWidget(card)
        layout.addStretch(1)
        self.refresh()

    # ------------------------------------------------------------------
    def _enable(self, checked):
        self.sim._sync_clock()
        self.sim.peripherals.ppi_enabled = checked
        self.sim.add_to_log(f"8255 PPI {'connected' if checked else 'disconnected'}", "SYSTEM")
        self.sim.after_peripheral_change()

    def _set_base(self):
        try:
            base = self.sim._parse_byte(self.base.text(), "8255 base port")
        except ValueError as e:
            self.sim.add_to_log(f"Error: {e}", "ERROR")
            base = self.sim.peripherals.ppi_base
        if base != self.sim.peripherals.ppi_base:
            self.sim._sync_clock()
            self.sim.peripherals.ppi_base = base
            self.sim.add_to_log(f"8255 PPI moved to ports {base:02X}H-{(base + 3) & 0xFF:02X}H", "SYSTEM")
        self.base.setText(f"{self.sim.peripherals.ppi_base:02X}H")
        self.refresh()

    def _pin_toggled(self, port, bit, checked):
        self.sim._sync_clock()
        ppi = self.sim.peripherals.ppi
        value = ppi.pins[port]
        value = value | (1 << bit) if checked else value & ~(1 << bit)
        ppi.set_pins(port, value)
        self.sim.peripherals._after_access()
        self.sim.after_peripheral_change()

    def _handshake(self, key):
        self.sim._sync_clock()
        bus = self.sim.peripherals
        kind, port = key.split()
        if kind == "STB":
            ok = bus.ppi.strobe(port)
            message = (f"8255: STB {port} - port {port} pins ({bus.ppi.pins[0 if port == 'A' else 1]:02X}H) "
                       f"latched, IBF {port} = 1" if ok else f"8255: STB {port} has no effect in this mode")
        else:
            data = bus.ppi.acknowledge(port)
            message = (f"8255: ACK {port} - the output device took {data:02X}H, OBF {port} inactive"
                       if data is not None else f"8255: ACK {port} has no effect in this mode")
        bus._after_access()
        self.sim.add_to_log(message, "SYSTEM")
        self.sim.after_peripheral_change()

    # ------------------------------------------------------------------
    def refresh(self):
        bus = self.sim.peripherals
        ppi = bus.ppi
        enabled = bus.ppi_enabled
        base = bus.ppi_base
        if self.enabled.isChecked() != enabled:
            self.enabled.blockSignals(True)
            self.enabled.setChecked(enabled)
            self.enabled.blockSignals(False)
        for chip, (name, offset) in zip(self.address_chips, (("A", 0), ("B", 1), ("C", 2), ("CW", 3))):
            set_text(chip, f"{name} {(base + offset) & 0xFF:02X}H")
            chip.set_kind("primary" if enabled else "grey")
        modes = {0: "mode 0", 1: "mode 1", 2: "mode 2"}
        set_text(self.control_chip, f"CW {ppi.control:02X}H")
        set_text(self.group_a_chip, f"Group A · {modes[ppi.mode_a]}")
        set_text(self.group_b_chip, f"Group B · {modes[ppi.mode_b]}")
        if enabled:
            a = "bidirectional" if ppi.mode_a == 2 else ("input" if ppi.a_input else "output")
            text = (f"Port A {a}, PC7-PC4 {'input' if ppi.c_upper_input else 'output'}; "
                    f"port B {'input' if ppi.b_input else 'output'}, "
                    f"PC3-PC0 {'input' if ppi.c_lower_input else 'output'}")
        else:
            text = "Disconnected: IN/OUT on these ports use the I/O tab latches"
        set_text(self.config_label, text)

        roles = ppi.c_roles()
        directions = [
            ("bidir", "amber") if ppi.mode_a == 2 else (("in", "teal") if ppi.a_input else ("out", "red")),
            ("in", "teal") if ppi.b_input else ("out", "red"),
            ("mixed", "grey"),
        ]
        for port in range(3):
            value, driven = ppi.port_pins(port)
            text, kind = directions[port]
            if port == 2:
                kinds = {r in ("in", "out") and r or "control" for r in roles}
                text = ("in" if kinds == {"in"} else "out" if kinds == {"out"} else "mixed")
                kind = {"in": "teal", "out": "red"}.get(text, "grey")
            set_text(self.direction_chips[port], text)
            self.direction_chips[port].set_kind(kind if enabled else "grey")
            set_text(self.value_chips[port], f"{value:02X}H")
            for column, bit in enumerate(range(7, -1, -1)):
                level = (value >> bit) & 1
                label = str(bit)
                control = False
                if port == 2 and roles[bit] not in ("in", "out"):
                    label = roles[bit].split("-")[0]
                    control = True
                tip = f"P{'ABC'[port]}{bit}" + (f": {roles[bit]}" if port == 2 else "")
                self.bits[port][column].show_state(
                    label, level, bool((driven >> bit) & 1) or not enabled, tip, control)

        valid = {
            "STB A": ppi.mode_a == 2 or (ppi.mode_a == 1 and ppi.a_input),
            "ACK A": ppi.mode_a == 2 or (ppi.mode_a == 1 and not ppi.a_input),
            "STB B": ppi.mode_b == 1 and ppi.b_input,
            "ACK B": ppi.mode_b == 1 and not ppi.b_input,
        }
        for key, button in self.handshake.items():
            button.setEnabled(enabled and valid[key])
        levels = ppi.interrupt_outputs()
        for source, box in self.wiring.items():
            _select_data(box, bus.wiring.get(source))
            self.intr_leds[source].set_on(enabled and levels[source])


# ======================================================================
# 8253
# ======================================================================


class _CounterRow(QWidget):
    """One 8253 counter: mode, count and OUT on the first line; CLK, GATE and wiring on the second."""

    def __init__(self, panel, index):
        super().__init__()
        self.panel = panel
        self.index = index
        self.setObjectName("counterRow")
        self.setStyleSheet("#counterRow { background: transparent; }")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(3)

        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(caption(f"Counter {index}", "#212121", 9, True))
        self.status = caption("")
        row.addWidget(self.status, 1)
        self.value = caption("", "#212121", 8, True)
        self.value.setFont(QFont("Consolas", 9, QFont.Weight.Bold))
        self.value.setFixedWidth(46)  # fixed size: the live value never relayouts the panel
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.value.setToolTip("Current count")
        row.addWidget(self.value)
        self.out = Led("", "#E53935", 14)
        self.out.setToolTip(f"OUT{index}")
        row.addWidget(self.out)
        layout.addLayout(row)

        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(caption("CLK"))
        self.source = combo(square=True)
        for source in PIT8253.CLOCK_SOURCES:
            if source == "OUT of previous counter":
                if index == 0:
                    continue
                self.source.addItem(f"OUT{index - 1}", source)
            elif source == "CLK OUT":
                self.source.addItem("CPU CLK OUT", source)
            else:
                self.source.addItem(source.replace("CLK OUT", "CPU CLK OUT"), source)
        self.source.setToolTip("What drives this counter's CLK input")
        self.source.currentIndexChanged.connect(lambda _i: panel.sim.set_counter_source(index, self.source.currentData()))
        row.addWidget(self.source)
        self.pulse = MaterialButton("Pulse", square=True)
        self.pulse.setToolTip("Apply one CLK pulse (Manual clock)")
        self.pulse.clicked.connect(lambda: panel.sim.pulse_counter_clock(index))
        row.addWidget(self.pulse)
        self.gate = ToggleSwitch("GATE", TEAL)
        self.gate.setChecked(True)
        self.gate.setToolTip("GATE input level (on = high)")
        self.gate.toggled.connect(lambda level: panel.sim.set_counter_gate(index, level))
        row.addWidget(self.gate)
        row.addWidget(caption("OUT →"))
        self.wiring = _wiring_combo()
        self.wiring.setToolTip("Connect OUT to an 8085 interrupt input")
        self.wiring.currentIndexChanged.connect(
            lambda _i: panel.sim.set_peripheral_wiring(f"OUT{index}", self.wiring.currentData()))
        row.addWidget(self.wiring)
        row.addStretch(1)
        layout.addLayout(row)

    def refresh(self, bus):
        counter = bus.pit.counters[self.index]
        if counter.mode is None:
            set_text(self.status, "not programmed")
            set_text(self.value, "")
        else:
            rw = {1: "LSB", 2: "MSB", 3: "LSB+MSB"}[counter.rw]
            if counter.cr is None:
                count = "no count"
            elif counter.bcd:
                count = f"count {counter.cr} BCD"
            else:
                count = f"count {counter.cr:04X}H"
            set_text(self.status, f"Mode {counter.mode} {MODE_NAMES[counter.mode]}, {rw}, {count}")
            set_text(self.value, f"{counter.value():04X}H" if counter.loaded else "----")
        self.out.set_on(counter.out)
        source = bus.pit.sources[self.index]
        _select_data(self.source, source)
        self.pulse.setEnabled(source == "Manual" and bus.pit_enabled)
        if self.gate.isChecked() != bool(counter.gate):
            self.gate.blockSignals(True)
            self.gate.setChecked(bool(counter.gate))
            self.gate.blockSignals(False)
            self.gate.update()
        _select_data(self.wiring, bus.wiring.get(f"OUT{self.index}"))


class PITPanel(QWidget):
    """8253 PIT: configuration and the three counters with their CLK, GATE and OUT."""

    def __init__(self, simulator):
        super().__init__()
        self.sim = simulator
        layout = _scroll_page(self)
        bus = simulator.peripherals
        card = Card("8253 PIT", "Programmable Interval Timer", square=True)
        self.enabled, self.base, self.address_chips = _chip_header(
            card, bus.pit_enabled, bus.pit_base, self._enable, self._set_base)
        layout.addWidget(card)

        card = Card("Counters", "CPU CLK OUT = one CLK pulse per T-state", square=True)
        self.counters = []
        for index in range(3):
            if index:
                card.body.addWidget(_divider())
            row = _CounterRow(self, index)
            card.body.addWidget(row)
            self.counters.append(row)
        layout.addWidget(card)
        layout.addStretch(1)
        self.refresh()

    def _enable(self, checked):
        self.sim._sync_clock()
        self.sim.peripherals.pit_enabled = checked
        self.sim.add_to_log(f"8253 PIT {'connected' if checked else 'disconnected'}", "SYSTEM")
        self.sim.after_peripheral_change()

    def _set_base(self):
        try:
            base = self.sim._parse_byte(self.base.text(), "8253 base port")
        except ValueError as e:
            self.sim.add_to_log(f"Error: {e}", "ERROR")
            base = self.sim.peripherals.pit_base
        if base != self.sim.peripherals.pit_base:
            self.sim._sync_clock()
            self.sim.peripherals.pit_base = base
            self.sim.add_to_log(f"8253 PIT moved to ports {base:02X}H-{(base + 3) & 0xFF:02X}H", "SYSTEM")
        self.base.setText(f"{self.sim.peripherals.pit_base:02X}H")
        self.refresh()

    def refresh(self):
        bus = self.sim.peripherals
        base = bus.pit_base
        enabled = bus.pit_enabled
        if self.enabled.isChecked() != enabled:
            self.enabled.blockSignals(True)
            self.enabled.setChecked(enabled)
            self.enabled.blockSignals(False)
        for chip, (name, offset) in zip(self.address_chips, (("C0", 0), ("C1", 1), ("C2", 2), ("CW", 3))):
            set_text(chip, f"{name} {(base + offset) & 0xFF:02X}H")
            chip.set_kind("primary" if enabled else "grey")
        for row in self.counters:
            if row.isEnabled() != enabled:
                row.setEnabled(enabled)
            row.refresh(bus)
