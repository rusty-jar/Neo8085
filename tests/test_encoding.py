"""
Opcode encoding, instruction length, disassembly and T-state timing for all
246 documented 8085 opcodes, checked against a hand-written opcode map.
"""

import unittest

from helpers import Processor8085, assemble
from processor import INSTRUCTION_SIZES, UNDOCUMENTED_OPCODES, disassemble_opcode

REGS = "BCDEHLMA"

# The documented 8085 opcode map (MOV and register ALU groups added below).
OPCODE_MAP = {
    "NOP": 0x00, "LXI B,1234H": 0x01, "STAX B": 0x02, "INX B": 0x03, "INR B": 0x04,
    "DCR B": 0x05, "MVI B,12H": 0x06, "RLC": 0x07, "DAD B": 0x09, "LDAX B": 0x0A,
    "DCX B": 0x0B, "INR C": 0x0C, "DCR C": 0x0D, "MVI C,12H": 0x0E, "RRC": 0x0F,
    "LXI D,1234H": 0x11, "STAX D": 0x12, "INX D": 0x13, "INR D": 0x14, "DCR D": 0x15,
    "MVI D,12H": 0x16, "RAL": 0x17, "DAD D": 0x19, "LDAX D": 0x1A, "DCX D": 0x1B,
    "INR E": 0x1C, "DCR E": 0x1D, "MVI E,12H": 0x1E, "RAR": 0x1F,
    "RIM": 0x20, "LXI H,1234H": 0x21, "SHLD 1234H": 0x22, "INX H": 0x23, "INR H": 0x24,
    "DCR H": 0x25, "MVI H,12H": 0x26, "DAA": 0x27, "DAD H": 0x29, "LHLD 1234H": 0x2A,
    "DCX H": 0x2B, "INR L": 0x2C, "DCR L": 0x2D, "MVI L,12H": 0x2E, "CMA": 0x2F,
    "SIM": 0x30, "LXI SP,1234H": 0x31, "STA 1234H": 0x32, "INX SP": 0x33, "INR M": 0x34,
    "DCR M": 0x35, "MVI M,12H": 0x36, "STC": 0x37, "DAD SP": 0x39, "LDA 1234H": 0x3A,
    "DCX SP": 0x3B, "INR A": 0x3C, "DCR A": 0x3D, "MVI A,12H": 0x3E, "CMC": 0x3F,
    "HLT": 0x76,
    "RNZ": 0xC0, "POP B": 0xC1, "JNZ 1234H": 0xC2, "JMP 1234H": 0xC3, "CNZ 1234H": 0xC4,
    "PUSH B": 0xC5, "ADI 12H": 0xC6, "RST 0": 0xC7, "RZ": 0xC8, "RET": 0xC9,
    "JZ 1234H": 0xCA, "CZ 1234H": 0xCC, "CALL 1234H": 0xCD, "ACI 12H": 0xCE, "RST 1": 0xCF,
    "RNC": 0xD0, "POP D": 0xD1, "JNC 1234H": 0xD2, "OUT 12H": 0xD3, "CNC 1234H": 0xD4,
    "PUSH D": 0xD5, "SUI 12H": 0xD6, "RST 2": 0xD7, "RC": 0xD8, "JC 1234H": 0xDA,
    "IN 12H": 0xDB, "CC 1234H": 0xDC, "SBI 12H": 0xDE, "RST 3": 0xDF,
    "RPO": 0xE0, "POP H": 0xE1, "JPO 1234H": 0xE2, "XTHL": 0xE3, "CPO 1234H": 0xE4,
    "PUSH H": 0xE5, "ANI 12H": 0xE6, "RST 4": 0xE7, "RPE": 0xE8, "PCHL": 0xE9,
    "JPE 1234H": 0xEA, "XCHG": 0xEB, "CPE 1234H": 0xEC, "XRI 12H": 0xEE, "RST 5": 0xEF,
    "RP": 0xF0, "POP PSW": 0xF1, "JP 1234H": 0xF2, "DI": 0xF3, "CP 1234H": 0xF4,
    "PUSH PSW": 0xF5, "ORI 12H": 0xF6, "RST 6": 0xF7, "RM": 0xF8, "SPHL": 0xF9,
    "JM 1234H": 0xFA, "EI": 0xFB, "CM 1234H": 0xFC, "CPI 12H": 0xFE, "RST 7": 0xFF,
    # Undocumented 8085 instructions
    "DSUB": 0x08, "ARHL": 0x10, "RDEL": 0x18, "LDHI 12H": 0x28, "LDSI 12H": 0x38,
    "RSTV": 0xCB, "SHLX": 0xD9, "JNK 1234H": 0xDD, "LHLX": 0xED, "JK 1234H": 0xFD,
}
for _d, _dst in enumerate(REGS):
    for _s, _src in enumerate(REGS):
        if not (_dst == "M" and _src == "M"):
            OPCODE_MAP[f"MOV {_dst},{_src}"] = 0x40 + _d * 8 + _s
for _o, _name in enumerate(("ADD", "ADC", "SUB", "SBB", "ANA", "XRA", "ORA", "CMP")):
    for _s, _src in enumerate(REGS):
        OPCODE_MAP[f"{_name} {_src}"] = 0x80 + _o * 8 + _s


def operand_bytes(text):
    if text.endswith("1234H"):
        return [0x34, 0x12]
    if text.endswith("12H"):
        return [0x12]
    return []


# 8085 T-states: (taken, not taken) for conditional instructions
def expected_t_states(text):
    mnemonic = text.split()[0]
    operands = text[len(mnemonic):].replace(" ", "").split(",")
    uses_m = "M" in operands
    table = {
        "MOV": 7 if uses_m else 4, "MVI": 10 if uses_m else 7, "LXI": 10,
        "LDA": 13, "STA": 13, "LHLD": 16, "SHLD": 16, "LDAX": 7, "STAX": 7, "XCHG": 4,
        "INR": 10 if uses_m else 4, "DCR": 10 if uses_m else 4, "INX": 6, "DCX": 6,
        "DAD": 10, "DAA": 4, "CMA": 4, "STC": 4, "CMC": 4,
        "RLC": 4, "RRC": 4, "RAL": 4, "RAR": 4,
        "JMP": 10, "CALL": 18, "RET": 10, "RST": 12, "PCHL": 6, "SPHL": 6, "XTHL": 16,
        "PUSH": 12, "POP": 10, "IN": 10, "OUT": 10,
        "EI": 4, "DI": 4, "NOP": 4, "HLT": 5, "RIM": 4, "SIM": 4,
        # Undocumented instructions
        "DSUB": 10, "ARHL": 7, "RDEL": 10, "LDHI": 10, "LDSI": 10, "SHLX": 10, "LHLX": 10,
        "RSTV": (12, 6), "JNK": (10, 7), "JK": (10, 7),
    }
    for alu in ("ADD", "ADC", "SUB", "SBB", "ANA", "XRA", "ORA", "CMP"):
        table[alu] = 7 if uses_m else 4
    for imm in ("ADI", "ACI", "SUI", "SBI", "ANI", "XRI", "ORI", "CPI"):
        table[imm] = 7
    for cc in ("NZ", "Z", "NC", "C", "PO", "PE", "P", "M"):
        table["J" + cc] = (10, 7)
        table["C" + cc] = (18, 9)
        table["R" + cc] = (12, 6)
    return table[mnemonic]


class OpcodeMapTests(unittest.TestCase):
    def test_map_covers_every_opcode(self):
        self.assertEqual(len(OPCODE_MAP), 256)
        self.assertEqual(set(OPCODE_MAP.values()), set(range(256)))
        self.assertEqual(len(UNDOCUMENTED_OPCODES), 10)

    def test_assembler_encoding(self):
        for text, opcode in OPCODE_MAP.items():
            with self.subTest(text=text):
                out = assemble(text)
                expected = [opcode] + operand_bytes(text)
                self.assertEqual(list(out.memory[: len(expected)]), expected)
                self.assertEqual(out.program_end_address, len(expected))

    def test_assembler_accepts_spaces_after_commas(self):
        for text, opcode in OPCODE_MAP.items():
            if "," in text:
                with self.subTest(text=text):
                    self.assertEqual(assemble(text.replace(",", ", ")).memory[0], opcode)
                    self.assertEqual(assemble(text.replace(",", " ,  ")).memory[0], opcode)

    def test_instruction_sizes(self):
        for text, opcode in OPCODE_MAP.items():
            with self.subTest(text=text):
                self.assertEqual(INSTRUCTION_SIZES[opcode], 1 + len(operand_bytes(text)))

    def test_disassembler(self):
        for text, opcode in OPCODE_MAP.items():
            with self.subTest(text=text):
                self.assertEqual(disassemble_opcode(opcode, 0x12, 0x1234).replace(", ", ","), text)

    def test_disassembly_reassembles_to_same_bytes(self):
        cpu = Processor8085()
        for opcode in OPCODE_MAP.values():
            for b1, b2 in ((0x00, 0x00), (0xAB, 0xCD), (0xFF, 0xFF)):
                cpu.memory[0:3] = bytes([opcode, b1, b2])
                text, size = cpu.disassemble(0)
                with self.subTest(text=text):
                    self.assertEqual(list(assemble(text).memory[:size]), [opcode, b1, b2][:size])

    def test_pc_advances_by_instruction_length(self):
        for text, opcode in OPCODE_MAP.items():
            mnemonic = text.split()[0]
            if mnemonic in ("HLT", "JMP", "CALL", "RET", "PCHL") or mnemonic.startswith("RST"):
                continue
            if mnemonic[0] in "JCR" and mnemonic not in ("RLC", "RRC", "RAL", "RAR", "RIM", "RDEL", "CMA", "CMC", "CMP", "CPI"):
                continue  # conditional branches tested separately
            with self.subTest(text=text):
                cpu = Processor8085()
                cpu.memory[0x100:0x103] = bytes([opcode] + operand_bytes(text) + [0] * (2 - len(operand_bytes(text))))
                cpu.registers["PC"] = 0x100
                self.assertEqual(cpu.step(), "OK", cpu.error)
                self.assertEqual(cpu.registers["PC"], 0x100 + INSTRUCTION_SIZES[opcode])


class TimingTests(unittest.TestCase):
    def test_t_states_for_every_opcode(self):
        for text, opcode in OPCODE_MAP.items():
            expected = expected_t_states(text)
            outcomes = (True, False) if isinstance(expected, tuple) else (None,)
            for taken in outcomes:
                with self.subTest(text=text, taken=taken):
                    cpu = Processor8085()
                    cpu.registers["SP"] = 0x8000
                    cpu.memory[0:3] = bytes([opcode, 0x34, 0x12])
                    if taken is not None:
                        # Make the condition true or false
                        if opcode == 0xCB:  # RSTV: V set
                            cpu.flags["V"] = 1 if taken else 0
                        elif opcode in (0xDD, 0xFD):  # JNK: K=0, JK: K=1
                            want = 1 if opcode == 0xFD else 0
                            cpu.flags["K"] = want if taken else 1 - want
                        else:
                            cc = (opcode >> 3) & 7
                            flag = ("Z", "C", "P", "S")[cc >> 1]
                            cpu.flags[flag] = (cc & 1) if taken else 1 - (cc & 1)
                    cpu.step()
                    want = expected if taken is None else expected[0 if taken else 1]
                    self.assertEqual(cpu.t_states, want)

    def test_peek_predicts_every_step(self):
        import random

        rng = random.Random(85)
        for opcode in range(256):
            for _ in range(8):
                with self.subTest(opcode=hex(opcode)):
                    cpu = Processor8085()
                    cpu.registers["SP"] = 0x8000
                    cpu.memory[0x100:0x103] = bytes([opcode, rng.randrange(256), rng.randrange(256)])
                    cpu.registers["PC"] = 0x100
                    for flag in cpu.flags:
                        cpu.flags[flag] = rng.randrange(2)
                    predicted = cpu.peek_t_states()
                    cpu.step()
                    self.assertEqual(cpu.t_states, predicted)

    def test_peek_interrupts_and_halt(self):
        cpu = Processor8085()
        cpu.memory[0] = 0x76
        cpu.step()
        self.assertIsNone(cpu.peek_t_states())  # halted, nothing pending
        cpu.set_pin("TRAP", 1)
        self.assertEqual(cpu.peek_t_states(), 12)
        cpu.step()
        self.assertEqual(cpu.t_states, 5 + 12)
        cpu = Processor8085()
        cpu.interrupt_enable = 1
        cpu.set_intr_instruction([0xCD, 0, 0x20])
        cpu.set_pin("INTR", 1)
        self.assertEqual(cpu.peek_t_states(), 18)

    def test_idle_only_counts_while_halted(self):
        cpu = Processor8085()
        cpu.idle(100)
        self.assertEqual(cpu.t_states, 0)  # running: idle() has no effect
        cpu.memory[0] = 0x76
        cpu.step()
        cpu.idle(100)
        self.assertEqual(cpu.t_states, 105)

    def test_t_states_accumulate(self):
        cpu = Processor8085()
        cpu.load_program(assemble("MVI B, 3\nLOOP: DCR B\nJNZ LOOP\nHLT"))
        while cpu.step() == "OK":
            pass
        # MVI(7) + 3*DCR(4) + 2*JNZ taken(10) + 1*JNZ not taken(7) + HLT(5)
        self.assertEqual(cpu.t_states, 7 + 12 + 20 + 7 + 5)


if __name__ == "__main__":
    unittest.main()
