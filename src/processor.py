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
Intel 8085 CPU core.

Execution
    The processor executes machine code directly from its 64KB memory using a
    fetch-decode-execute cycle: the opcode byte at PC is fetched, PC is
    advanced past the instruction, and the instruction is then executed. All 256 opcodes are implemented: the 246 documented ones
    and the 10 undocumented 8085 instructions (DSUB, ARHL, RDEL, LDHI, LDSI,
    RSTV, SHLX, JNK, LHLX, JK).

Flag register (PSW low byte):  S Z K AC 0 P V CY  (bit 7 .. bit 0)
  * Subtraction (SUB/SBB/SUI/SBI/CMP/CPI) is performed as A + ~operand + !borrow.
    CY is the complement of the carry out of bit 7 (it signals a borrow), AC
    is the carry out of bit 3 of that same addition (not complemented).
  * ANA/ANI set AC=1 and clear CY (8085 behaviour). ORA/XRA clear AC and CY.
  * INR/DCR affect S, Z, AC, P (and V, K) but never CY. DAD affects CY (and V).
  * V (bit 1, undocumented): two's complement overflow = carry into bit 7 XOR
    carry out of bit 7 of the ALU addition. Cleared by logic ops, RRC, RAR.
  * K (bit 5, undocumented, also called X5/UI): V XOR S after 8-bit
    arithmetic/logic; carry/borrow out of the 16-bit incrementer for INX/DCX.
  * Bit 3 always reads as 0.

Interrupts (Intel 8085A interrupt structure)
    TRAP     non-maskable, rising edge + high level, vector 0024H, highest priority
    RST 7.5  rising edge latched in the R7.5 flip-flop, mask M7.5, vector 003CH
    RST 6.5  high level, mask M6.5, vector 0034H
    RST 5.5  high level, mask M5.5, vector 002CH
    INTR     high level, lowest priority; during INTA the device supplies an
             instruction, usually RST n or CALL a16
    VALID INT = TRAP + INTE.(INTR + R7.5.!M7.5 + RST6.5.!M6.5 + RST5.5.!M5.5)
    Interrupts are sampled during the next-to-last clock cycle of every
    instruction (and on every clock during HALT): a request that appears in
    an instruction's last clock cycle is recognised one instruction later. In
    HALT the CPU leaves THALT at the end of the clock period after the one in
    which it samples the request (MCS-80/85 User's Manual, Figure 2-20).
    Accepting any interrupt (including TRAP) resets INTE. EI takes effect
    after the instruction following it. RESET clears INTE, the R7.5 and TRAP
    flip-flops and SOD, and sets all three masks.

Input / Output
    IN reads the 256 input-port latches (driven by external devices), OUT
    writes the 256 output-port latches. SID/SOD are the serial pins used by
    RIM/SIM. With an io_bus attached (see peripherals.py), the ports of the
    8255 and 8253 are routed to those chips at the T-state of the I/O read or
    write machine cycle, and chip outputs can drive the interrupt pins.

Instruction timing is tracked in T-states using the 8085 cycle counts. With
trace_bus enabled, every step() also records its machine cycles (opcode
fetch, memory/I/O read and write, interrupt acknowledge, bus idle) in
bus_cycles - see bus.py.
"""

from bus import finish_cycles, plan_instruction, plan_interrupt

_NEVER = float("inf")

REG_NAMES = ("B", "C", "D", "E", "H", "L", "M", "A")
RP_NAMES = ("B", "D", "H", "SP")
ALU_NAMES = ("ADD", "ADC", "SUB", "SBB", "ANA", "XRA", "ORA", "CMP")
ALU_IMM_NAMES = ("ADI", "ACI", "SUI", "SBI", "ANI", "XRI", "ORI", "CPI")
COND_NAMES = ("NZ", "Z", "NC", "C", "PO", "PE", "P", "M")

# Opcodes that exist on the 8085 but are undocumented by Intel (all implemented).
UNDOCUMENTED_OPCODES = {
    0x08: "DSUB",
    0x10: "ARHL",
    0x18: "RDEL",
    0x28: "LDHI",
    0x38: "LDSI",
    0xCB: "RSTV",
    0xD9: "SHLX",
    0xDD: "JNK",
    0xED: "LHLX",
    0xFD: "JK",
}

INTERRUPT_PINS = ("TRAP", "RST7.5", "RST6.5", "RST5.5", "INTR")
INTERRUPT_VECTORS = {"TRAP": 0x0024, "RST7.5": 0x003C, "RST6.5": 0x0034, "RST5.5": 0x002C}

# Even parity lookup (1 = even number of 1 bits)
_PARITY = tuple(1 if bin(i).count("1") % 2 == 0 else 0 for i in range(256))


def _build_size_table():
    """Instruction length in bytes for every opcode."""
    sizes = [1] * 256
    for r in range(8):
        sizes[0x06 | (r << 3)] = 2  # MVI r,d8
    for rp in range(4):
        sizes[0x01 | (rp << 4)] = 3  # LXI rp,d16
    for op in (0x22, 0x2A, 0x32, 0x3A, 0xC3, 0xCD, 0xDD, 0xFD):  # SHLD LHLD STA LDA JMP CALL JNK JK
        sizes[op] = 3
    for cc in range(8):
        sizes[0xC2 | (cc << 3)] = 3  # Jcc
        sizes[0xC4 | (cc << 3)] = 3  # Ccc
    for op in (0xC6, 0xCE, 0xD6, 0xDE, 0xE6, 0xEE, 0xF6, 0xFE, 0xD3, 0xDB, 0x28, 0x38):
        sizes[op] = 2  # ALU immediate, OUT, IN, LDHI, LDSI
    return tuple(sizes)


INSTRUCTION_SIZES = _build_size_table()


def _build_timing_table():
    """
    8085 T-states per opcode. Conditional instructions have a
    (taken, not taken) pair; instructions using M have their memory timing.
    """
    t = [4] * 256  # NOP, rotates, DAA, CMA, STC, CMC, RIM, SIM, EI, DI, XCHG, MOV r,r, ALU r
    for op in range(0x40, 0x80):
        if (op >> 3) & 7 == 6 or op & 7 == 6:
            t[op] = 7  # MOV with M
    t[0x76] = 5  # HLT
    for op in range(0x80, 0xC0):
        if op & 7 == 6:
            t[op] = 7  # ALU M
    for r in range(8):
        t[0x06 | (r << 3)] = 10 if r == 6 else 7  # MVI
        t[0x04 | (r << 3)] = 10 if r == 6 else 4  # INR
        t[0x05 | (r << 3)] = 10 if r == 6 else 4  # DCR
    for rp in range(4):
        t[0x01 | (rp << 4)] = 10  # LXI
        t[0x09 | (rp << 4)] = 10  # DAD
        t[0x03 | (rp << 4)] = 6  # INX
        t[0x0B | (rp << 4)] = 6  # DCX
        t[0xC1 | (rp << 4)] = 10  # POP
        t[0xC5 | (rp << 4)] = 12  # PUSH
    for op in (0x02, 0x12, 0x0A, 0x1A):
        t[op] = 7  # STAX / LDAX
    t[0x22] = t[0x2A] = 16  # SHLD / LHLD
    t[0x32] = t[0x3A] = 13  # STA / LDA
    for cc in range(8):
        t[0xC0 | (cc << 3)] = (12, 6)  # Rcc
        t[0xC2 | (cc << 3)] = (10, 7)  # Jcc
        t[0xC4 | (cc << 3)] = (18, 9)  # Ccc
        t[0xC6 | (cc << 3)] = 7  # ALU immediate
        t[0xC7 | (cc << 3)] = 12  # RST n
    t[0xC3] = 10  # JMP
    t[0xC9] = 10  # RET
    t[0xCD] = 18  # CALL
    t[0xD3] = t[0xDB] = 10  # OUT / IN
    t[0xE3] = 16  # XTHL
    t[0xE9] = t[0xF9] = 6  # PCHL / SPHL
    # Undocumented instructions
    t[0x08] = 10  # DSUB
    t[0x10] = 7  # ARHL
    t[0x18] = 10  # RDEL
    t[0x28] = t[0x38] = 10  # LDHI / LDSI
    t[0xCB] = (12, 6)  # RSTV
    t[0xD9] = t[0xED] = 10  # SHLX / LHLX
    t[0xDD] = t[0xFD] = (10, 7)  # JNK / JK
    return tuple(t)


INSTRUCTION_T_STATES = _build_timing_table()


def _hex8(value):
    """Format a byte the way an 8085 assembler accepts it (leading 0 before A-F)."""
    text = f"{value:02X}H"
    return "0" + text if text[0] in "ABCDEF" else text


def _hex16(value):
    text = f"{value:04X}H"
    return "0" + text if text[0] in "ABCDEF" else text


class Processor8085:
    """
    8085 microprocessor simulator: registers, flags, memory, I/O ports,
    interrupt system and instruction execution.
    """

    def __init__(self):
        self.registers = {
            "A": 0,
            "B": 0,
            "C": 0,
            "D": 0,
            "E": 0,
            "H": 0,
            "L": 0,
            "SP": 0xFFFF,
            "PC": 0x0000,
        }
        # Documented flags S, Z, AC, P, C plus the undocumented K (bit 5) and V (bit 1)
        self.flags = {"S": 0, "Z": 0, "K": 0, "AC": 0, "P": 0, "V": 0, "C": 0}
        self.memory = bytearray(0x10000)  # 64KB memory space
        self.input_ports = bytearray(0x100)  # Latches read by IN (driven by input devices)
        self.output_ports = bytearray(0x100)  # Latches written by OUT (drive output devices)
        self.last_io = None  # ("IN" | "OUT", port, value) of the last executed instruction
        self.halted = False
        self.error = None
        self.last_address = None  # Address of the last executed instruction
        self._last = None  # (opcode, byte1, word) of the last executed instruction
        self._last_text = None  # Description of an interrupt acknowledge cycle
        self.t_states = 0  # Total clock cycles (T-states) executed
        self.trace_bus = False  # Record the machine cycles of every step in bus_cycles
        self.bus_cycles = None  # Machine cycles of the last step (when trace_bus is set)

        # One handler per opcode (see _build_dispatch)
        self._dispatch = self._build_dispatch()

        # Peripheral chips on the I/O bus (PeripheralBus) and the T-state at
        # which one of their outputs wired to an interrupt pin changes next
        self.io_bus = None
        self._io_deadline = _NEVER

        # Interrupt system
        self.pins = dict.fromkeys(INTERRUPT_PINS, 0)  # External input pin levels
        self._any_pin_high = False  # any(self.pins.values()), kept up to date for step()
        # Each pin can be driven by several sources (the front panel, chip
        # outputs); its level is the OR of them
        self._pin_sources = {name: {} for name in INTERRUPT_PINS}
        # T-state at which each request appeared (None = before anything ran);
        # used to sample interrupts at the next-to-last clock of an instruction
        self._request_time = dict.fromkeys(INTERRUPT_PINS)
        self.trap_ff = 0  # Set by a rising edge on TRAP, cleared on acknowledge
        self.rst75_ff = 0  # R7.5 flip-flop: set by a rising edge on RST 7.5
        self.interrupt_enable = 0  # INTE flip-flop
        self.interrupt_masks = 0b111  # bit2 = M7.5, bit1 = M6.5, bit0 = M5.5 (set by RESET)
        self._ei_delay = False  # EI enables interrupts after the next instruction
        self._trap_saved_ie = None  # INTE before the last TRAP (reported by the next RIM)
        self._auto_release = set()  # Pins a device drops when its interrupt is acknowledged
        self.intr_instruction = (0xFF,)  # Instruction supplied by the device during INTA
        self.last_interrupt = None  # Interrupt acknowledged by the last step()
        self.interrupt_log = []  # (name, return address, target) of acknowledged interrupts

        # Serial pins
        self.sid = 0  # Serial input data line (read by RIM)
        self.sod = 0  # Serial output data latch (written by SIM)

        # Assembly metadata (used by the UI)
        self.starting_address = 0x0000
        self.program_end_address = 0
        self.program_memory_range = set()
        self.data_memory_range = set()
        self.parsed_program = []
        self.line_to_address_map = {}
        self.address_to_line_map = {}
        self.labels = {}
        self.symbols = {}
        self._address_to_label = {}

    @property
    def io_ports(self):
        """Alias of output_ports."""
        return self.output_ports

    def load_program(self, assembly_output):
        """Loads the output of Assembler8085.assemble() into memory and resets the CPU state."""
        self.memory = assembly_output.memory
        self.parsed_program = assembly_output.parsed_program
        self.line_to_address_map = assembly_output.line_to_address_map
        self.address_to_line_map = assembly_output.address_to_line_map
        self.labels = assembly_output.labels
        self.symbols = assembly_output.symbols
        self.program_end_address = assembly_output.program_end_address
        self.program_memory_range = assembly_output.program_memory_range
        self.data_memory_range = assembly_output.data_memory_range
        self.starting_address = assembly_output.starting_address
        if self.io_bus is not None:
            self.io_bus.rebase()

        # Reverse label lookup for readable disassembly
        self._address_to_label = {}
        for name, addr in self.labels.items():
            self._address_to_label.setdefault(addr, name)

        self.registers["PC"] = assembly_output.starting_address
        self.halted = False
        self.error = None
        self.last_address = None
        self._last = None
        self._last_text = None
        self.t_states = 0
        self.bus_cycles = None

    def reset(self):
        """
        Hardware RESET (RESET IN low): clears the halt state, the INTE, R7.5
        and TRAP flip-flops and SOD, and sets the RST 7.5/6.5/5.5 masks.
        Registers, flags, the stack pointer and memory keep their contents.
        PC is set to the program's starting address (the
        address a trainer kit would GO to after reset).
        """
        self.registers["PC"] = self.starting_address
        self.halted = False
        self.error = None
        self.last_address = None
        self._last = None
        self._last_text = None
        self.last_io = None
        self.t_states = 0
        self.interrupt_enable = 0
        self.interrupt_masks = 0b111
        self.trap_ff = 0
        self.rst75_ff = 0
        self._ei_delay = False
        self._trap_saved_ie = None
        self.sod = 0
        self.last_interrupt = None
        self.bus_cycles = None
        if self.io_bus is not None:
            # RESET OUT resets the 8255 (the 8253 has no RESET input)
            self.io_bus.cpu_reset()

    @property
    def last_instruction(self):
        """Disassembly of the last executed instruction (or interrupt acknowledge)."""
        if self._last_text is not None:
            return self._last_text
        if self._last is None:
            return None
        opcode, b1, imm16 = self._last
        return disassemble_opcode(opcode, b1, imm16, self._address_to_label)

    # ------------------------------------------------------------------
    # Interrupt pins
    # ------------------------------------------------------------------

    def set_pin(self, name, level, auto_release=False, source="panel", at=None):
        """
        Drives an interrupt input pin from a source (the front panel by
        default, or a chip output). The pin level is the OR of all sources. A
        rising edge on TRAP or RST 7.5 sets the corresponding flip-flop. With
        auto_release, the (simulated) panel device drops TRAP or INTR again
        when the CPU acknowledges the interrupt.

        `at` is the T-state at which the level changes. The CPU samples
        interrupts in the next-to-last clock cycle of each instruction, so a
        request that appears in the last clock cycle of an instruction is only
        recognised after the following instruction. None means the change
        happened before the instruction that is about to execute.
        """
        if name not in self.pins:
            raise ValueError(f"Unknown interrupt pin: {name}")
        sources = self._pin_sources[name]
        sources[source] = 1 if level else 0
        level = 1 if any(sources.values()) else 0
        if level and not self.pins[name]:
            self._request_time[name] = at
            if name == "TRAP":
                self.trap_ff = 1
            elif name == "RST7.5":
                self.rst75_ff = 1
        self.pins[name] = level
        self._any_pin_high = any(self.pins.values())
        if source == "panel":
            if sources["panel"] and auto_release:
                self._auto_release.add(name)
            else:
                self._auto_release.discard(name)

    def pin_source_level(self, name, source):
        """Level one source drives on an interrupt pin."""
        return self._pin_sources[name].get(source, 0)

    def pulse_rst75(self, at=None):
        """Applies a rising edge (low-high-low pulse) to the RST 7.5 pin."""
        self.set_pin("RST7.5", 0, at=at)
        self.set_pin("RST7.5", 1, at=at)
        self.set_pin("RST7.5", 0, at=at)

    def set_intr_instruction(self, data):
        """
        Sets the instruction the interrupting device places on the data bus
        during the INTA cycles. RST n and CALL a16 are the usual choices, but
        "any instruction could be used (except EI or DI)" (MCS-80/85 User's
        Manual, 2.3.4): its opcode and operand bytes are read in INTA cycles
        while the PC is not incremented, then it executes.
        """
        data = tuple(byte & 0xFF for byte in data)
        if not data:
            raise ValueError("INTA must supply an instruction")
        opcode = data[0]
        if opcode in (0xFB, 0xF3):
            raise ValueError("EI and DI cannot be supplied during INTA")
        if len(data) != INSTRUCTION_SIZES[opcode]:
            raise ValueError(f"{disassemble_opcode(opcode).split()[0]} needs {INSTRUCTION_SIZES[opcode]} byte(s)")
        self.intr_instruction = data

    def pending_interrupt(self, sampled=False):
        """
        Returns the interrupt the CPU would acknowledge, or None. With
        sampled=True only requests the CPU has actually sampled count: those
        present before the next-to-last clock cycle of the instruction that has
        just finished (in HALT, interrupts are sampled on every clock).
        """
        if sampled:
            # Running: sampled in the next-to-last clock of the instruction.
            # Halted: sampled during a THALT state; the CPU enters M1.T1 at the
            # end of the next clock period. Either way a request is seen two
            # T-states after it appears.
            cutoff = self.t_states - 1
            times = self._request_time

            def seen(name):
                at = times[name]
                return at is None or at < cutoff
        else:
            def seen(_name):
                return True

        if self.trap_ff and self.pins["TRAP"] and seen("TRAP"):
            return "TRAP"
        if not self.interrupt_enable or self._ei_delay:
            return None
        masks = self.interrupt_masks
        if self.rst75_ff and not masks & 0b100 and seen("RST7.5"):
            return "RST7.5"
        if self.pins["RST6.5"] and not masks & 0b010 and seen("RST6.5"):
            return "RST6.5"
        if self.pins["RST5.5"] and not masks & 0b001 and seen("RST5.5"):
            return "RST5.5"
        if self.pins["INTR"] and seen("INTR"):
            return "INTR"
        return None

    def peek_t_states(self):
        """
        T-states the next step() will take: the interrupt acknowledge if one is
        pending, otherwise the instruction at PC (using the current flags for
        conditional instructions). Returns None while halted with nothing to
        wake the CPU. Used to complete instructions exactly on the clock.
        """
        interrupt = self.pending_interrupt(sampled=True)
        if interrupt is not None:
            if interrupt != "INTR":
                return 12
            opcode = self.intr_instruction[0]
            timing = INSTRUCTION_T_STATES[opcode]
            if isinstance(timing, int):
                return timing
            return timing[0] if self.branch_taken(opcode) else timing[1]
        if self.halted or self.error:
            return None
        op = self.memory[self.registers["PC"]]
        timing = INSTRUCTION_T_STATES[op]
        if isinstance(timing, int):
            return timing
        return timing[0] if self.branch_taken(op) else timing[1]

    def branch_taken(self, op):
        """
        Whether a conditional instruction (Jcc, Ccc, Rcc, JNK, JK, RSTV) would
        take its branch with the current flags. True for every other opcode.
        """
        if not isinstance(INSTRUCTION_T_STATES[op], tuple):
            return True
        if op == 0xCB:  # RSTV
            return self.flags["V"] == 1
        if op in (0xDD, 0xFD):  # JNK / JK
            return self.flags["K"] == (1 if op == 0xFD else 0)
        return self._condition((op >> 3) & 7)

    def idle(self, cycles):
        """
        HALT state: the clock keeps running while the CPU waits, and interrupts
        are sampled on every clock. Advances the T-state count by up to the
        given number of clock cycles if (and only if) the CPU is halted. It
        stops early, at the exact T-state, when a peripheral output wired to an
        interrupt pin makes an interrupt pending. Returns the cycles used.
        """
        if not self.halted or cycles <= 0 or self.pending_interrupt(sampled=True) is not None:
            return 0  # an interrupt already sampled is acknowledged without waiting
        start = self.t_states
        end = start + cycles
        while self.t_states < end:
            if self.pending_interrupt(sampled=True) is not None:
                break
            target = end
            requested = self.pending_interrupt()
            if requested is not None:  # requested but not sampled yet: wake when it is
                at = self._request_time[requested]
                target = min(end, max(self.t_states + 1, (at if at is not None else self.t_states) + 2))
            if self._io_deadline < target:
                self.t_states = max(self.t_states, self._io_deadline)
                self.io_bus.sync(self.t_states)
                continue
            self.t_states = target
        return self.t_states - start

    def can_resume(self):
        """True if a halted CPU can still be woken by an interrupt (INTE set or one pending)."""
        return bool(self.interrupt_enable) or self.pending_interrupt() is not None

    def _acknowledge(self, name):
        """Interrupt acknowledge: push PC and jump to the service routine."""
        return_address = self.registers["PC"]
        if name == "TRAP":
            self._trap_saved_ie = self.interrupt_enable
            self.trap_ff = 0
        elif name == "RST7.5":
            self.rst75_ff = 0

        if self.trace_bus:
            self.bus_cycles = plan_interrupt(self, name)

        # Any interrupt acknowledge resets the INTE flip-flop
        self.interrupt_enable = 0
        self._ei_delay = False
        self.halted = False
        if name in self._auto_release:
            self._auto_release.discard(name)
            self._pin_sources[name]["panel"] = 0
            self.pins[name] = 1 if any(self._pin_sources[name].values()) else 0
            self._any_pin_high = any(self.pins.values())

        if name == "INTR":
            # The instruction supplied in the INTA cycles executes with the PC
            # not incremented (usually RST n or CALL, which push it)
            data = self.intr_instruction
            opcode = data[0]
            b1 = data[1] if len(data) > 1 else 0
            word = (data[2] << 8) | data[1] if len(data) > 2 else b1
            self.t_states += self._dispatch[opcode](b1, word)
            target = self.registers["PC"]
            description = f"INTR acknowledged (INTA: {disassemble_opcode(opcode, b1, word)})"
        else:
            target = INTERRUPT_VECTORS[name]
            self._push16(return_address)
            self.registers["PC"] = target
            self.t_states += 12
            description = f"{name[:3]} {name[3:]} acknowledged" if name != "TRAP" else "TRAP acknowledged"
        self.last_interrupt = name
        self.last_address = return_address
        self._last = None
        self._last_text = f"{description} -> {target:04X}H (return address {return_address:04X}H)"
        self.interrupt_log.append((name, return_address, target))
        if self.trace_bus:
            finish_cycles(self, self.bus_cycles)
        if self.io_bus is not None:
            self.io_bus.cpu_state_changed()

    def rim_value(self):
        """Value RIM loads into A (without consuming the post-TRAP IE status)."""
        ie_bit = self.interrupt_enable if self._trap_saved_ie is None else self._trap_saved_ie
        return (
            (self.sid << 7)
            | (self.rst75_ff << 6)
            | (self.pins["RST6.5"] << 5)
            | (self.pins["RST5.5"] << 4)
            | (ie_bit << 3)
            | self.interrupt_masks
        )

    # ------------------------------------------------------------------
    # Register pair / flag helpers
    # ------------------------------------------------------------------

    def get_hl_addr(self):
        """HL as a 16-bit value."""
        return (self.registers["H"] << 8) | self.registers["L"]

    def get_bc_addr(self):
        """BC as a 16-bit value."""
        return (self.registers["B"] << 8) | self.registers["C"]

    def get_de_addr(self):
        """DE as a 16-bit value."""
        return (self.registers["D"] << 8) | self.registers["E"]

    def get_psw(self):
        """A and the flags byte as a 16-bit value (what PUSH PSW stores)."""
        return (self.registers["A"] << 8) | self.get_flags_byte()

    def get_flags_byte(self):
        """The flags as a byte: S Z K AC 0 P V CY (bit 7 to bit 0)."""
        f = self.flags
        return (
            (f["S"] << 7)
            | (f["Z"] << 6)
            | (f["K"] << 5)
            | (f["AC"] << 4)
            | (f["P"] << 2)
            | (f["V"] << 1)
            | f["C"]
        )

    def set_flags_byte(self, value):
        """Loads all flags from a flags byte (as done by POP PSW). Bit 3 is ignored."""
        f = self.flags
        f["S"] = (value >> 7) & 1
        f["Z"] = (value >> 6) & 1
        f["K"] = (value >> 5) & 1
        f["AC"] = (value >> 4) & 1
        f["P"] = (value >> 2) & 1
        f["V"] = (value >> 1) & 1
        f["C"] = value & 1

    def update_flags(
        self, result, check_carry=False, carry_value=None, check_ac=False, ac_value=None
    ):
        """
        Updates S, Z and P from an 8-bit result and optionally AC and CY.
        """
        self._set_szp(result)
        if check_ac:
            self.flags["AC"] = ac_value
        if check_carry:
            self.flags["C"] = carry_value

    def _set_szp(self, value):
        value &= 0xFF
        f = self.flags
        f["S"] = value >> 7
        f["Z"] = 1 if value == 0 else 0
        f["P"] = _PARITY[value]

    def _get_pair(self, rp):
        """rp: 0=BC, 1=DE, 2=HL, 3=SP"""
        if rp == 3:
            return self.registers["SP"]
        hi, lo = (("B", "C"), ("D", "E"), ("H", "L"))[rp]
        return (self.registers[hi] << 8) | self.registers[lo]

    def _set_pair(self, rp, value):
        value &= 0xFFFF
        if rp == 3:
            self.registers["SP"] = value
            return
        hi, lo = (("B", "C"), ("D", "E"), ("H", "L"))[rp]
        self.registers[hi] = value >> 8
        self.registers[lo] = value & 0xFF

    def _get_reg(self, code):
        """Read register by 3-bit code; code 6 (M) reads memory at HL."""
        if code == 6:
            return self.memory[self.get_hl_addr()]
        return self.registers[REG_NAMES[code]]

    def _set_reg(self, code, value):
        if code == 6:
            self.memory[self.get_hl_addr()] = value & 0xFF
        else:
            self.registers[REG_NAMES[code]] = value & 0xFF

    def _condition(self, cc):
        """Evaluates condition code: NZ, Z, NC, C, PO, PE, P, M"""
        flag = ("Z", "C", "P", "S")[cc >> 1]
        return self.flags[flag] == (cc & 1)

    def _push16(self, value):
        sp = self.registers["SP"]
        self.memory[(sp - 1) & 0xFFFF] = (value >> 8) & 0xFF
        self.memory[(sp - 2) & 0xFFFF] = value & 0xFF
        self.registers["SP"] = (sp - 2) & 0xFFFF

    def _pop16(self):
        sp = self.registers["SP"]
        low = self.memory[sp]
        high = self.memory[(sp + 1) & 0xFFFF]
        self.registers["SP"] = (sp + 2) & 0xFFFF
        return (high << 8) | low

    # ------------------------------------------------------------------
    # ALU
    # ------------------------------------------------------------------

    def _adder(self, a, b, carry_in):
        """
        8-bit ALU addition a + b + carry_in. Sets S, Z, P, AC, V and K and
        returns (8-bit result, carry out of bit 7).
        """
        total = a + b + carry_in
        carry_out = total >> 8
        result = total & 0xFF
        sign = result >> 7
        overflow = (((a & 0x7F) + (b & 0x7F) + carry_in) >> 7) ^ carry_out  # carry into bit 7 xor carry out
        f = self.flags
        f["AC"] = ((a & 0x0F) + (b & 0x0F) + carry_in) >> 4
        f["S"] = sign
        f["Z"] = 0 if result else 1
        f["P"] = _PARITY[result]
        f["V"] = overflow
        f["K"] = overflow ^ sign
        return result, carry_out

    def _alu_add(self, value, carry_in):
        result, carry_out = self._adder(self.registers["A"], value, carry_in)
        self.flags["C"] = carry_out
        return result

    def _alu_sub(self, value, borrow_in):
        """A - value - borrow, computed as A + ~value + !borrow like the 8085 ALU."""
        result, carry_out = self._adder(self.registers["A"], (~value) & 0xFF, 1 - borrow_in)
        self.flags["C"] = 1 - carry_out  # CY = borrow
        return result

    def _logic_flags(self, result, ac):
        f = self.flags
        f["S"] = result >> 7
        f["Z"] = 1 if result == 0 else 0
        f["P"] = _PARITY[result]
        f["C"] = 0
        f["AC"] = ac
        f["V"] = 0
        f["K"] = f["S"]  # K = V ^ S with V = 0

    def _alu(self, operation, value):
        """Executes ADD/ADC/SUB/SBB/ANA/XRA/ORA/CMP (0-7) with the given operand."""
        a = self.registers["A"]
        if operation == 0:  # ADD
            self.registers["A"] = self._alu_add(value, 0)
        elif operation == 1:  # ADC
            self.registers["A"] = self._alu_add(value, self.flags["C"])
        elif operation == 2:  # SUB
            self.registers["A"] = self._alu_sub(value, 0)
        elif operation == 3:  # SBB
            self.registers["A"] = self._alu_sub(value, self.flags["C"])
        elif operation == 4:  # ANA: CY=0, AC=1 on the 8085
            self.registers["A"] = a & value
            self._logic_flags(a & value, 1)
        elif operation == 5:  # XRA: CY=0, AC=0
            self.registers["A"] = a ^ value
            self._logic_flags(a ^ value, 0)
        elif operation == 6:  # ORA: CY=0, AC=0
            self.registers["A"] = a | value
            self._logic_flags(a | value, 0)
        else:  # CMP: flags as SUB, accumulator unchanged
            self._alu_sub(value, 0)

    def _daa(self):
        a = self.registers["A"]
        correction = 0
        carry = self.flags["C"]
        if (a & 0x0F) > 9 or self.flags["AC"]:
            correction |= 0x06
        if a > 0x99 or carry:
            correction |= 0x60
            carry = 1
        result, _ = self._adder(a, correction, 0)  # sets S Z P AC V K
        self.flags["C"] = carry
        self.registers["A"] = result

    def _dsub(self):
        """DSUB (undocumented): HL <- HL - BC, done by the ALU as L-C then H-B-borrow."""
        regs = self.registers
        low, carry_low = self._adder(regs["L"], (~regs["C"]) & 0xFF, 1)
        high, carry_high = self._adder(regs["H"], (~regs["B"]) & 0xFF, carry_low)
        self.flags["C"] = 1 - carry_high  # borrow
        self.flags["Z"] = 1 if (high | low) == 0 else 0  # zero for the 16-bit result
        regs["H"], regs["L"] = high, low

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def step(self):
        """
        Services a pending interrupt, or fetches, decodes and executes one
        instruction at the current PC.
        Returns execution status: "OK", "HALT", or "ERROR".
        """
        if self.error:
            return "ERROR"

        # Per-step reports (only written when set, to keep the hot path fast)
        if self.last_io is not None:
            self.last_io = None
        if self._last_text is not None:
            self._last_text = None
            self.last_interrupt = None

        # Interrupts sampled in the next-to-last clock of the previous
        # instruction (or during HALT) are acknowledged now (the cheap pre-test
        # skips the full check when nothing can interrupt)
        if self.trap_ff or (self.interrupt_enable and (self.rst75_ff or self._any_pin_high)):
            interrupt = self.pending_interrupt(sampled=True)
            if interrupt is not None:
                self._acknowledge(interrupt)
                return "OK"

        if self.halted:
            if self.trace_bus:
                self.bus_cycles = []  # HALT state: no machine cycles
            return "HALT"

        memory = self.memory
        pc = self.registers["PC"]
        opcode = memory[pc]
        b1 = memory[(pc + 1) & 0xFFFF]
        imm16 = (memory[(pc + 2) & 0xFFFF] << 8) | b1
        self.last_address = pc
        self._last = (opcode, b1, imm16)

        trace = self.trace_bus
        if trace:  # machine cycles are planned from the state before execution
            cycles = plan_instruction(self, opcode, pc, self.branch_taken(opcode))

        # Fetch advances PC past the whole instruction before execution
        self.registers["PC"] = (pc + INSTRUCTION_SIZES[opcode]) & 0xFFFF

        try:
            self.t_states += self._dispatch[opcode](b1, imm16)
        except Exception as e:  # Defensive: should not happen for valid opcodes
            self.error = f"Internal error executing {opcode:02X}H at {pc:04X}H: {e}"
            return "ERROR"

        while self.t_states >= self._io_deadline:  # a wired chip output changes
            self.io_bus.sync(self._io_deadline)

        if trace:
            self.bus_cycles = finish_cycles(self, cycles)

        if self._ei_delay and opcode != 0xFB:  # EI blocks interrupts for one more instruction
            self._ei_delay = False

        return "HALT" if self.halted else "OK"

    def _build_dispatch(self):
        """
        Builds the opcode dispatch table: one handler per opcode, called as
        handler(byte 1, word) and returning the T-states. The frequent
        instructions get handlers specialised for their registers, ALU
        operation or condition, so no decoding happens while running; the
        rest use _execute. The behaviour is identical (checked opcode by opcode
        against an independent reference model in the test suite).
        """
        cpu = self
        regs = self.registers
        flags = self.flags
        alu_add = self._alu_add
        alu_sub = self._alu_sub
        logic = self._logic_flags
        adder = self._adder
        push16 = self._push16
        pop16 = self._pop16
        execute = self._execute

        def fallback(op):
            return lambda b1, w: execute(op, b1, w)

        table = [fallback(op) for op in range(256)]

        def hl():
            return (regs["H"] << 8) | regs["L"]

        # MOV r1, r2 / MOV M, r / MOV r, M
        for d in range(8):
            for src in range(8):
                op = 0x40 | (d << 3) | src
                if op == 0x76:
                    continue  # HLT
                dn, sn = REG_NAMES[d], REG_NAMES[src]
                if d == 6:
                    def h(b1, w, sn=sn):
                        cpu.memory[(regs["H"] << 8) | regs["L"]] = regs[sn]
                        return 7
                elif src == 6:
                    def h(b1, w, dn=dn):
                        regs[dn] = cpu.memory[(regs["H"] << 8) | regs["L"]]
                        return 7
                else:
                    def h(b1, w, dn=dn, sn=sn):
                        regs[dn] = regs[sn]
                        return 4
                table[op] = h

        # ALU operations on A
        def op_add(v):
            regs["A"] = alu_add(v, 0)

        def op_adc(v):
            regs["A"] = alu_add(v, flags["C"])

        def op_sub(v):
            regs["A"] = alu_sub(v, 0)

        def op_sbb(v):
            regs["A"] = alu_sub(v, flags["C"])

        def op_ana(v):
            r = regs["A"] & v
            regs["A"] = r
            logic(r, 1)

        def op_xra(v):
            r = regs["A"] ^ v
            regs["A"] = r
            logic(r, 0)

        def op_ora(v):
            r = regs["A"] | v
            regs["A"] = r
            logic(r, 0)

        def op_cmp(v):
            alu_sub(v, 0)

        alu_ops = (op_add, op_adc, op_sub, op_sbb, op_ana, op_xra, op_ora, op_cmp)
        for k, fn in enumerate(alu_ops):
            for src in range(8):
                if src == 6:
                    def h(b1, w, fn=fn):
                        fn(cpu.memory[(regs["H"] << 8) | regs["L"]])
                        return 7
                else:
                    def h(b1, w, fn=fn, sn=REG_NAMES[src]):
                        fn(regs[sn])
                        return 4
                table[0x80 | (k << 3) | src] = h

            def h_imm(b1, w, fn=fn):
                fn(b1)
                return 7
            table[0xC6 | (k << 3)] = h_imm

        # MVI, INR, DCR
        for r in range(8):
            if r == 6:
                def mvi(b1, w):
                    cpu.memory[(regs["H"] << 8) | regs["L"]] = b1
                    return 10

                def inr(b1, w):
                    addr = (regs["H"] << 8) | regs["L"]
                    cpu.memory[addr] = adder(cpu.memory[addr], 0x01, 0)[0]
                    return 10

                def dcr(b1, w):
                    addr = (regs["H"] << 8) | regs["L"]
                    cpu.memory[addr] = adder(cpu.memory[addr], 0xFF, 0)[0]
                    return 10
            else:
                name = REG_NAMES[r]

                def mvi(b1, w, name=name):
                    regs[name] = b1
                    return 7

                def inr(b1, w, name=name):
                    regs[name] = adder(regs[name], 0x01, 0)[0]
                    return 4

                def dcr(b1, w, name=name):
                    regs[name] = adder(regs[name], 0xFF, 0)[0]
                    return 4
            table[0x06 | (r << 3)] = mvi
            table[0x04 | (r << 3)] = inr
            table[0x05 | (r << 3)] = dcr

        # Register pairs: LXI, INX, DCX, DAD, PUSH, POP
        for rp in range(4):
            if rp == 3:
                def lxi(b1, w):
                    regs["SP"] = w
                    return 10

                def inx(b1, w):
                    v = regs["SP"]
                    flags["K"] = 1 if v == 0xFFFF else 0
                    regs["SP"] = (v + 1) & 0xFFFF
                    return 6

                def dcx(b1, w):
                    v = regs["SP"]
                    flags["K"] = 1 if v == 0 else 0
                    regs["SP"] = (v - 1) & 0xFFFF
                    return 6

                def dad(b1, w):
                    return cpu._dad(regs["SP"])
            else:
                hi, lo = (("B", "C"), ("D", "E"), ("H", "L"))[rp]

                def lxi(b1, w, hi=hi, lo=lo):
                    regs[hi] = w >> 8
                    regs[lo] = w & 0xFF
                    return 10

                def inx(b1, w, hi=hi, lo=lo):
                    v = (regs[hi] << 8) | regs[lo]
                    flags["K"] = 1 if v == 0xFFFF else 0
                    v = (v + 1) & 0xFFFF
                    regs[hi] = v >> 8
                    regs[lo] = v & 0xFF
                    return 6

                def dcx(b1, w, hi=hi, lo=lo):
                    v = (regs[hi] << 8) | regs[lo]
                    flags["K"] = 1 if v == 0 else 0
                    v = (v - 1) & 0xFFFF
                    regs[hi] = v >> 8
                    regs[lo] = v & 0xFF
                    return 6

                def dad(b1, w, hi=hi, lo=lo):
                    return cpu._dad((regs[hi] << 8) | regs[lo])

                def push(b1, w, hi=hi, lo=lo):
                    push16((regs[hi] << 8) | regs[lo])
                    return 12

                def pop(b1, w, hi=hi, lo=lo):
                    v = pop16()
                    regs[hi] = v >> 8
                    regs[lo] = v & 0xFF
                    return 10
                table[0xC5 | (rp << 4)] = push
                table[0xC1 | (rp << 4)] = pop
            table[0x01 | (rp << 4)] = lxi
            table[0x03 | (rp << 4)] = inx
            table[0x0B | (rp << 4)] = dcx
            table[0x09 | (rp << 4)] = dad

        # Loads and stores
        def lda(b1, w):
            regs["A"] = cpu.memory[w]
            return 13

        def sta(b1, w):
            cpu.memory[w] = regs["A"]
            return 13

        def ldax_b(b1, w):
            regs["A"] = cpu.memory[(regs["B"] << 8) | regs["C"]]
            return 7

        def ldax_d(b1, w):
            regs["A"] = cpu.memory[(regs["D"] << 8) | regs["E"]]
            return 7

        def stax_b(b1, w):
            cpu.memory[(regs["B"] << 8) | regs["C"]] = regs["A"]
            return 7

        def stax_d(b1, w):
            cpu.memory[(regs["D"] << 8) | regs["E"]] = regs["A"]
            return 7

        def xchg(b1, w):
            regs["D"], regs["H"] = regs["H"], regs["D"]
            regs["E"], regs["L"] = regs["L"], regs["E"]
            return 4

        def nop(b1, w):
            return 4

        table[0x3A], table[0x32] = lda, sta
        table[0x0A], table[0x1A], table[0x02], table[0x12] = ldax_b, ldax_d, stax_b, stax_d
        table[0xEB], table[0x00] = xchg, nop

        # Jumps, calls and returns
        condition_flags = (("Z", 0), ("Z", 1), ("C", 0), ("C", 1), ("P", 0), ("P", 1), ("S", 0), ("S", 1))

        def jmp(b1, w):
            regs["PC"] = w
            return 10

        def call(b1, w):
            push16(regs["PC"])
            regs["PC"] = w
            return 18

        def ret(b1, w):
            regs["PC"] = pop16()
            return 10

        table[0xC3], table[0xCD], table[0xC9] = jmp, call, ret
        for cc, (flag, value) in enumerate(condition_flags):
            def jcc(b1, w, flag=flag, value=value):
                if flags[flag] == value:
                    regs["PC"] = w
                    return 10
                return 7

            def ccc(b1, w, flag=flag, value=value):
                if flags[flag] == value:
                    push16(regs["PC"])
                    regs["PC"] = w
                    return 18
                return 9

            def rcc(b1, w, flag=flag, value=value):
                if flags[flag] == value:
                    regs["PC"] = pop16()
                    return 12
                return 6

            table[0xC2 | (cc << 3)] = jcc
            table[0xC4 | (cc << 3)] = ccc
            table[0xC0 | (cc << 3)] = rcc

            def rst(b1, w, target=cc * 8):
                push16(regs["PC"])
                regs["PC"] = target
                return 12
            table[0xC7 | (cc << 3)] = rst

        def rlc(b1, w):
            a = regs["A"]
            flags["C"] = a >> 7
            flags["V"] = ((a >> 7) ^ (a >> 6)) & 1
            regs["A"] = ((a << 1) | (a >> 7)) & 0xFF
            return 4

        def rrc(b1, w):
            a = regs["A"]
            flags["C"] = a & 1
            flags["V"] = 0
            regs["A"] = (a >> 1) | ((a & 1) << 7)
            return 4

        def ral(b1, w):
            a = regs["A"]
            carry = flags["C"]
            flags["C"] = a >> 7
            flags["V"] = ((a >> 7) ^ (a >> 6)) & 1
            regs["A"] = ((a << 1) | carry) & 0xFF
            return 4

        def rar(b1, w):
            a = regs["A"]
            carry = flags["C"]
            flags["C"] = a & 1
            flags["V"] = 0
            regs["A"] = (a >> 1) | (carry << 7)
            return 4

        def daa(b1, w):
            cpu._daa()
            return 4

        def cma(b1, w):
            regs["A"] ^= 0xFF
            return 4

        def stc(b1, w):
            flags["C"] = 1
            return 4

        def cmc(b1, w):
            flags["C"] ^= 1
            return 4

        table[0x07], table[0x0F], table[0x17], table[0x1F] = rlc, rrc, ral, rar
        table[0x27], table[0x2F], table[0x37], table[0x3F] = daa, cma, stc, cmc

        del hl
        return table

    def _dad(self, operand):
        """DAD: HL <- HL + operand; CY = carry out of bit 15, V = 16-bit signed overflow."""
        regs = self.registers
        hl = (regs["H"] << 8) | regs["L"]
        total = hl + operand
        carry_out = total >> 16
        self.flags["C"] = carry_out
        self.flags["V"] = (((hl & 0x7FFF) + (operand & 0x7FFF)) >> 15) ^ carry_out
        total &= 0xFFFF
        regs["H"] = total >> 8
        regs["L"] = total & 0xFF
        return 10

    def _execute(self, op, b1, imm16):
        """Executes a decoded instruction and returns the number of T-states used."""
        regs = self.registers

        # MOV r1,r2 (01DDDSSS) / HLT (76H)
        if 0x40 <= op <= 0x7F:
            if op == 0x76:
                self.halted = True
                return 5
            dst = (op >> 3) & 7
            src = op & 7
            self._set_reg(dst, self._get_reg(src))
            return 7 if (dst == 6 or src == 6) else 4

        # ALU register/memory (10OOOSSS)
        if 0x80 <= op <= 0xBF:
            src = op & 7
            self._alu((op >> 3) & 7, self._get_reg(src))
            return 7 if src == 6 else 4

        if op < 0x40:
            low3 = op & 7
            reg = (op >> 3) & 7
            rp = (op >> 4) & 3

            if low3 == 6:  # MVI r,d8
                self._set_reg(reg, b1)
                return 10 if reg == 6 else 7

            if low3 == 4 or low3 == 5:  # INR r / DCR r (ALU adds 01H or FFH, CY unaffected)
                result, _ = self._adder(self._get_reg(reg), 0x01 if low3 == 4 else 0xFF, 0)
                self._set_reg(reg, result)
                return 10 if reg == 6 else 4

            if low3 == 1:
                if op & 0x08:  # DAD rp
                    hl = self.get_hl_addr()
                    operand = self._get_pair(rp)
                    total = hl + operand
                    carry_out = total >> 16
                    carry_into_bit15 = ((hl & 0x7FFF) + (operand & 0x7FFF)) >> 15
                    self.flags["C"] = carry_out
                    self.flags["V"] = carry_into_bit15 ^ carry_out
                    self._set_pair(2, total)
                    return 10
                self._set_pair(rp, imm16)  # LXI rp,d16
                return 10

            if low3 == 3:
                value = self._get_pair(rp)
                if op & 0x08:  # DCX rp: K = borrow out of the 16-bit decrementer
                    self.flags["K"] = 1 if value == 0x0000 else 0
                    self._set_pair(rp, value - 1)
                else:  # INX rp: K = carry out of the 16-bit incrementer
                    self.flags["K"] = 1 if value == 0xFFFF else 0
                    self._set_pair(rp, value + 1)
                return 6

            if low3 == 2:
                if op == 0x02:  # STAX B
                    self.memory[self.get_bc_addr()] = regs["A"]
                    return 7
                if op == 0x12:  # STAX D
                    self.memory[self.get_de_addr()] = regs["A"]
                    return 7
                if op == 0x0A:  # LDAX B
                    regs["A"] = self.memory[self.get_bc_addr()]
                    return 7
                if op == 0x1A:  # LDAX D
                    regs["A"] = self.memory[self.get_de_addr()]
                    return 7
                if op == 0x22:  # SHLD a16
                    self.memory[imm16] = regs["L"]
                    self.memory[(imm16 + 1) & 0xFFFF] = regs["H"]
                    return 16
                if op == 0x2A:  # LHLD a16
                    regs["L"] = self.memory[imm16]
                    regs["H"] = self.memory[(imm16 + 1) & 0xFFFF]
                    return 16
                if op == 0x32:  # STA a16
                    self.memory[imm16] = regs["A"]
                    return 13
                regs["A"] = self.memory[imm16]  # 0x3A LDA a16
                return 13

            if low3 == 7:
                a = regs["A"]
                if op == 0x07:  # RLC (V as for A + A)
                    self.flags["C"] = a >> 7
                    self.flags["V"] = ((a >> 7) ^ (a >> 6)) & 1
                    regs["A"] = ((a << 1) | (a >> 7)) & 0xFF
                elif op == 0x0F:  # RRC
                    self.flags["C"] = a & 1
                    self.flags["V"] = 0
                    regs["A"] = ((a >> 1) | ((a & 1) << 7)) & 0xFF
                elif op == 0x17:  # RAL (V as for A + A)
                    carry = self.flags["C"]
                    self.flags["C"] = a >> 7
                    self.flags["V"] = ((a >> 7) ^ (a >> 6)) & 1
                    regs["A"] = ((a << 1) | carry) & 0xFF
                elif op == 0x1F:  # RAR
                    carry = self.flags["C"]
                    self.flags["C"] = a & 1
                    self.flags["V"] = 0
                    regs["A"] = ((a >> 1) | (carry << 7)) & 0xFF
                elif op == 0x27:  # DAA
                    self._daa()
                elif op == 0x2F:  # CMA (no flags)
                    regs["A"] = (~a) & 0xFF
                elif op == 0x37:  # STC
                    self.flags["C"] = 1
                else:  # 0x3F CMC
                    self.flags["C"] ^= 1
                return 4

            # low3 == 0
            if op == 0x00:  # NOP
                return 4
            if op == 0x20:  # RIM
                if self.io_bus is not None:
                    self.io_bus.sync(self.t_states)  # pin levels and R7.5 up to date
                regs["A"] = self.rim_value()
                self._trap_saved_ie = None
                return 4
            if op == 0x30:  # SIM
                bus = self.io_bus
                if bus is not None:
                    bus.sync(self.t_states)  # edges before SIM reach R7.5 before it may be reset
                a = regs["A"]
                if a & 0x08:  # MSE: mask set enable
                    self.interrupt_masks = a & 0x07
                if a & 0x10:  # R7.5: reset the RST 7.5 flip-flop
                    self.rst75_ff = 0
                if a & 0x40:  # SDE: serial data enable
                    self.sod = (a >> 7) & 1
                if bus is not None:
                    bus.cpu_state_changed()
                return 4
            if op == 0x08:  # DSUB (undocumented): HL <- HL - BC
                self._dsub()
                return 10
            if op == 0x10:  # ARHL (undocumented): arithmetic shift right HL, CY <- L0
                # V is cleared as by RRC/RAR, the other flags are unchanged
                # (die analyses by Ken Shirriff and Pavel Zima)
                hl = self.get_hl_addr()
                self.flags["C"] = hl & 1
                self.flags["V"] = 0
                self._set_pair(2, (hl >> 1) | (hl & 0x8000))
                return 7
            if op == 0x18:  # RDEL (undocumented): rotate DE left through carry
                de = self.get_de_addr()
                carry = self.flags["C"]
                self.flags["C"] = de >> 15
                self.flags["V"] = ((de >> 15) ^ (de >> 14)) & 1
                self._set_pair(1, (de << 1) | carry)
                return 10
            if op == 0x28:  # LDHI d8 (undocumented): DE <- HL + d8
                self._set_pair(1, self.get_hl_addr() + b1)
                return 10
            self._set_pair(1, regs["SP"] + b1)  # 0x38 LDSI d8 (undocumented): DE <- SP + d8
            return 10

        # 0xC0 - 0xFF
        low3 = op & 7
        cc = (op >> 3) & 7
        rp = (op >> 4) & 3

        if low3 == 0:  # Rcc
            if self._condition(cc):
                regs["PC"] = self._pop16()
                return 12
            return 6

        if low3 == 2:  # Jcc
            if self._condition(cc):
                regs["PC"] = imm16
                return 10
            return 7

        if low3 == 4:  # Ccc
            if self._condition(cc):
                self._push16(regs["PC"])
                regs["PC"] = imm16
                return 18
            return 9

        if low3 == 6:  # ALU immediate
            self._alu(cc, b1)
            return 7

        if low3 == 7:  # RST n
            self._push16(regs["PC"])
            regs["PC"] = cc * 8
            return 12

        if low3 == 1:
            if op & 0x08:
                if op == 0xC9:  # RET
                    regs["PC"] = self._pop16()
                    return 10
                if op == 0xE9:  # PCHL
                    regs["PC"] = self.get_hl_addr()
                    return 6
                if op == 0xF9:  # SPHL
                    regs["SP"] = self.get_hl_addr()
                    return 6
                de = self.get_de_addr()  # 0xD9 SHLX (undocumented): (DE) <- L, (DE+1) <- H
                self.memory[de] = regs["L"]
                self.memory[(de + 1) & 0xFFFF] = regs["H"]
                return 10
            value = self._pop16()  # POP rp / POP PSW
            if rp == 3:
                regs["A"] = value >> 8
                self.set_flags_byte(value & 0xFF)
            else:
                self._set_pair(rp, value)
            return 10

        if low3 == 5:
            if op == 0xCD:  # CALL
                self._push16(regs["PC"])
                regs["PC"] = imm16
                return 18
            if op == 0xDD or op == 0xFD:  # JNK / JK (undocumented): jump on K flag
                if self.flags["K"] == (1 if op == 0xFD else 0):
                    regs["PC"] = imm16
                    return 10
                return 7
            if op == 0xED:  # LHLX (undocumented): L <- (DE), H <- (DE+1)
                de = self.get_de_addr()
                regs["L"] = self.memory[de]
                regs["H"] = self.memory[(de + 1) & 0xFFFF]
                return 10
            self._push16(self.get_psw() if rp == 3 else self._get_pair(rp))  # PUSH rp / PSW
            return 12

        # low3 == 3
        if op == 0xC3:  # JMP
            regs["PC"] = imm16
            return 10
        if op == 0xCB:  # RSTV (undocumented): RST 8 (0040H) if V is set
            if self.flags["V"]:
                self._push16(regs["PC"])
                regs["PC"] = 0x0040
                return 12
            return 6
        if op == 0xD3:  # OUT port
            self.output_ports[b1] = regs["A"]
            bus = self.io_bus
            if bus is not None and bus.claims(b1):
                bus.write(b1, regs["A"], self.t_states + 10)  # WR trailing edge, end of T3 of M3
            self.last_io = ("OUT", b1, regs["A"])
            return 10
        if op == 0xDB:  # IN port
            bus = self.io_bus
            if bus is not None and bus.claims(b1):
                regs["A"] = bus.read(b1, self.t_states + 10)  # RD trailing edge, end of T3 of M3
            else:
                regs["A"] = self.input_ports[b1]
            self.last_io = ("IN", b1, regs["A"])
            return 10
        if op == 0xE3:  # XTHL
            sp = regs["SP"]
            sp1 = (sp + 1) & 0xFFFF
            regs["L"], self.memory[sp] = self.memory[sp], regs["L"]
            regs["H"], self.memory[sp1] = self.memory[sp1], regs["H"]
            return 16
        if op == 0xEB:  # XCHG
            regs["D"], regs["H"] = regs["H"], regs["D"]
            regs["E"], regs["L"] = regs["L"], regs["E"]
            return 4
        bus = self.io_bus
        if op == 0xF3:  # DI
            self.interrupt_enable = 0
            if bus is not None:
                bus.cpu_state_changed()
            return 4
        # 0xFB EI: INTE is set now, interrupts are accepted after the next instruction
        if bus is not None:
            bus.sync(self.t_states)  # pin levels and R7.5 up to date before interrupts are enabled
        self.interrupt_enable = 1
        self._ei_delay = True
        if bus is not None:
            bus.cpu_state_changed()
        return 4

    # ------------------------------------------------------------------
    # Disassembler
    # ------------------------------------------------------------------

    def disassemble(self, address):
        """Disassembles the instruction at address. Returns (text, size)."""
        op = self.memory[address & 0xFFFF]
        b1 = self.memory[(address + 1) & 0xFFFF]
        imm16 = (self.memory[(address + 2) & 0xFFFF] << 8) | b1
        return disassemble_opcode(op, b1, imm16, self._address_to_label), INSTRUCTION_SIZES[op]

    def is_program_memory(self, address):
        """True if the address holds program code rather than data."""
        return address in self.program_memory_range and address not in self.data_memory_range


def disassemble_opcode(op, b1=0, imm16=0, labels=None):
    """Returns assembler text for an opcode with its operand bytes."""

    def addr(value):
        text = _hex16(value)
        if labels and value in labels:
            text += f" ({labels[value]})"
        return text

    if op == 0x76:
        return "HLT"
    if 0x40 <= op <= 0x7F:
        return f"MOV {REG_NAMES[(op >> 3) & 7]}, {REG_NAMES[op & 7]}"
    if 0x80 <= op <= 0xBF:
        return f"{ALU_NAMES[(op >> 3) & 7]} {REG_NAMES[op & 7]}"

    fixed = {
        0x00: "NOP", 0x07: "RLC", 0x0F: "RRC", 0x17: "RAL", 0x1F: "RAR",
        0x20: "RIM", 0x27: "DAA", 0x2F: "CMA", 0x30: "SIM", 0x37: "STC",
        0x3F: "CMC", 0x02: "STAX B", 0x12: "STAX D", 0x0A: "LDAX B",
        0x1A: "LDAX D", 0xC9: "RET", 0xE9: "PCHL", 0xF9: "SPHL",
        0xE3: "XTHL", 0xEB: "XCHG", 0xF3: "DI", 0xFB: "EI",
        0x08: "DSUB", 0x10: "ARHL", 0x18: "RDEL", 0xCB: "RSTV", 0xD9: "SHLX", 0xED: "LHLX",
    }
    if op in fixed:
        return fixed[op]
    if op == 0x28:
        return f"LDHI {_hex8(b1)}"
    if op == 0x38:
        return f"LDSI {_hex8(b1)}"
    if op == 0xDD:
        return f"JNK {addr(imm16)}"
    if op == 0xFD:
        return f"JK {addr(imm16)}"

    if op < 0x40:
        low3 = op & 7
        reg = REG_NAMES[(op >> 3) & 7]
        rp = RP_NAMES[(op >> 4) & 3]
        if low3 == 6:
            return f"MVI {reg}, {_hex8(b1)}"
        if low3 == 4:
            return f"INR {reg}"
        if low3 == 5:
            return f"DCR {reg}"
        if low3 == 1:
            return f"DAD {rp}" if op & 0x08 else f"LXI {rp}, {_hex16(imm16)}"
        if low3 == 3:
            return f"DCX {rp}" if op & 0x08 else f"INX {rp}"
        return {0x22: "SHLD", 0x2A: "LHLD", 0x32: "STA", 0x3A: "LDA"}[op] + " " + addr(imm16)

    low3 = op & 7
    cc = (op >> 3) & 7
    rp = (op >> 4) & 3
    if low3 == 0:
        return f"R{COND_NAMES[cc]}"
    if low3 == 2:
        return f"J{COND_NAMES[cc]} {addr(imm16)}"
    if low3 == 4:
        return f"C{COND_NAMES[cc]} {addr(imm16)}"
    if low3 == 6:
        return f"{ALU_IMM_NAMES[cc]} {_hex8(b1)}"
    if low3 == 7:
        return f"RST {cc}"
    if low3 == 1:
        return "POP " + ("PSW" if rp == 3 else RP_NAMES[rp])
    if low3 == 5:
        if op == 0xCD:
            return f"CALL {addr(imm16)}"
        return "PUSH " + ("PSW" if rp == 3 else RP_NAMES[rp])
    if op == 0xC3:
        return f"JMP {addr(imm16)}"
    if op == 0xD3:
        return f"OUT {_hex8(b1)}"
    return f"IN {_hex8(b1)}"  # 0xDB
