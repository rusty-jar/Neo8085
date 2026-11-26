"""
Machine cycles and bus timing (bus.py), checked against an independent table
of 8085 machine-cycle sequences written from the Intel manuals, the T-state
table, and the bus behaviour of the 8085AH data sheet.
"""

import random
import re
import unittest

from helpers import Processor8085, assemble
from bus import CYCLE_TYPES, SIGNALS, waveform
from processor import INSTRUCTION_T_STATES, disassemble_opcode

# Machine cycles per instruction in the notation of the Intel 8080/8085 manuals:
# F = 4-T opcode fetch, S = 6-T opcode fetch, R = memory read, W = memory write,
# I = I/O read, O = I/O write, B = bus idle, H = halt.
# (pattern on the disassembly, sequence when taken, sequence when not taken)
REFERENCE = [
    (r"HLT$", "FH", None),
    (r"MOV M, ?", "FW", None),
    (r"MOV [A-L], ?M$", "FR", None),
    (r"MOV ", "F", None),
    (r"MVI M, ?", "FRW", None),
    (r"MVI ", "FR", None),
    (r"LXI ", "FRR", None),
    (r"LDA ", "FRRR", None),
    (r"STA ", "FRRW", None),
    (r"LHLD ", "FRRRR", None),
    (r"SHLD ", "FRRWW", None),
    (r"LDAX ", "FR", None),
    (r"STAX ", "FW", None),
    (r"(INR|DCR) M$", "FRW", None),
    (r"(INR|DCR) ", "F", None),
    (r"(INX|DCX) ", "S", None),
    (r"DAD ", "FBB", None),
    (r"(ADD|ADC|SUB|SBB|ANA|XRA|ORA|CMP) M$", "FR", None),
    (r"(ADD|ADC|SUB|SBB|ANA|XRA|ORA|CMP) ", "F", None),
    (r"(ADI|ACI|SUI|SBI|ANI|XRI|ORI|CPI) ", "FR", None),
    (r"JMP ", "FRR", None),
    (r"J(NZ|Z|NC|C|PO|PE|P|M|NK|K) ", "FRR", "FR"),
    (r"CALL ", "SRRWW", None),
    (r"C(NZ|Z|NC|C|PO|PE|P|M) ", "SRRWW", "SR"),
    (r"RET$", "FRR", None),
    (r"R(NZ|Z|NC|C|PO|PE|P|M)$", "SRR", "S"),
    (r"RST \d$", "SWW", None),
    (r"RSTV$", "SWW", "S"),
    (r"PUSH ", "SWW", None),
    (r"POP ", "FRR", None),
    (r"XTHL$", "FRRWW", None),
    (r"(SPHL|PCHL)$", "S", None),
    (r"IN ", "FRI", None),
    (r"OUT ", "FRO", None),
    (r"(XCHG|EI|DI|NOP|RIM|SIM|DAA|CMA|STC|CMC|RLC|RRC|RAL|RAR)$", "F", None),
    (r"(DSUB|RDEL)$", "FBB", None),
    (r"ARHL$", "FB", None),
    (r"(LDHI|LDSI) ", "FRB", None),
    (r"SHLX$", "FWW", None),
    (r"LHLX$", "FRR", None),
]

LETTER = {"MR": "R", "MW": "W", "IOR": "I", "IOW": "O", "BI": "B", "HALT": "H"}


def notation(cycles):
    out = []
    for cycle in cycles:
        if cycle.kind == "OF":
            out.append("S" if cycle.t_states == 6 else "F")
        else:
            out.append(LETTER[cycle.kind])
    return "".join(out)


def reference_for(op):
    text = disassemble_opcode(op, 0x12, 0x3412)
    for pattern, taken, not_taken in REFERENCE:
        if re.match(pattern, text):
            return text, taken, not_taken or taken
    raise AssertionError(f"no reference sequence for {op:02X}H {text}")


def random_cpu(rng, op, pc=0x4000):
    cpu = Processor8085()
    cpu.trace_bus = True
    cpu.memory = bytearray(rng.randbytes(0x10000))
    for reg in "ABCDEHL":
        cpu.registers[reg] = rng.randrange(256)
    cpu.registers["SP"] = rng.randrange(0x10000)
    cpu.registers["PC"] = pc
    cpu.set_flags_byte(rng.randrange(256))
    cpu.memory[pc] = op
    cpu.input_ports = bytearray(rng.randrange(256) for _ in range(256))
    return cpu


class MachineCycleSequences(unittest.TestCase):
    def test_every_opcode_matches_the_reference_and_its_t_states(self):
        rng = random.Random(8085)
        for op in range(256):
            text, ref_taken, ref_not_taken = reference_for(op)
            timing = INSTRUCTION_T_STATES[op]
            outcomes = set()
            for _ in range(64):
                cpu = random_cpu(rng, op)
                before = cpu.t_states
                cpu.step()
                spent = cpu.t_states - before
                cycles = cpu.bus_cycles
                with self.subTest(op=f"{op:02X}H", text=text):
                    self.assertEqual(sum(c.t_states for c in cycles), spent)
                    taken = spent == (timing[0] if isinstance(timing, tuple) else timing)
                    outcomes.add(taken)
                    self.assertEqual(notation(cycles), ref_taken if taken else ref_not_taken)
                    self.assertEqual(cycles[0].address, 0x4000)
                    self.assertEqual(cycles[0].data, op)
                if isinstance(timing, int) or len(outcomes) == 2:
                    break
            if isinstance(timing, tuple):
                self.assertEqual(outcomes, {True, False}, f"{op:02X}H: both paths not exercised")

    def test_bus_data_matches_memory_before_and_after(self):
        """Reads report the byte read before execution, writes the byte stored after it."""
        rng = random.Random(1)
        for op in range(256):
            for _ in range(8):
                cpu = random_cpu(rng, op)
                before = bytes(cpu.memory)
                cpu.step()
                for cycle in cpu.bus_cycles:
                    if cycle.kind in ("OF", "MR"):
                        self.assertEqual(cycle.data, before[cycle.address], f"{op:02X}H {cycle}")
                    elif cycle.kind == "MW":
                        self.assertEqual(cycle.data, cpu.memory[cycle.address], f"{op:02X}H {cycle}")
                    elif cycle.kind in ("IOR", "IOW"):
                        self.assertEqual(cycle.address >> 8, cycle.address & 0xFF)
                    elif cycle.kind == "BI":
                        self.assertIsNone(cycle.address)
                # Every changed memory byte was written by a write cycle
                written = {c.address for c in cpu.bus_cycles if c.kind == "MW"}
                changed = {a for a in range(0x10000) if before[a] != cpu.memory[a]} if op in (
                    0x02, 0x12, 0x22, 0x32, 0x34, 0x35, 0x36, 0x70, 0x77, 0xC5, 0xCD, 0xE3, 0xFF, 0xD9
                ) else set()
                self.assertTrue(changed <= written, f"{op:02X}H wrote {changed - written} without a cycle")


class SpecificInstructions(unittest.TestCase):
    def trace(self, source, steps):
        cpu = Processor8085()
        cpu.trace_bus = True
        cpu.load_program(assemble(source))
        for _ in range(steps):
            cpu.step()
        return cpu, cpu.bus_cycles

    def test_lda(self):
        cpu, cycles = self.trace("ORG 2000H\nLDA 2050H\nHLT\nORG 2050H\nDB 9AH\nEND 2000H", 1)
        self.assertEqual([(c.kind, c.t_states, c.address, c.data) for c in cycles], [
            ("OF", 4, 0x2000, 0x3A), ("MR", 3, 0x2001, 0x50), ("MR", 3, 0x2002, 0x20), ("MR", 3, 0x2050, 0x9A),
        ])

    def test_sta_and_out(self):
        cpu, cycles = self.trace("ORG 2000H\nMVI A, 5AH\nSTA 3000H\nOUT 42H\nHLT\nEND 2000H", 2)
        self.assertEqual([(c.kind, c.address, c.data) for c in cycles][-1], ("MW", 0x3000, 0x5A))
        cpu.step()
        self.assertEqual([(c.kind, c.address, c.data) for c in cpu.bus_cycles], [
            ("OF", 0x2005, 0xD3), ("MR", 0x2006, 0x42), ("IOW", 0x4242, 0x5A),
        ])

    def test_in_reads_the_input_latch(self):
        cpu = Processor8085()
        cpu.trace_bus = True
        cpu.load_program(assemble("IN 07H\nHLT"))
        cpu.input_ports[7] = 0xC3
        cpu.step()
        self.assertEqual((cpu.bus_cycles[-1].kind, cpu.bus_cycles[-1].address, cpu.bus_cycles[-1].data),
                         ("IOR", 0x0707, 0xC3))

    def test_call_push_and_xthl_stack_order(self):
        source = "ORG 2000H\nLXI SP, 4000H\nLXI B, 1234H\nPUSH B\nCALL SBR\nHLT\nSBR: XTHL\nRET\nEND 2000H"
        cpu, cycles = self.trace(source, 3)  # PUSH B
        self.assertEqual([(c.kind, c.t_states, c.address, c.data) for c in cycles], [
            ("OF", 6, 0x2006, 0xC5), ("MW", 3, 0x3FFF, 0x12), ("MW", 3, 0x3FFE, 0x34),
        ])
        cpu.step()  # CALL SBR (SBR = 200BH, return address 200AH)
        self.assertEqual([(c.kind, c.address, c.data) for c in cpu.bus_cycles], [
            ("OF", 0x2007, 0xCD), ("MR", 0x2008, 0x0B), ("MR", 0x2009, 0x20),
            ("MW", 0x3FFD, 0x20), ("MW", 0x3FFC, 0x0A),
        ])
        cpu.registers["H"], cpu.registers["L"] = 0xAB, 0xCD
        cpu.step()  # XTHL: read SP, SP+1, write H to SP+1, L to SP
        self.assertEqual([(c.kind, c.address, c.data) for c in cpu.bus_cycles], [
            ("OF", 0x200B, 0xE3), ("MR", 0x3FFC, 0x0A), ("MR", 0x3FFD, 0x20),
            ("MW", 0x3FFD, 0xAB), ("MW", 0x3FFC, 0xCD),
        ])

    def test_conditional_jump_not_taken_skips_the_high_byte(self):
        cpu, cycles = self.trace("ORG 2000H\nXRA A\nJNZ 3000H\nHLT\nEND 2000H", 2)
        self.assertEqual([(c.kind, c.address) for c in cycles], [("OF", 0x2001), ("MR", 0x2002)])

    def test_dad_bus_idle(self):
        cpu, cycles = self.trace("DAD B\nHLT", 1)
        self.assertEqual([(c.kind, c.t_states, c.address) for c in cycles],
                         [("OF", 4, 0), ("BI", 3, None), ("BI", 3, None)])

    def test_hlt_and_halt_state(self):
        cpu, cycles = self.trace("NOP\nHLT", 2)
        self.assertEqual([(c.kind, c.t_states) for c in cycles], [("OF", 4), ("HALT", 1)])
        cpu.step()  # stays halted: no machine cycles
        self.assertEqual(cpu.bus_cycles, [])

    def test_tracing_off_records_nothing(self):
        cpu = Processor8085()
        cpu.load_program(assemble("NOP\nHLT"))
        cpu.step()
        self.assertIsNone(cpu.bus_cycles)


class InterruptAcknowledge(unittest.TestCase):
    SOURCE = "ORG 2000H\nLXI SP, 4000H\nEI\nNOP\nNOP\nHLT\nEND 2000H"

    def cpu(self):
        cpu = Processor8085()
        cpu.trace_bus = True
        cpu.load_program(assemble(self.SOURCE))
        for _ in range(3):  # LXI, EI, NOP (EI delay)
            cpu.step()
        return cpu

    def test_trap_and_rst_x5(self):
        for pin, vector in (("TRAP", 0x24), ("RST7.5", 0x3C), ("RST6.5", 0x34), ("RST5.5", 0x2C)):
            cpu = self.cpu()
            cpu.interrupt_masks = 0
            cpu.set_pin(pin, 1)
            before = cpu.t_states
            cpu.step()
            self.assertEqual(cpu.last_interrupt, pin)
            self.assertEqual([(c.kind, c.t_states, c.address, c.data) for c in cpu.bus_cycles], [
                ("BIA", 6, 0x2005, None), ("MW", 3, 0x3FFF, 0x20), ("MW", 3, 0x3FFE, 0x05),
            ])
            self.assertEqual(cpu.t_states - before, 12)
            self.assertEqual(cpu.registers["PC"], vector)

    def test_intr_with_rst(self):
        cpu = self.cpu()
        cpu.set_intr_instruction((0xEF,))  # RST 5
        cpu.set_pin("INTR", 1)
        cpu.step()
        self.assertEqual([(c.kind, c.t_states, c.address, c.data) for c in cpu.bus_cycles], [
            ("INA", 6, 0x2005, 0xEF), ("MW", 3, 0x3FFF, 0x20), ("MW", 3, 0x3FFE, 0x05),
        ])

    def test_intr_with_call(self):
        cpu = self.cpu()
        cpu.set_intr_instruction((0xCD, 0x00, 0x30))
        cpu.set_pin("INTR", 1)
        before = cpu.t_states
        cpu.step()
        cycles = cpu.bus_cycles
        self.assertEqual([(c.kind, c.t_states, c.address, c.data) for c in cycles], [
            ("INA", 6, 0x2005, 0xCD), ("INA", 3, 0x2005, 0x00), ("INA", 3, 0x2005, 0x30),
            ("MW", 3, 0x3FFF, 0x20), ("MW", 3, 0x3FFE, 0x05),
        ])
        self.assertEqual(sum(c.t_states for c in cycles), cpu.t_states - before)


class TracingDoesNotChangeExecution(unittest.TestCase):
    def test_random_programs_with_interrupts(self):
        from processor import INTERRUPT_PINS
        rng = random.Random(2026)
        for _ in range(40):
            memory = rng.randbytes(0x10000)
            plain, traced = Processor8085(), Processor8085()
            traced.trace_bus = True
            for cpu in (plain, traced):
                cpu.memory = bytearray(memory)
                cpu.registers["SP"] = 0xF000
                cpu.input_ports = bytearray(range(256))
            for _ in range(400):
                if rng.random() < 0.02:
                    pin, level = rng.choice(INTERRUPT_PINS), rng.randrange(2)
                    for cpu in (plain, traced):
                        cpu.set_pin(pin, level)
                before = traced.t_states
                status = plain.step()
                self.assertEqual(traced.step(), status)
                spent = traced.t_states - before
                self.assertEqual(sum(c.t_states for c in traced.bus_cycles), spent)
                if status == "HALT":
                    for cpu in (plain, traced):
                        cpu.idle(10)
                self.assertEqual(plain.registers, traced.registers)
                self.assertEqual(plain.flags, traced.flags)
                self.assertEqual(plain.t_states, traced.t_states)
            self.assertEqual(plain.memory, traced.memory)


class Waveforms(unittest.TestCase):
    """Bus signal levels per T-state, per the 8085AH data sheet (Tables 3 and 4)."""

    def all_cycles(self):
        rng = random.Random(5)
        for op in range(256):
            cpu = random_cpu(rng, op)
            cpu.step()
            yield op, cpu.bus_cycles

    def test_status_lines_and_strobes(self):
        for op, cycles in self.all_cycles():
            states = waveform(cycles)
            self.assertEqual(len(states), sum(c.t_states for c in cycles))
            for index, label, signals in states:
                cycle = cycles[index]
                self.assertEqual(set(signals), set(SIGNALS) - {"CLK"})
                io_m, s1, s0 = cycle.status
                # Status is valid for the whole machine cycle
                self.assertEqual(signals["S1"], (s1, s1))
                self.assertEqual(signals["S0"], (s0, s0))
                self.assertEqual(signals["IO/M"], ("Z", "Z") if io_m is None else (io_m, io_m))
                # ALE only in T1 (also T1 of the HALT cycle), never in the bus idle cycles of DAD
                if label == "T1" and cycle.kind != "BI":
                    self.assertEqual(signals["ALE"], (1, 0))
                else:
                    self.assertEqual(signals["ALE"], (0, 0))
                # Exactly the machine cycle's strobe is active, only in T2 and T3
                for line in ("RD", "WR", "INTA"):
                    if cycle.kind == "HALT":
                        expected = ("Z", "Z") if line != "INTA" else (1, 1)
                    elif line == cycle.strobe and label in ("T2", "T3"):
                        expected = (0, 0)
                    else:
                        expected = (1, 1)
                    self.assertEqual(signals[line], expected, f"{op:02X}H {cycle} {label} {line}")
                # T4-T6: address/data bus floats
                if label in ("T4", "T5", "T6"):
                    self.assertEqual(signals["AD7-AD0"], ("Z", "Z"))
                if label == "T1" and cycle.address is not None:
                    self.assertEqual(signals["AD7-AD0"][0], ("A", cycle.address & 0xFF))
                    self.assertEqual(signals["A15-A8"][0], ("A", cycle.address >> 8))

    def test_status_codes_match_the_data_sheet(self):
        expected = {
            "OF": (0, 1, 1), "MR": (0, 1, 0), "MW": (0, 0, 1), "IOR": (1, 1, 0), "IOW": (1, 0, 1),
            "INA": (1, 1, 1), "BI": (0, 1, 0), "BIA": (1, 1, 1), "HALT": (None, 0, 0),
        }
        self.assertEqual({k: v[2:5] for k, v in CYCLE_TYPES.items()}, expected)


if __name__ == "__main__":
    unittest.main()
