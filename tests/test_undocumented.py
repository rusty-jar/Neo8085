"""
The 10 undocumented 8085 instructions: DSUB, ARHL, RDEL, LDHI, LDSI, RSTV, SHLX,
JNK, LHLX and JK. Expected behaviour follows the register transfers published
by Dehnhardt & Sorensen (1979); the flag effects follow the die analyses by
Ken Shirriff and Pavel Zima where they are more specific (ARHL clears V).
"""

import random
import unittest

from helpers import Processor8085, assemble, pair, run


def execute(source, setup=None, steps=None):
    cpu = Processor8085()
    cpu.load_program(assemble(source))
    if setup:
        setup(cpu)
    count = 0
    while (steps is None or count < steps) and cpu.step() == "OK":
        count += 1
    return cpu


class UndocumentedInstructionTests(unittest.TestCase):
    def test_dsub(self):
        cpu = execute("LXI H, 1234H\nLXI B, 0234H\nDSUB\nHLT")
        self.assertEqual((pair(cpu, "HL"), cpu.flags["C"], cpu.flags["Z"]), (0x1000, 0, 0))
        cpu = execute("LXI H, 0000H\nLXI B, 0001H\nDSUB\nHLT")
        self.assertEqual((pair(cpu, "HL"), cpu.flags["C"], cpu.flags["S"]), (0xFFFF, 1, 1))
        # Z reflects the whole 16-bit result
        cpu = execute("LXI H, 0100H\nLXI B, 0000H\nDSUB\nHLT")
        self.assertEqual((pair(cpu, "HL"), cpu.flags["Z"]), (0x0100, 0))
        cpu = execute("LXI H, 0ABCDH\nLXI B, 0ABCDH\nDSUB\nHLT")
        self.assertEqual((pair(cpu, "HL"), cpu.flags["Z"], cpu.flags["C"]), (0, 1, 0))

    def test_dsub_matches_16_bit_arithmetic(self):
        rng = random.Random(8085)
        cpu = Processor8085()
        cpu.memory[0] = 0x08
        for _ in range(20000):
            hl, bc = rng.randrange(0x10000), rng.randrange(0x10000)
            cpu.registers.update(H=hl >> 8, L=hl & 0xFF, B=bc >> 8, C=bc & 0xFF, PC=0)
            cpu.step()
            result = (hl - bc) & 0xFFFF
            signed = (hl - (hl & 0x8000) * 2) - (bc - (bc & 0x8000) * 2)
            self.assertEqual(pair(cpu, "HL"), result)
            self.assertEqual(cpu.flags["C"], 1 if hl < bc else 0)
            self.assertEqual(cpu.flags["Z"], 1 if result == 0 else 0)
            self.assertEqual(cpu.flags["S"], result >> 15)
            self.assertEqual(cpu.flags["V"], 0 if -32768 <= signed <= 32767 else 1)
            self.assertEqual(cpu.flags["K"], cpu.flags["V"] ^ cpu.flags["S"])
        self.assertEqual(cpu.t_states, 20000 * 10)

    def test_arhl(self):
        # H7 is duplicated, L0 goes to CY, V is cleared, the rest unchanged
        cpu = execute("XRA A\nLXI H, 8001H\nARHL\nHLT")
        self.assertEqual((pair(cpu, "HL"), cpu.flags["C"], cpu.flags["Z"]), (0xC000, 1, 1))
        cpu = execute("MVI A, 7FH\nADI 1\nLXI H, 0003H\nARHL\nHLT")  # 7F+1 sets V and S (K = 0)
        self.assertEqual((cpu.flags["V"], cpu.flags["S"], cpu.flags["K"], cpu.flags["C"]), (0, 1, 0, 1))
        cpu = execute("STC\nLXI H, 4002H\nARHL\nHLT")
        self.assertEqual((pair(cpu, "HL"), cpu.flags["C"]), (0x2001, 0))
        cpu = execute("LXI H, 0100H\nARHL\nHLT")
        self.assertEqual(pair(cpu, "HL"), 0x0080)  # H0 moves into L7

    def test_rdel(self):
        # CY <- D7, DE shifted left, E0 <- old CY; V is affected
        cpu = execute("STC\nLXI D, 8001H\nRDEL\nHLT")
        self.assertEqual((pair(cpu, "DE"), cpu.flags["C"], cpu.flags["V"]), (0x0003, 1, 1))
        cpu = execute("STC\nCMC\nLXI D, 4080H\nRDEL\nHLT")
        self.assertEqual((pair(cpu, "DE"), cpu.flags["C"], cpu.flags["V"]), (0x8100, 0, 1))
        cpu = execute("STC\nCMC\nLXI D, 0C000H\nRDEL\nHLT")
        self.assertEqual((pair(cpu, "DE"), cpu.flags["C"], cpu.flags["V"]), (0x8000, 1, 0))

    def test_ldhi_ldsi_add_unsigned_offset(self):
        cpu = execute("XRA A\nLXI H, 12FEH\nLDHI 5\nHLT")
        self.assertEqual((pair(cpu, "DE"), cpu.flags["Z"], cpu.flags["C"]), (0x1303, 1, 0))  # flags untouched
        cpu = execute("LXI H, 0001H\nLDHI 0FFH\nHLT")
        self.assertEqual(pair(cpu, "DE"), 0x0100)
        cpu = execute("LXI SP, 0FFF0H\nLDSI 20H\nHLT")
        self.assertEqual(pair(cpu, "DE"), 0x0010)  # wraps at 16 bits

    def test_shlx_lhlx(self):
        cpu = execute("LXI D, 3000H\nLXI H, 0BEEFH\nSHLX\nHLT")
        self.assertEqual((cpu.memory[0x3000], cpu.memory[0x3001]), (0xEF, 0xBE))
        cpu = execute("LXI H, 1234H\nSHLD 4000H\nLXI H, 0\nLXI D, 4000H\nLHLX\nHLT")
        self.assertEqual(pair(cpu, "HL"), 0x1234)

    def test_rstv(self):
        source = "ORG 0040H\nMVI C, 99H\nHLT\nORG 2000H\nLXI SP, 4000H\nMVI A, 7FH\nADI 1\nRSTV\nMVI C, 1\nHLT"
        cpu = Processor8085()
        cpu.load_program(assemble(source))
        cpu.registers["PC"] = 0x2000
        while cpu.step() == "OK":
            pass
        self.assertEqual(cpu.registers["C"], 0x99)  # V=1: restart at 0040H
        self.assertEqual(cpu.memory[0x3FFE] | (cpu.memory[0x3FFF] << 8), 0x2008)
        source = source.replace("MVI A, 7FH\nADI 1", "MVI A, 1\nADI 1")
        cpu = Processor8085()
        cpu.load_program(assemble(source))
        cpu.registers["PC"] = 0x2000
        while cpu.step() == "OK":
            pass
        self.assertEqual(cpu.registers["C"], 1)  # V=0: continue

    def test_jk_jnk(self):
        # K after CMP: 1 when A < operand as signed numbers
        cpu = execute("MVI A, 0FEH\nCPI 1\nJK LESS\nMVI B, 0\nHLT\nLESS: MVI B, 1\nHLT")
        self.assertEqual(cpu.registers["B"], 1)
        cpu = execute("MVI A, 5\nCPI 1\nJNK NOT_LESS\nMVI B, 0\nHLT\nNOT_LESS: MVI B, 2\nHLT")
        self.assertEqual(cpu.registers["B"], 2)

    def test_dcx_jnk_counting_loop(self):
        # Classic use of K: loop until the 16-bit counter underflows (0000H -> FFFFH)
        cpu = execute("LXI B, 3\nMVI D, 0\nLOOP: INR D\nDCX B\nJNK LOOP\nHLT")
        self.assertEqual((cpu.registers["D"], pair(cpu, "BC")), (4, 0xFFFF))

    def test_timing(self):
        cases = {
            "DSUB": 10, "ARHL": 7, "RDEL": 10, "LDHI 1": 10, "LDSI 1": 10,
            "SHLX": 10, "LHLX": 10, "JNK 0": 10, "JK 0": 7,
        }
        for source, t_states in cases.items():
            with self.subTest(source=source):
                cpu = execute(source, steps=1)
                self.assertEqual(cpu.t_states, t_states)
        self.assertEqual(execute("RSTV", steps=1).t_states, 6)
        self.assertEqual(execute("MVI A, 7FH\nADI 1\nRSTV", steps=3).t_states, 7 + 7 + 12)


class UndocumentedAssemblerTests(unittest.TestCase):
    def test_encoding_and_aliases(self):
        out = assemble(
            "DSUB\nARHL\nRDEL\nLDHI 10H\nLDSI 20H\nRSTV\nSHLX\nJNK 1234H\nLHLX\nJK 5678H\nJNX5 1\nJX5 2"
        )
        expected = [
            0x08, 0x10, 0x18, 0x28, 0x10, 0x38, 0x20, 0xCB, 0xD9,
            0xDD, 0x34, 0x12, 0xED, 0xFD, 0x78, 0x56, 0xDD, 1, 0, 0xFD, 2, 0,
        ]
        self.assertEqual(list(out.memory[: len(expected)]), expected)

    def test_offset_range(self):
        for source in ("LDHI 256", "LDSI -1"):
            with self.subTest(source=source):
                with self.assertRaises(SyntaxError):
                    assemble(source)

    def test_programs_run(self):
        cpu, status = run("LXI H, 9000H\nLXI B, 1000H\nDSUB\nARHL\nHLT")
        self.assertEqual((status, pair(cpu, "HL")), ("HALT", 0xC000))


if __name__ == "__main__":
    unittest.main()
