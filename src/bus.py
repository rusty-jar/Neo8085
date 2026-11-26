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
8085 machine cycles and bus timing.

Every 8085 instruction is a fixed sequence of machine cycles (Intel 8085AH
data sheet, Table 3 "Machine Cycle Chart" and Table 4 "T-State Chart"):

    Machine cycle             IO/M S1 S0   Control     T-states
    Opcode Fetch (OF)           0   1  1   RD = 0      4 or 6
    Memory Read (MR)            0   1  0   RD = 0      3
    Memory Write (MW)           0   0  1   WR = 0      3
    I/O Read (IOR)              1   1  0   RD = 0      3
    I/O Write (IOW)             1   0  1   WR = 0      3
    Interrupt Ack (INA)         1   1  1   INTA = 0    6 (first) / 3
    Bus Idle: DAD (BI)          0   1  0   none        3   (no ALE)
    Bus Idle: ACK of RST/TRAP   1   1  1   none        6
    Halt                        Z   0  0   RD, WR = Z

T-state behaviour of the buses (Table 4):
    T1      ALE high, A15-A8 = high-order address, AD7-AD0 = low-order address
            (for I/O cycles the port address appears on both halves)
    T2, T3  RD / WR / INTA active; AD7-AD0 carries the data byte
    T4-T6   internal operation: A15-A8 unspecified, AD7-AD0 high impedance
    THALT   address, data, IO/M, RD and WR high impedance, S1 S0 = 00
IO/M, S1 and S0 are valid from the start of T1 for the whole machine cycle.
HLT is an opcode fetch followed by a HALT machine cycle: its T1 (the 5th
T-state of HLT) has the ALE pulse of every T1, with the address unspecified,
then the CPU stays in THALT states (MCS-80/85 User's Manual, Figure 2-20).

This module works at machine-cycle level: plan_instruction() and
plan_interrupt() produce the cycles of one instruction or interrupt
acknowledge, and waveform() expands cycles into per-T-state signal levels for
a timing diagram. The machine cycles of each instruction always add up to
the instruction's T-states (verified by the test suite for every opcode).
"""

# kind: (name, short name, IO/M, S1, S0, active strobe, ALE generated)
# IO/M None = high impedance
CYCLE_TYPES = {
    "OF": ("Opcode Fetch", "OF", 0, 1, 1, "RD", True),
    "MR": ("Memory Read", "MR", 0, 1, 0, "RD", True),
    "MW": ("Memory Write", "MW", 0, 0, 1, "WR", True),
    "IOR": ("I/O Read", "IOR", 1, 1, 0, "RD", True),
    "IOW": ("I/O Write", "IOW", 1, 0, 1, "WR", True),
    "INA": ("Interrupt Acknowledge", "INA", 1, 1, 1, "INTA", True),
    "BI": ("Bus Idle", "BI", 0, 1, 0, None, False),
    "BIA": ("Bus Idle (Interrupt Ack)", "BI", 1, 1, 1, None, True),
    "HALT": ("Halt", "HALT", None, 0, 0, None, True),
}

# Signals shown in a timing diagram (top to bottom)
SIGNALS = ("CLK", "A15-A8", "AD7-AD0", "ALE", "IO/M", "S1", "S0", "RD", "WR", "INTA")
BUS_SIGNALS = ("A15-A8", "AD7-AD0")

# Opcodes whose opcode fetch takes 6 T-states (the "S" fetch of the Intel
# manuals): INX, DCX, PCHL, SPHL, PUSH, CALL, Ccc, Rcc, RST n and RSTV
SIX_T_FETCH = frozenset(
    [0x03 | (rp << 4) for rp in range(4)]
    + [0x0B | (rp << 4) for rp in range(4)]
    + [0xC5 | (rp << 4) for rp in range(4)]
    + [0xC0 | (cc << 3) for cc in range(8)]
    + [0xC4 | (cc << 3) for cc in range(8)]
    + [0xC7 | (n << 3) for n in range(8)]
    + [0xE9, 0xF9, 0xCD, 0xCB]
)

_PAIR_NAMES = ("BC", "DE", "HL", "SP")
_PUSH_NAMES = (("B", "C"), ("D", "E"), ("H", "L"), ("A", "flags"))
_REGS = ("B", "C", "D", "E", "H", "L", "M", "A")


class MachineCycle:
    """
    One machine cycle: its type, length, the address it puts on the bus and
    the byte transferred (None when no data is transferred or not yet known).
    """

    __slots__ = ("kind", "t_states", "address", "data", "note")

    def __init__(self, kind, t_states, address=None, data=None, note=""):
        self.kind = kind
        self.t_states = t_states
        self.address = address
        self.data = data
        self.note = note

    @property
    def name(self):
        return CYCLE_TYPES[self.kind][0]

    @property
    def short_name(self):
        return CYCLE_TYPES[self.kind][1]

    @property
    def status(self):
        """(IO/M, S1, S0); IO/M is None (high impedance) in the Halt state."""
        info = CYCLE_TYPES[self.kind]
        return info[2], info[3], info[4]

    @property
    def strobe(self):
        """Control line pulsed low: "RD", "WR", "INTA" or None."""
        return CYCLE_TYPES[self.kind][5]

    @property
    def ale(self):
        return CYCLE_TYPES[self.kind][6]

    def __repr__(self):
        address = "----" if self.address is None else f"{self.address:04X}"
        data = "--" if self.data is None else f"{self.data:02X}"
        return f"<{self.short_name} {self.t_states}T {address} {data} {self.note}>"


# ----------------------------------------------------------------------
# Planning the machine cycles of an instruction
# ----------------------------------------------------------------------


def plan_instruction(cpu, op, pc, taken):
    """
    Machine cycles of the instruction at pc, using the CPU state *before* the
    instruction executes. Read cycles carry the byte read; write cycles carry
    their address, and finish_cycles() fills in the byte written once the
    instruction has executed. `taken` selects the path of a conditional
    instruction.
    """
    mem = cpu.memory
    regs = cpu.registers
    pc1 = (pc + 1) & 0xFFFF
    pc2 = (pc + 2) & 0xFFFF
    hl = (regs["H"] << 8) | regs["L"]
    sp = regs["SP"]

    def read(address, note):
        address &= 0xFFFF
        return MachineCycle("MR", 3, address, mem[address], note)

    def write(address, note):
        return MachineCycle("MW", 3, address & 0xFFFF, None, note)

    fetch = MachineCycle("OF", 6 if op in SIX_T_FETCH else 4, pc, op, "opcode")
    cycles = [fetch]
    add = cycles.append

    # MOV / HLT
    if 0x40 <= op <= 0x7F:
        if op == 0x76:
            add(MachineCycle("HALT", 1, None, None, "T1 of the HALT machine cycle, then THALT states"))
        elif (op >> 3) & 7 == 6:
            add(write(hl, f"{_REGS[op & 7]} to memory (HL)"))
        elif op & 7 == 6:
            add(read(hl, f"memory (HL) to {_REGS[(op >> 3) & 7]}"))
        return cycles

    # ALU with register / memory operand
    if 0x80 <= op <= 0xBF:
        if op & 7 == 6:
            add(read(hl, "operand from memory (HL)"))
        return cycles

    low3 = op & 7
    if op < 0x40:
        reg = (op >> 3) & 7
        rp = (op >> 4) & 3
        if low3 == 6:  # MVI
            add(read(pc1, "immediate data"))
            if reg == 6:
                add(write(hl, "data to memory (HL)"))
        elif low3 in (4, 5):  # INR / DCR
            if reg == 6:
                add(read(hl, "operand from memory (HL)"))
                add(write(hl, "result to memory (HL)"))
        elif low3 == 1:
            if op & 0x08:  # DAD: two bus idle cycles while the ALU adds
                add(MachineCycle("BI", 3, None, None, "add low bytes (L + low byte)"))
                add(MachineCycle("BI", 3, None, None, "add high bytes (H + high byte)"))
            else:  # LXI
                add(read(pc1, f"low byte of data (to {_PAIR_NAMES[rp][1] if rp < 3 else 'SPL'})"))
                add(read(pc2, f"high byte of data (to {_PAIR_NAMES[rp][0] if rp < 3 else 'SPH'})"))
        elif low3 == 2:
            if op in (0x02, 0x12):  # STAX
                pointer = (regs["B"] << 8) | regs["C"] if op == 0x02 else (regs["D"] << 8) | regs["E"]
                add(write(pointer, f"A to memory ({'BC' if op == 0x02 else 'DE'})"))
            elif op in (0x0A, 0x1A):  # LDAX
                pointer = (regs["B"] << 8) | regs["C"] if op == 0x0A else (regs["D"] << 8) | regs["E"]
                add(read(pointer, f"memory ({'BC' if op == 0x0A else 'DE'}) to A"))
            else:
                address = (mem[pc2] << 8) | mem[pc1]
                add(read(pc1, "low-order address byte"))
                add(read(pc2, "high-order address byte"))
                if op == 0x22:  # SHLD
                    add(write(address, "L to memory"))
                    add(write(address + 1, "H to memory"))
                elif op == 0x2A:  # LHLD
                    add(read(address, "memory to L"))
                    add(read(address + 1, "memory to H"))
                elif op == 0x32:  # STA
                    add(write(address, "A to memory"))
                else:  # LDA
                    add(read(address, "memory to A"))
        elif low3 == 0:
            # The undocumented instructions turn their R1/R2 cycles into bus
            # idle cycles with the same CYC_IDL signal as DAD (same status,
            # no ALE, READY ignored): Pavel Zima's die analysis of the
            # instruction timing ROM, pastraiser.com/reverse/AMD9085
            if op == 0x08:  # DSUB
                add(MachineCycle("BI", 3, None, None, "subtract low bytes (L - C)"))
                add(MachineCycle("BI", 3, None, None, "subtract high bytes (H - B)"))
            elif op == 0x10:  # ARHL
                add(MachineCycle("BI", 3, None, None, "shift HL right"))
            elif op == 0x18:  # RDEL
                add(MachineCycle("BI", 3, None, None, "rotate E left"))
                add(MachineCycle("BI", 3, None, None, "rotate D left"))
            elif op in (0x28, 0x38):  # LDHI / LDSI
                add(read(pc1, "immediate offset"))
                add(MachineCycle("BI", 3, None, None, f"DE = {'HL' if op == 0x28 else 'SP'} + offset"))
        # INX/DCX (6-T fetch), rotates, DAA, CMA, STC, CMC, NOP, RIM, SIM: fetch only
        return cycles

    # 0xC0 - 0xFF
    cc_low = low3
    rp = (op >> 4) & 3
    if cc_low == 0:  # Rcc
        if taken:
            add(read(sp, "return address low byte (PCL) from stack"))
            add(read(sp + 1, "return address high byte (PCH) from stack"))
    elif cc_low == 2 or op in (0xC3, 0xDD, 0xFD):  # Jcc, JMP, JNK, JK
        add(read(pc1, "low-order address byte"))
        if taken:  # a jump not taken skips the high-order byte
            add(read(pc2, "high-order address byte"))
    elif cc_low == 4 or op == 0xCD:  # Ccc, CALL
        add(read(pc1, "low-order address byte"))
        if taken:
            add(read(pc2, "high-order address byte"))
            add(write(sp - 1, "return address high byte (PCH) to stack"))
            add(write(sp - 2, "return address low byte (PCL) to stack"))
    elif cc_low == 6:  # ALU immediate
        add(read(pc1, "immediate data"))
    elif cc_low == 7 or (op == 0xCB and taken):  # RST n, RSTV taken
        add(write(sp - 1, "return address high byte (PCH) to stack"))
        add(write(sp - 2, "return address low byte (PCL) to stack"))
    elif op == 0xC9:  # RET
        add(read(sp, "return address low byte (PCL) from stack"))
        add(read(sp + 1, "return address high byte (PCH) from stack"))
    elif op == 0xD9:  # SHLX
        de = (regs["D"] << 8) | regs["E"]
        add(write(de, "L to memory (DE)"))
        add(write(de + 1, "H to memory (DE + 1)"))
    elif op == 0xED:  # LHLX
        de = (regs["D"] << 8) | regs["E"]
        add(read(de, "memory (DE) to L"))
        add(read(de + 1, "memory (DE + 1) to H"))
    elif cc_low == 1 and not op & 0x08:  # POP
        high, low = _PUSH_NAMES[rp]
        add(read(sp, f"{low} from stack"))
        add(read(sp + 1, f"{high} from stack"))
    elif cc_low == 5 and not op & 0x08:  # PUSH
        high, low = _PUSH_NAMES[rp]
        add(write(sp - 1, f"{high} to stack"))
        add(write(sp - 2, f"{low} to stack"))
    elif op in (0xD3, 0xDB):  # OUT / IN
        port = mem[pc1]
        add(read(pc1, "port address"))
        if op == 0xD3:
            add(MachineCycle("IOW", 3, (port << 8) | port, None, f"A to output port {port:02X}H"))
        else:
            add(MachineCycle("IOR", 3, (port << 8) | port, None, f"input port {port:02X}H to A"))
    elif op == 0xE3:  # XTHL
        add(read(sp, "stack top (SP) - goes to L"))
        add(read(sp + 1, "stack top (SP + 1) - goes to H"))
        add(write(sp + 1, "H to stack (SP + 1)"))
        add(write(sp, "L to stack (SP)"))
    # PCHL, SPHL (6-T fetch), XCHG, DI, EI, RSTV not taken: fetch only
    return cycles


def plan_interrupt(cpu, name):
    """
    Machine cycles of an interrupt acknowledge, from the CPU state before it.
    TRAP and RST 7.5/6.5/5.5 insert a RESTART internally: a 6-T bus idle
    acknowledge cycle (IO/M S1 S0 = 111, no RD and no INTA) followed by two
    stack writes. INTR is acknowledged with INTA cycles in which the device
    supplies an instruction (usually RST n or CALL a16); the PC is not
    incremented during them.
    """
    pc = cpu.registers["PC"]
    sp = cpu.registers["SP"]
    if name == "INTR":
        # The supplied instruction's cycles, with its opcode and operand bytes
        # read in INTA cycles (the address lines carry the PC, not incremented)
        data = cpu.intr_instruction
        memory = cpu.memory
        saved = [memory[(pc + i) & 0xFFFF] for i in range(len(data))]
        for i, byte in enumerate(data):
            memory[(pc + i) & 0xFFFF] = byte
        try:
            cycles = plan_instruction(cpu, data[0], pc, cpu.branch_taken(data[0]))
        finally:
            for i, byte in enumerate(saved):
                memory[(pc + i) & 0xFFFF] = byte
        notes = ("device supplies the opcode", "device supplies byte 2", "device supplies byte 3")
        for i, byte in enumerate(data):
            cycles[i] = MachineCycle("INA", cycles[i].t_states, pc, byte, notes[i])
        return cycles
    return [
        MachineCycle("BIA", 6, pc, None, f"{name} acknowledged: internal RESTART"),
        MachineCycle("MW", 3, (sp - 1) & 0xFFFF, None, "return address high byte (PCH) to stack"),
        MachineCycle("MW", 3, (sp - 2) & 0xFFFF, None, "return address low byte (PCL) to stack"),
    ]


def finish_cycles(cpu, cycles):
    """Fills in the bytes written by write cycles after the instruction has executed."""
    for cycle in cycles:
        if cycle.kind == "MW":
            cycle.data = cpu.memory[cycle.address]
        elif cycle.kind == "IOW":
            cycle.data = cpu.output_ports[cycle.address & 0xFF]
        elif cycle.kind == "IOR" and cpu.last_io is not None:
            cycle.data = cpu.last_io[2]  # the byte the device put on the bus
    return cycles


# ----------------------------------------------------------------------
# Timing diagram waveforms
# ----------------------------------------------------------------------

# Signal values per half T-state:
#   0 / 1   logic level          "Z"  high impedance          "X"  unspecified
#   ("A", value) address on a bus  ("D", value) data on a bus  ("D", None) data, value unknown


def _t_state(cycle, number):
    """Signal levels for T-state `number` (1-based) of a machine cycle, as {signal: (first half, second half)}."""
    io_m, s1, s0 = cycle.status
    strobe = cycle.strobe
    if cycle.kind == "HALT":  # T1 of the HALT machine cycle (ALE, address unspecified)
        return {
            "A15-A8": ("X", "X"),
            "AD7-AD0": ("X", "X"),
            "ALE": (1, 0),
            "IO/M": ("Z", "Z"),
            "S1": (s1, s1),
            "S0": (s0, s0),
            "RD": ("Z", "Z"),
            "WR": ("Z", "Z"),
            "INTA": (1, 1),
        }

    signals = {
        "IO/M": (io_m, io_m),
        "S1": (s1, s1),
        "S0": (s0, s0),
        "ALE": (0, 0),
        "RD": (1, 1),
        "WR": (1, 1),
        "INTA": (1, 1),
    }
    address = cycle.address
    high = "X" if address is None else ("A", address >> 8)
    low = "X" if address is None else ("A", address & 0xFF)
    data = ("D", cycle.data)

    if number == 1:
        if cycle.ale:
            signals["ALE"] = (1, 0)
        signals["A15-A8"] = (high, high)
        signals["AD7-AD0"] = (low, low)
    elif number in (2, 3):
        signals["A15-A8"] = (high, high)
        if strobe is not None:
            signals[strobe] = (0, 0)
        if strobe == "WR":  # the CPU drives the data from the start of T2
            signals["AD7-AD0"] = (data, data)
        elif strobe is not None:  # read: the bus floats, then the device drives the data
            signals["AD7-AD0"] = ("Z", data) if number == 2 else (data, data)
        else:  # bus idle: no data transfer
            signals["AD7-AD0"] = ("X", "X")
    else:  # T4 - T6: internal operation
        signals["A15-A8"] = ("X", "X")
        signals["AD7-AD0"] = ("Z", "Z")
    return signals


def waveform(cycles):
    """
    Expands machine cycles into T-states for a timing diagram. Returns a list
    of (machine cycle index, T-state label, {signal: (first half, second half)}).
    The HALT machine cycle is the T1 that leads into the THALT states.
    """
    states = []
    for index, cycle in enumerate(cycles):
        for number in range(1, cycle.t_states + 1):
            label = f"T{number}"
            states.append((index, label, _t_state(cycle, number)))
    return states


def describe_cycle(cycle):
    """One-line description used by the GUI and the execution log."""
    parts = [f"{cycle.short_name:<4} {cycle.t_states}T"]
    if cycle.address is not None:
        parts.append(f"addr {cycle.address:04X}H")
    if cycle.data is not None:
        parts.append(f"data {cycle.data:02X}H")
    if cycle.note:
        parts.append(cycle.note)
    return "  ".join(parts)
