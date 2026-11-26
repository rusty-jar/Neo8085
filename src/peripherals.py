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
Peripheral chips on the 8085 I/O bus: the Intel 8255A Programmable
Peripheral Interface and the Intel 8253 Programmable Interval Timer.

Both are I/O mapped at four consecutive port addresses (A1 A0 = 00, 01, 10,
11), as on 8085 trainer kits. The PeripheralBus routes IN/OUT to the chips,
keeps the 8253 counters in step with the CPU clock and drives the 8085
interrupt pins from chip outputs (8253 OUT0-2, 8255 INTR A/B).

Timing
    The 8253 counters are clocked from the CPU's CLK OUT (one pulse per
    T-state), CLK OUT / 2, the OUT of the previous counter, or by hand. The
    counters are brought up to date lazily: when the CPU accesses a chip (at
    the trailing edge of RD or WR, the end of T3 of the I/O machine cycle)
    and when an output wired to an interrupt pin is due to change, so the
    simulation stays exact without slowing the CPU down. Interrupt requests
    carry the T-state at which they appear, so the CPU can sample them in the
    next-to-last clock cycle of an instruction.
"""

INF = float("inf")


# ======================================================================
# Intel 8255A Programmable Peripheral Interface
# ======================================================================


class PPI8255:
    """
    Intel 8255A. Port A, port B, port C and the control register at offsets
    0-3.

    Mode set (control word with D7 = 1):
        D6 D5  group A mode (00 = mode 0, 01 = mode 1, 1x = mode 2)
        D4     port A          1 = input, 0 = output
        D3     port C upper    1 = input, 0 = output
        D2     group B mode    (0 = mode 0, 1 = mode 1)
        D1     port B          1 = input, 0 = output
        D0     port C lower    1 = input, 0 = output
        Writing a mode word clears all output latches and status flip-flops.
    Bit set/reset (D7 = 0): D3-D1 select a port C bit, D0 is its new value.
        In modes 1 and 2 the bits at the STB/ACK positions set the INTE
        (interrupt enable) flip-flops instead.
    RESET puts all ports in mode 0 input (control word 9BH).

    Mode 1 port C use (A = group A, B = group B):
        A input:  PC4 STB-A (in), PC5 IBF-A (out), PC3 INTR-A, INTE-A = PC4
        A output: PC7 OBF-A (out, active low), PC6 ACK-A (in), PC3 INTR-A, INTE-A = PC6
        B input:  PC2 STB-B (in), PC1 IBF-B (out), PC0 INTR-B, INTE-B = PC2
        B output: PC1 OBF-B (out, active low), PC2 ACK-B (in), PC0 INTR-B, INTE-B = PC2
    In modes 1 and 2, writing port C changes only its spare general-purpose
    outputs, and those in the upper half (PC7-PC4) only through bit set/reset.
    Mode 2 (port A bidirectional): PC7 OBF-A, PC6 ACK-A, PC5 IBF-A, PC4 STB-A,
        PC3 INTR-A, INTE1 = PC6 (output), INTE2 = PC4 (input). Port A drives
        its pins only while ACK-A is low.
    Reading port C in mode 1/2 returns the status word: IBF, OBF and INTR
    bits, and the INTE flip-flops at the STB/ACK bit positions.
    Reading the control register is not allowed on the 8255A; the data bus
    floats and the CPU reads FFH.
    """

    NAME = "8255"

    def __init__(self):
        self.pins = [0, 0, 0]  # levels external devices drive on ports A, B, C
        self.reset()

    # ------------------------------------------------------------------
    def reset(self):
        """RESET pin: all ports become mode 0 inputs (control word 9BH)."""
        self._mode_set(0x9B)

    def _mode_set(self, word):
        self.control = word & 0xFF
        self.mode_a = 2 if word & 0x40 else (1 if word & 0x20 else 0)
        self.mode_b = 1 if word & 0x04 else 0
        self.a_input = bool(word & 0x10)
        self.c_upper_input = bool(word & 0x08)
        self.b_input = bool(word & 0x02)
        self.c_lower_input = bool(word & 0x01)
        # Output latches and status flip-flops are cleared by a mode set
        self.latch = [0, 0, 0]  # output latches A, B, C
        self.in_latch = [0, 0]  # strobed input latches A, B (mode 1/2)
        self.ibf = [0, 0]  # input buffer full A, B
        self.obf = [0, 0]  # output buffer full A, B (the OBF pin is active low)
        self.inte = [0, 0]  # INTE A (mode 1) and INTE B
        self.inte1 = 0  # mode 2: output interrupt enable (PC6)
        self.inte2 = 0  # mode 2: input interrupt enable (PC4)
        self.ack_low = 0  # mode 2: ACK-A held low (port A drives its pins)

    # ------------------------------------------------------------------
    # Port C bit roles
    # ------------------------------------------------------------------
    def c_roles(self):
        """Role of each port C bit (index 0-7): 'in', 'out' or a control signal name."""
        roles = []
        for bit in range(8):
            upper = bit >= 4
            roles.append("in" if (self.c_upper_input if upper else self.c_lower_input) else "out")
        if self.mode_b == 1:
            if self.b_input:
                roles[2], roles[1], roles[0] = "STB-B", "IBF-B", "INTR-B"
            else:
                roles[2], roles[1], roles[0] = "ACK-B", "OBF-B", "INTR-B"
        if self.mode_a == 1:
            roles[3] = "INTR-A"
            if self.a_input:
                roles[4], roles[5] = "STB-A", "IBF-A"
            else:
                roles[6], roles[7] = "ACK-A", "OBF-A"
        elif self.mode_a == 2:
            roles[3], roles[4], roles[5], roles[6], roles[7] = "INTR-A", "STB-A", "IBF-A", "ACK-A", "OBF-A"
        return roles

    # INTR as defined in the 8255A data sheet (STB and ACK are high between pulses):
    #   input:  INTR = INTE . IBF            output: INTR = INTE . (OBF inactive)
    #   mode 2: INTR = INTE1 . (OBF inactive) + INTE2 . IBF
    def intr_a(self):
        if self.mode_a == 1:
            ready = self.ibf[0] if self.a_input else (not self.obf[0])
            return int(bool(self.inte[0] and ready))
        if self.mode_a == 2:
            return int(bool((self.inte1 and not self.obf[0]) or (self.inte2 and self.ibf[0])))
        return 0

    def intr_b(self):
        if self.mode_b == 1:
            ready = self.ibf[1] if self.b_input else (not self.obf[1])
            return int(bool(self.inte[1] and ready))
        return 0

    def interrupt_outputs(self):
        return {"INTR-A": self.intr_a(), "INTR-B": self.intr_b()}

    def _control_output_level(self, role):
        if role == "INTR-A":
            return self.intr_a()
        if role == "INTR-B":
            return self.intr_b()
        if role == "IBF-A":
            return self.ibf[0]
        if role == "IBF-B":
            return self.ibf[1]
        if role == "OBF-A":
            return 0 if self.obf[0] else 1  # active low
        if role == "OBF-B":
            return 0 if self.obf[1] else 1
        return None  # STB/ACK are inputs

    # ------------------------------------------------------------------
    # Pin view (what an oscilloscope on the port pins would show)
    # ------------------------------------------------------------------
    def port_pins(self, port):
        """(value on the 8 pins, mask of the bits the 8255 drives)."""
        if port == 0:
            if self.mode_a == 2:
                if self.ack_low:
                    return self.latch[0], 0xFF
                return self.pins[0], 0x00
            if self.a_input:
                return self.pins[0], 0x00
            return self.latch[0], 0xFF
        if port == 1:
            if self.b_input:
                return self.pins[1], 0x00
            return self.latch[1], 0xFF
        value = 0
        driven = 0
        for bit, role in enumerate(self.c_roles()):
            if role == "out":
                level = (self.latch[2] >> bit) & 1
                driven |= 1 << bit
            elif role == "in" or role.startswith(("STB", "ACK")):
                level = (self.pins[2] >> bit) & 1
            else:
                level = self._control_output_level(role)
                driven |= 1 << bit
            value |= level << bit
        return value, driven

    # ------------------------------------------------------------------
    # CPU side
    # ------------------------------------------------------------------
    def read(self, offset):
        if offset == 0:
            if self.mode_a in (1, 2) and (self.a_input or self.mode_a == 2):
                value = self.in_latch[0]
                self._cpu_read_input(0)
                return value
            if self.a_input:
                return self.pins[0]
            return self.latch[0]
        if offset == 1:
            if self.mode_b == 1 and self.b_input:
                value = self.in_latch[1]
                self._cpu_read_input(1)
                return value
            if self.b_input:
                return self.pins[1]
            return self.latch[1]
        if offset == 2:
            return self.read_port_c()
        return 0xFF  # control register cannot be read: floating bus

    def read_port_c(self):
        """Port C as read by the CPU: I/O bits, or the mode 1/2 status word."""
        roles = self.c_roles()
        value = 0
        for bit, role in enumerate(roles):
            if role == "in":
                level = (self.pins[2] >> bit) & 1
            elif role == "out":
                level = (self.latch[2] >> bit) & 1
            elif role == "STB-A" or (role == "ACK-A" and self.mode_a == 1):
                level = self.inte[0] if self.mode_a == 1 else self.inte2
            elif role == "ACK-A":  # mode 2
                level = self.inte1
            elif role in ("STB-B", "ACK-B"):
                level = self.inte[1]
            else:
                level = self._control_output_level(role)
            value |= level << bit
        if self.mode_a == 2:  # PC4 reads INTE2 (STB position), PC6 reads INTE1 (ACK position)
            value = (value & ~0x50) | (self.inte2 << 4) | (self.inte1 << 6)
        return value

    def _cpu_read_input(self, index):
        # RD resets IBF (and with it INTR)
        self.ibf[index] = 0

    def write(self, offset, value):
        value &= 0xFF
        if offset == 3:
            if value & 0x80:
                self._mode_set(value)
            else:
                self._bit_set_reset((value >> 1) & 7, value & 1)
            return
        if offset == 0:
            self.latch[0] = value
            if (self.mode_a == 1 and not self.a_input) or self.mode_a == 2:
                self.obf[0] = 1  # WR sets OBF (the OBF pin goes low) and resets INTR
            return
        if offset == 1:
            self.latch[1] = value
            if self.mode_b == 1 and not self.b_input:
                self.obf[1] = 1
            return
        # Port C: only the bits that are general-purpose outputs change. When
        # group A is in mode 1 or 2, the spare outputs of the upper half
        # (PC7-PC4) "must be individually accessed using the bit set/reset
        # function" (Intel 8255A data sheet); the lower ones can be written.
        mask = 0
        for bit, role in enumerate(self.c_roles()):
            if role == "out" and not (bit >= 4 and self.mode_a in (1, 2)):
                mask |= 1 << bit
        self.latch[2] = (self.latch[2] & ~mask) | (value & mask)

    def _bit_set_reset(self, bit, level):
        roles = self.c_roles()
        role = roles[bit]
        if self.mode_a == 1 and role in ("STB-A", "ACK-A"):
            self.inte[0] = level
            return
        if self.mode_a == 2 and role == "STB-A":
            self.inte2 = level
            return
        if self.mode_a == 2 and role == "ACK-A":
            self.inte1 = level
            return
        if self.mode_b == 1 and role in ("STB-B", "ACK-B"):
            self.inte[1] = level
            return
        if level:
            self.latch[2] |= 1 << bit
        else:
            self.latch[2] &= ~(1 << bit)

    # ------------------------------------------------------------------
    # Device side (the peripheral connected to the ports)
    # ------------------------------------------------------------------
    def set_pins(self, port, value):
        """Levels an external device drives on port A, B or C (input bits only matter)."""
        self.pins[port] = value & 0xFF

    def strobe(self, port, value=None):
        """
        STB pulse from an input device (mode 1 input, or mode 2 for port A):
        the data on the pins is latched, IBF is set and, when STB returns
        high, INTR is set if INTE is 1. Returns False if the port is not in
        a strobed input mode.
        """
        index = 0 if port == "A" else 1
        if value is not None:
            self.pins[index] = value & 0xFF
        if index == 0 and not (self.mode_a == 2 or (self.mode_a == 1 and self.a_input)):
            return False
        if index == 1 and not (self.mode_b == 1 and self.b_input):
            return False
        self.in_latch[index] = self.pins[index]
        self.ibf[index] = 1
        return True

    def acknowledge(self, port):
        """
        ACK pulse from an output device (mode 1 output, or mode 2 for port A):
        the device has taken the data, OBF goes inactive (high) and, when ACK
        returns high, INTR is set if INTE is 1. Returns the data the device
        read from the port pins, or None if the port is not in a handshake
        output mode.
        """
        index = 0 if port == "A" else 1
        if index == 0 and not (self.mode_a == 2 or (self.mode_a == 1 and not self.a_input)):
            return None
        if index == 1 and not (self.mode_b == 1 and not self.b_input):
            return None
        self.obf[index] = 0  # in mode 2, port A drives its pins while ACK is low
        return self.latch[index]

    # ------------------------------------------------------------------
    def describe(self):
        """Human-readable configuration."""
        modes = {0: "mode 0", 1: "mode 1", 2: "mode 2"}
        a = "bidirectional" if self.mode_a == 2 else ("input" if self.a_input else "output")
        parts = [
            f"Control word {self.control:02X}H",
            f"Group A: {modes[self.mode_a]}, port A {a}, PC7-PC4 {'input' if self.c_upper_input else 'output'}",
            f"Group B: {modes[self.mode_b]}, port B {'input' if self.b_input else 'output'}, "
            f"PC3-PC0 {'input' if self.c_lower_input else 'output'}",
        ]
        return parts


# ======================================================================
# Intel 8253 Programmable Interval Timer
# ======================================================================

MODE_NAMES = {
    0: "interrupt on terminal count",
    1: "hardware retriggerable one-shot",
    2: "rate generator",
    3: "square wave generator",
    4: "software triggered strobe",
    5: "hardware triggered strobe",
}


def _from_bcd(value):
    digits = [(value >> shift) & 0xF for shift in (12, 8, 4, 0)]
    return sum(min(d, 9) * 10 ** (3 - i) for i, d in enumerate(digits))


def _to_bcd(value):
    value %= 10000
    return int(str(value), 16)


class Counter8253:
    """
    One 16-bit down counter of the 8253.

    Control word (written to the control register):
        D7 D6  SC1 SC0   counter select 0-2 (11 is illegal on the 8253)
        D5 D4  RW1 RW0   00 counter latch, 01 LSB only, 10 MSB only, 11 LSB then MSB
        D3-D1  M2 M1 M0  mode 0-5 (x10 = 2, x11 = 3)
        D0     BCD       0 = binary (16 bit), 1 = BCD (4 decades)
    A count of 0 means 65536 (binary) or 10000 (BCD). After a count is
    written it is loaded into the counting element on the next CLK pulse;
    that pulse does not decrement the count. The counter decrements on the
    falling edge of CLK.
    """

    def __init__(self, index):
        self.index = index
        self.power_on()

    def power_on(self):
        # The 8253 has no RESET input: after power-on the counters are unprogrammed
        self.mode = None
        self.rw = 3
        self.bcd = False
        self.cr = None  # count register (count written by the CPU)
        self.ce = 0  # counting element
        self.out = 0
        self.gate = 1
        self.loaded = False  # the counting element holds a count
        self.pending_load = False  # load the count register on the next CLK
        self.triggered = False  # mode 1/5: GATE rising edge seen
        self.armed = False  # mode 1/4/5: terminal count not reached yet for this load
        self.strobe = False  # mode 4/5: OUT is low for this one clock
        self.half = 0  # mode 3: CLK pulses left in this half cycle
        self.fresh = False  # mode 3: the count has just been (re)loaded, not yet decremented
        self.warning = None  # programming the data sheets call illegal (read and cleared by the GUI)
        self.active = None  # mode 2/3: the count the current period runs with
        self.write_msb_next = False
        self.partial = 0
        self.read_msb_next = False
        self.latched = None  # value held by a counter latch command
        self.stopped = False  # mode 0: first byte of a new count written

    @property
    def modulus(self):
        return 10000 if self.bcd else 0x10000

    # ------------------------------------------------------------------
    # CPU interface
    # ------------------------------------------------------------------
    def control_word(self, word):
        rw = (word >> 4) & 3
        if rw == 0:  # counter latch command
            if self.latched is None:
                self.latched = self.value()
                self.read_msb_next = False
            return
        mode = (word >> 1) & 7
        if mode >= 6:
            mode -= 4
        self.rw = rw
        self.mode = mode
        self.bcd = bool(word & 1)
        self.cr = None
        self.loaded = False
        self.pending_load = False
        self.triggered = False
        self.armed = False
        self.strobe = False
        self.stopped = False
        self.write_msb_next = False
        self.read_msb_next = False
        self.latched = None
        self.out = 0 if mode == 0 else 1

    def write(self, byte):
        if self.mode is None:
            return
        byte &= 0xFF
        if self.rw == 1:
            raw = byte
        elif self.rw == 2:
            raw = byte << 8
        elif not self.write_msb_next:
            self.partial = byte
            self.write_msb_next = True
            if self.mode == 0:  # writing the first byte stops counting, OUT goes low
                self.stopped = True
                self.out = 0
            return
        else:
            raw = (byte << 8) | self.partial
            self.write_msb_next = False
        count = _from_bcd(raw) if self.bcd else raw
        if self.mode == 2 and count == 1:
            self.warning = (f"8253 counter {self.index}: a count of 1 is illegal in mode 2 "
                            "(Intel 8254 data sheet); OUT stays high")
        self._new_count(count)

    def _new_count(self, count):
        self.cr = count
        self.stopped = False
        mode = self.mode
        if mode == 0:
            self.out = 0
            self.pending_load = True
        elif mode == 4:
            self.pending_load = True
        elif mode in (2, 3):
            if not self.loaded:
                self.pending_load = True
            # otherwise the new count is used at the end of the period / half cycle
        # modes 1 and 5 wait for a GATE trigger

    def value(self):
        """
        Current count as the CPU would read it (binary or BCD). In mode 3 the
        8253 counts down by two (Intel 8253 data sheet): right after a load or
        reload the counting element holds the count N; for odd N the first
        pulse after the load subtracts 1 and the first pulse after the reload
        3, every other pulse 2. So between those points it holds twice the
        pulses left in the half cycle.
        """
        count = self.ce
        if self.mode == 3 and self.loaded:
            count = (self.active if self.active is not None else (self.cr or 0)) if self.fresh else self.half * 2
        count %= self.modulus
        return _to_bcd(count) if self.bcd else count

    def read(self):
        value = self.latched if self.latched is not None else self.value()
        if self.rw == 1:
            byte = value & 0xFF
            done = True
        elif self.rw == 2:
            byte = value >> 8
            done = True
        else:
            byte = (value >> 8) if self.read_msb_next else (value & 0xFF)
            done = self.read_msb_next
            self.read_msb_next = not self.read_msb_next
        if done:
            self.latched = None
        return byte & 0xFF

    def set_gate(self, level):
        level = 1 if level else 0
        rising = level and not self.gate
        self.gate = level
        if self.mode in (2, 3) and not level:
            self.out = 1  # GATE low forces OUT high immediately
        if rising and self.cr is not None:
            if self.mode in (1, 5):
                self.triggered = True
            elif self.mode in (2, 3):
                self.pending_load = True

    # ------------------------------------------------------------------
    # Clocking
    # ------------------------------------------------------------------
    def _counting(self):
        """Whether CLK pulses decrement the counting element now."""
        if not self.loaded or self.stopped:
            return False
        if self.mode in (1, 5):
            return True
        return bool(self.gate)

    def _to_zero(self):
        return self.ce if self.ce else self.modulus

    def _half_lengths(self, count):
        count = count if count else self.modulus
        return (count + 1) // 2, count // 2  # high, low

    def pulses_to_event(self):
        """CLK pulses until (and including) the next pulse that does more than decrement."""
        mode = self.mode
        if mode is None:
            return INF
        if self.pending_load and (mode in (0, 4) or self.gate):
            return 1
        if self.triggered:
            return 1
        if self.strobe:
            return 1
        if not self._counting():
            return INF
        if mode == 0:
            return self._to_zero() if self.out == 0 else INF
        if mode in (1, 4, 5):
            return self._to_zero() if self.armed else INF
        if mode == 2:
            return 1 if self.ce == 1 else (self._to_zero() - 1 if self.ce != 0 else self.modulus - 1)
        if mode == 3:
            return self.half
        return INF

    def _plain(self, pulses):
        if pulses <= 0 or not self._counting():
            return
        if self.mode == 3:
            self.half -= pulses
            self.fresh = False
        else:
            self.ce = (self.ce - pulses) % self.modulus

    def _event_pulse(self):
        """One CLK pulse with all its side effects. Returns (rising, falling) edge counts."""
        before = self.out
        mode = self.mode
        if self.triggered:  # modes 1 and 5: load on the pulse after the trigger
            self.triggered = False
            self.ce = self.cr % self.modulus
            self.loaded = True
            self.armed = True
            if mode == 1:
                self.out = 0
        elif self.pending_load and (mode in (0, 4) or self.gate):
            self.pending_load = False
            self.loaded = True
            self.armed = True
            self.active = self.cr
            if mode == 3:
                self.out = 1
                self.half = self._half_lengths(self.cr)[0]
                self.fresh = True
            else:
                self.ce = self.cr % self.modulus
                if mode == 2:
                    self.out = 1
        elif self.strobe:  # modes 4/5: the one-clock low strobe ends
            self.strobe = False
            self.out = 1
            self._plain(1)
        elif self._counting():
            if mode == 2:
                if self.ce == 1:
                    self.ce = self.cr % self.modulus  # reload, OUT back high
                    self.active = self.cr
                    self.out = 1
                else:
                    self.ce = (self.ce - 1) % self.modulus
                    if self.ce == 1:
                        self.out = 0
            elif mode == 3:
                self.half -= 1
                self.fresh = False
                if self.half <= 0:
                    self.out ^= 1
                    high, low = self._half_lengths(self.cr)
                    if self.out:
                        self.active = self.cr  # a period starts with its high half
                    elif self.active != self.cr:
                        self.active = None  # the count changed in the middle of a period
                    self.half = high if self.out else low
                    self.fresh = True  # reloaded with the full count
                    if self.half == 0:  # count of 1: no low half
                        self.out = 1
                        self.half = high
            else:
                self.ce = (self.ce - 1) % self.modulus
                if self.ce == 0:
                    if mode == 0:
                        self.out = 1
                    elif mode == 1 and self.armed:
                        self.out = 1
                        self.armed = False
                    elif mode in (4, 5) and self.armed:
                        self.out = 0
                        self.strobe = True
                        self.armed = False
        rising = 1 if (self.out and not before) else 0
        falling = 1 if (before and not self.out) else 0
        return rising, falling

    def period(self):
        """
        CLK pulses of one full output period in modes 2 and 3 while the count
        is stable (the state then repeats exactly every period), else None.
        """
        if (self.mode in (2, 3) and self.loaded and not self.pending_load
                and self.cr is not None and self.active == self.cr):
            period = self.cr if self.cr else self.modulus
            return period if period >= 2 else None
        return None

    def clock(self, pulses, stop_on_change=False):
        """
        Applies CLK pulses. Returns (pulses used, rising edges, falling edges)
        of OUT. With stop_on_change, stops right after the first OUT change.
        """
        used = rising = falling = 0
        while used < pulses:
            remaining = pulses - used
            step = self.pulses_to_event()
            if step > remaining:
                self._plain(remaining)
                used = pulses
                break
            # Whole periods of a periodic output can be skipped arithmetically
            period = self.period()
            if (not stop_on_change and period and self._counting() and self.gate
                    and remaining > step + 2 * period):
                cycles = (remaining - step) // period - 1
                if cycles > 0:  # the counter state repeats after each period
                    used += cycles * period
                    rising += cycles
                    falling += cycles
                    continue
            self._plain(step - 1)
            r, f = self._event_pulse()
            used += step
            rising += r
            falling += f
            if stop_on_change and (r or f):
                break
        return used, rising, falling


# ======================================================================


class PIT8253:
    """Intel 8253: counters 0-2 at offsets 0-2, control register at offset 3."""

    NAME = "8253"
    CLOCK_SOURCES = ("CLK OUT", "CLK OUT / 2", "OUT of previous counter", "Manual")

    def __init__(self):
        self.counters = [Counter8253(i) for i in range(3)]
        self.sources = ["CLK OUT", "CLK OUT", "CLK OUT"]
        self._phase = [0, 0, 0]  # T-states left over from the CLK OUT / 2 divider

    def power_on(self):
        for counter in self.counters:
            counter.power_on()
        self._phase = [0, 0, 0]

    def read(self, offset):
        if offset == 3:
            return 0xFF  # the control register cannot be read on the 8253
        return self.counters[offset].read()

    def write(self, offset, value):
        if offset == 3:
            select = (value >> 6) & 3
            if select == 3:
                return  # illegal on the 8253 (read-back exists only on the 8254)
            self.counters[select].control_word(value)
        else:
            self.counters[offset].write(value)

    def outputs(self):
        return {f"OUT{i}": c.out for i, c in enumerate(self.counters)}


# ======================================================================


class PeripheralBus:
    """
    Connects the 8255 and 8253 to the CPU's I/O ports, clock and interrupt
    pins. `wiring` maps chip outputs ("OUT0", "OUT1", "OUT2", "INTR-A",
    "INTR-B") to 8085 interrupt pins ("TRAP", "RST7.5", "RST6.5", "RST5.5").
    """

    def __init__(self, ppi_base=0x40, pit_base=0x50):
        self.ppi = PPI8255()
        self.pit = PIT8253()
        self._ppi_enabled = True
        self._pit_enabled = True
        self._ppi_base = ppi_base & 0xFF
        self._pit_base = pit_base & 0xFF
        self._port_map = None
        self.wiring = {}
        self._applied = {}  # output -> interrupt pin it currently drives
        self.cpu = None
        self.time = 0  # T-state up to which the 8253 has been clocked
        self.external_time = None  # T-state of a change made from outside (panel), if known
        self.edges = {}  # output -> number of rising edges seen (for displays)

    # ------------------------------------------------------------------
    def attach(self, cpu):
        """Connects the bus to a (new) processor; the chips keep their state."""
        self.cpu = cpu
        cpu.io_bus = self
        self._applied = {}
        self.time = cpu.t_states
        self._drive_pins()
        self._update_deadline()

    def rebase(self):
        """The CPU's T-state counter was reset: continue from the new count."""
        if self.cpu is not None:
            self.time = self.cpu.t_states
            self._update_deadline()

    def cpu_reset(self):
        """The CPU was reset: RESET OUT resets the 8255; the 8253 has no RESET input."""
        self.ppi.reset()
        self.rebase()
        self._drive_pins()

    def power_on(self):
        """
        Power-on of the board: both chips start from their initial state. The
        levels external devices drive on the 8255 pins are not part of the chip
        and stay as they are.
        """
        self.ppi.reset()
        self.pit.power_on()
        self.edges = {}
        self.rebase()
        self._drive_pins()

    # Configuration (changing it rebuilds the port map)
    def _configure(self, name, value):
        setattr(self, name, value)
        self._port_map = None
        self._drive_pins()
        self._update_deadline()

    ppi_enabled = property(lambda self: self._ppi_enabled, lambda self, v: self._configure("_ppi_enabled", bool(v)))
    pit_enabled = property(lambda self: self._pit_enabled, lambda self, v: self._configure("_pit_enabled", bool(v)))
    ppi_base = property(lambda self: self._ppi_base, lambda self, v: self._configure("_ppi_base", v & 0xFF))
    pit_base = property(lambda self: self._pit_base, lambda self, v: self._configure("_pit_base", v & 0xFF))

    def ports(self):
        """Port number -> (chip, register offset) for the enabled chips (the 8255 wins an overlap)."""
        if self._port_map is None:
            ports = {}
            if self._ppi_enabled:
                for offset in range(4):
                    ports[(self._ppi_base + offset) & 0xFF] = (self.ppi, offset)
            if self._pit_enabled:
                for offset in range(4):
                    ports.setdefault((self._pit_base + offset) & 0xFF, (self.pit, offset))
            self._port_map = ports
        return self._port_map

    def claims(self, port):
        return port in self.ports()

    def read(self, port, t_states):
        device, offset = self.ports()[port]
        self.sync(t_states)
        value = device.read(offset)
        self._after_access()
        return value

    def write(self, port, value, t_states):
        device, offset = self.ports()[port]
        self.sync(t_states)
        device.write(offset, value)
        self._after_access()

    def _after_access(self):
        self._drive_pins()
        self._update_deadline()

    # ------------------------------------------------------------------
    # Clocking
    # ------------------------------------------------------------------
    def _pulses_for(self, index, cycles):
        source = self.pit.sources[index]
        if source == "CLK OUT":
            return cycles
        if source == "CLK OUT / 2":
            total = self.pit._phase[index] + cycles
            self.pit._phase[index] = total % 2
            return total // 2
        return 0

    def sync(self, t_states):
        """Clocks the 8253 up to the given T-state and updates the interrupt pins."""
        cycles = t_states - self.time
        if cycles <= 0:
            return
        self.time = t_states
        if self._pit_enabled:
            self._clock_pit(cycles)
        if self.wiring or self._applied:
            self._drive_pins()
            self._update_deadline()

    def _clock_pit(self, cycles):
        cascade = 0
        for index, counter in enumerate(self.pit.counters):
            if counter.mode is None:  # unprogrammed: nothing to count
                cascade = 0
                if self.pit.sources[index] == "CLK OUT / 2":
                    self.pit._phase[index] = (self.pit._phase[index] + cycles) % 2
                continue
            if self.pit.sources[index] == "OUT of previous counter":
                pulses = cascade  # falling edges of the previous counter's OUT
            else:
                pulses = self._pulses_for(index, cycles)
            _, rising, falling = counter.clock(pulses)
            name = f"OUT{index}"
            pin = self.wiring.get(name)
            if rising and pin in ("RST7.5", "TRAP"):
                self._edge_to_pin(pin, name)
            if rising:
                self.edges[name] = self.edges.get(name, 0) + rising
            cascade = falling

    def _now(self):
        """T-state of the change being applied (a panel action's time, or the chips' time)."""
        return self.external_time if self.external_time is not None else self.time

    def _edge_to_pin(self, pin, source):
        """A rising edge reached an edge-triggered input (RST 7.5 / TRAP)."""
        if self.cpu is not None:
            at = self._now()
            self.cpu.set_pin(pin, 0, source=source, at=at)
            self.cpu.set_pin(pin, 1, source=source, at=at)

    def manual_clock(self, index, pulses=1):
        """A CLK pulse from the Manual source (the counters after it may be cascaded)."""
        self.sync(self.cpu.t_states if self.cpu else self.time)
        counter = self.pit.counters[index]
        _, rising, falling = counter.clock(pulses)
        name = f"OUT{index}"
        pin = self.wiring.get(name)
        if rising and pin in ("RST7.5", "TRAP"):
            self._edge_to_pin(pin, name)
        cascade = falling
        for nxt in range(index + 1, 3):
            if self.pit.sources[nxt] != "OUT of previous counter" or not cascade:
                break
            c = self.pit.counters[nxt]
            _, r, cascade = c.clock(cascade)
            pin = self.wiring.get(f"OUT{nxt}")
            if r and pin in ("RST7.5", "TRAP"):
                self._edge_to_pin(pin, f"OUT{nxt}")
        self._after_access()

    def set_gate(self, index, level):
        self.sync(self.cpu.t_states if self.cpu else self.time)
        self.pit.counters[index].set_gate(level)
        self._after_access()

    # ------------------------------------------------------------------
    # Interrupt wiring
    # ------------------------------------------------------------------
    def levels(self):
        levels = {}
        if self.pit_enabled:
            levels.update(self.pit.outputs())
        if self.ppi_enabled:
            levels.update(self.ppi.interrupt_outputs())
        return levels

    def _source_level(self, source):
        if source.startswith("OUT"):
            return self.pit.counters[int(source[3])].out if self._pit_enabled else 0
        if not self._ppi_enabled:
            return 0
        return self.ppi.intr_a() if source == "INTR-A" else self.ppi.intr_b()

    def _drive_pins(self):
        """Puts the levels of the wired chip outputs on the CPU's interrupt pins."""
        cpu = self.cpu
        if cpu is None:
            return
        applied = self._applied
        for source in ("OUT0", "OUT1", "OUT2", "INTR-A", "INTR-B"):
            pin = self.wiring.get(source)
            old = applied.get(source)
            if old is not None and old != pin:
                cpu.set_pin(old, 0, source=source, at=self._now())  # disconnected or rewired
                del applied[source]
            if pin is None:
                continue
            level = self._source_level(source)
            if old != pin or cpu.pin_source_level(pin, source) != level:
                cpu.set_pin(pin, level, source=source, at=self._now())
            applied[source] = pin

    def set_wiring(self, source, pin):
        if pin:
            self.wiring[source] = pin
        else:
            self.wiring.pop(source, None)
        self._drive_pins()
        self._update_deadline()

    def _can_act_on(self, pin):
        """
        Whether a change on this interrupt pin can change what the CPU does
        next. Edges that cannot (interrupts disabled, the pin masked, R7.5
        already latched) are still applied, in bulk, before the CPU next looks
        at the interrupt state (EI, SIM, RIM) or touches a chip.
        """
        cpu = self.cpu
        if pin == "TRAP":
            return True
        if pin is None or not cpu.interrupt_enable:
            return False
        masks = cpu.interrupt_masks
        if pin == "RST7.5":
            return not masks & 0b100 and not cpu.rst75_ff
        if pin == "RST6.5":
            return not masks & 0b010
        if pin == "RST5.5":
            return not masks & 0b001
        return False

    def cpu_state_changed(self):
        """The CPU changed INTE, the masks or R7.5 (EI, DI, SIM, an acknowledge)."""
        if self.wiring:
            self._update_deadline()

    def _update_deadline(self):
        """
        Tells the CPU the T-state at which a wired 8253 output next changes in
        a way the CPU can act on (see _can_act_on).
        """
        if self.cpu is None:
            return
        deadline = INF
        if self._pit_enabled and self.wiring:
            for index, counter in enumerate(self.pit.counters):
                if counter.mode is None or not self._wakes_cpu(index):
                    continue
                source = self.pit.sources[index]
                if source == "CLK OUT":
                    cycles = counter.pulses_to_event()
                elif source == "CLK OUT / 2":
                    pulses = counter.pulses_to_event()
                    cycles = pulses * 2 - self.pit._phase[index] if pulses != INF else INF
                elif source == "OUT of previous counter" and index > 0:
                    # conservative: wake up at every event of the counter feeding it
                    prev = self.pit.counters[index - 1]
                    prev_source = self.pit.sources[index - 1]
                    cycles = prev.pulses_to_event()
                    if prev_source == "CLK OUT / 2" and cycles != INF:
                        cycles = cycles * 2 - self.pit._phase[index - 1]
                    elif prev_source not in ("CLK OUT", "CLK OUT / 2"):
                        cycles = INF
                else:
                    cycles = INF
                if cycles != INF:
                    deadline = min(deadline, self.time + max(1, cycles))
        self.cpu._io_deadline = deadline

    def _wakes_cpu(self, index):
        """Whether counter `index` (or a counter it clocks) drives a pin the CPU can act on now."""
        if self._can_act_on(self.wiring.get(f"OUT{index}")):
            return True
        for nxt in range(index + 1, 3):
            if self.pit.sources[nxt] != "OUT of previous counter":
                return False
            if self._can_act_on(self.wiring.get(f"OUT{nxt}")):
                return True
        return False
