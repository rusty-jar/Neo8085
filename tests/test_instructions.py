"""
Behavioural tests for every documented 8085 instruction.

Expected values come from the Intel 8080/8085 Assembly Language Programming
Manual and from independent reference models in helpers.py (a bit-level
ripple-carry adder and plain decimal arithmetic for DAA).
"""

import unittest

from helpers import Processor8085, assemble, pair, parity_even, reference_alu, ripple_add, run

STACK = "LXI SP, 4000H\n"


class InstructionTestCase(unittest.TestCase):
    def check(self, source, expected, status="HALT"):
        cpu, result = run(source)
        self.assertEqual(result, status, f"status ({cpu.error})")
        for key, want in expected.items():
            if key in ("BC", "DE", "HL"):
                got = pair(cpu, key)
            elif key in ("S", "Z", "AC", "P", "CY"):
                got = cpu.flags["C" if key == "CY" else key]
            elif key.startswith("M["):
                got = cpu.memory[int(key[2:-1], 16)]
            else:
                got = cpu.registers[key]
            self.assertEqual(got, want, f"{key}: got {got:X}H, want {want:X}H")
        return cpu


class DataTransferTests(InstructionTestCase):
    def test_mov_register_to_register(self):
        self.check("MVI B, 12H\nMOV A, B\nHLT", {"A": 0x12})

    def test_mov_all_register_combinations(self):
        regs = "BCDEHLA"
        for dst in regs:
            for src in regs:
                with self.subTest(dst=dst, src=src):
                    src_init = "".join(f"MVI {r}, {0x10 + i:X}H\n" for i, r in enumerate(regs))
                    cpu, _ = run(src_init + f"MOV {dst}, {src}\nHLT")
                    self.assertEqual(cpu.registers[dst], 0x10 + regs.index(src))

    def test_mov_memory(self):
        self.check("LXI H, 3000H\nMVI A, 5AH\nMOV M, A\nMOV C, M\nHLT", {"M[3000]": 0x5A, "C": 0x5A})

    def test_mvi_memory(self):
        self.check("LXI H, 3000H\nMVI M, 77H\nHLT", {"M[3000]": 0x77})

    def test_lxi_all_pairs(self):
        self.check(
            "LXI B, 1234H\nLXI D, 5678H\nLXI H, 9ABCH\nLXI SP, 0DEF0H\nHLT",
            {"BC": 0x1234, "DE": 0x5678, "HL": 0x9ABC, "SP": 0xDEF0},
        )

    def test_sta_lda(self):
        self.check("MVI A, 3CH\nSTA 3000H\nMVI A, 0\nLDA 3000H\nHLT", {"A": 0x3C, "M[3000]": 0x3C})

    def test_shld_stores_l_then_h(self):
        self.check("LXI H, 1234H\nSHLD 3000H\nHLT", {"M[3000]": 0x34, "M[3001]": 0x12})

    def test_lhld(self):
        self.check("LXI H, 1234H\nSHLD 3000H\nLXI H, 0\nLHLD 3000H\nHLT", {"HL": 0x1234})

    def test_stax_ldax(self):
        self.check(
            "LXI B, 3000H\nLXI D, 3001H\nMVI A, 11H\nSTAX B\nMVI A, 22H\nSTAX D\nLDAX B\nHLT",
            {"A": 0x11, "M[3001]": 0x22},
        )
        self.check("LXI D, 3001H\nLXI H, 3001H\nMVI M, 99H\nLDAX D\nHLT", {"A": 0x99})

    def test_xchg(self):
        self.check("LXI H, 1111H\nLXI D, 2233H\nXCHG\nHLT", {"HL": 0x2233, "DE": 0x1111})

    def test_data_transfer_affects_no_flags(self):
        cpu = self.check(
            "STC\nXRA A\nSTC\nMVI B, 0FFH\nMOV A, B\nLXI H, 0\nLDA 0\nXCHG\nLHLD 0\nHLT",
            {"Z": 1, "CY": 1, "P": 1, "S": 0},
        )
        self.assertEqual(cpu.flags["AC"], 0)


class ArithmeticTests(InstructionTestCase):
    def test_add_sets_all_flags(self):
        self.check("MVI A, 3AH\nMVI B, 0C6H\nADD B\nHLT", {"A": 0, "CY": 1, "Z": 1, "AC": 1, "P": 1, "S": 0})
        self.check("MVI A, 7FH\nMVI B, 1\nADD B\nHLT", {"A": 0x80, "S": 1, "Z": 0, "AC": 1, "P": 0, "CY": 0})

    def test_add_memory_and_immediate(self):
        self.check("LXI H, 3000H\nMVI M, 5\nMVI A, 3\nADD M\nHLT", {"A": 8})
        self.check("MVI A, 0F0H\nADI 20H\nHLT", {"A": 0x10, "CY": 1})

    def test_adc_aci(self):
        self.check("STC\nMVI A, 10H\nMVI B, 20H\nADC B\nHLT", {"A": 0x31, "CY": 0, "P": 0})
        self.check("STC\nMVI A, 0FH\nMVI B, 0\nADC B\nHLT", {"A": 0x10, "AC": 1})
        self.check("STC\nMVI A, 0FFH\nACI 0\nHLT", {"A": 0, "CY": 1, "Z": 1, "AC": 1})

    def test_sub_intel_manual_example(self):
        # Intel 8080/8085 Assembly Language Programming Manual, SUB A with A=3EH:
        # 3EH + C2H (two's complement) = 00H; CY=0, S=0, Z=1, P=1, AC=1
        self.check("MVI A, 3EH\nSUB A\nHLT", {"A": 0, "CY": 0, "S": 0, "Z": 1, "P": 1, "AC": 1})

    def test_sub_borrow_and_aux_carry(self):
        # 05H + F9H = FEH, no carry anywhere: CY (borrow)=1, AC=0
        self.check("MVI A, 5\nMVI B, 7\nSUB B\nHLT", {"A": 0xFE, "CY": 1, "S": 1, "Z": 0, "P": 0, "AC": 0})
        # 15H - 03H: 5 + C + 1 carries out of bit 3 -> AC=1
        self.check("MVI A, 15H\nSUI 3\nHLT", {"A": 0x12, "CY": 0, "AC": 1})

    def test_sbb_sbi(self):
        self.check("STC\nMVI A, 10H\nMVI B, 5\nSBB B\nHLT", {"A": 0x0A, "CY": 0})
        self.check("STC\nMVI A, 0\nMVI B, 0\nSBB B\nHLT", {"A": 0xFF, "CY": 1})
        self.check("STC\nMVI A, 20H\nSBI 1FH\nHLT", {"A": 0, "Z": 1, "CY": 0})
        self.check("STC\nMVI A, 5\nMVI B, 0FFH\nSBB B\nHLT", {"A": 0x05, "CY": 1})

    def test_sui(self):
        self.check("MVI A, 20H\nSUI 21H\nHLT", {"A": 0xFF, "CY": 1, "S": 1})

    def test_inr_dcr(self):
        self.check("STC\nMVI A, 0FH\nINR A\nHLT", {"A": 0x10, "AC": 1, "CY": 1})
        self.check("MVI B, 0FFH\nINR B\nHLT", {"B": 0, "Z": 1, "AC": 1, "CY": 0})
        self.check("MVI A, 1\nDCR A\nHLT", {"A": 0, "Z": 1, "AC": 1})
        self.check("STC\nMVI C, 0\nDCR C\nHLT", {"C": 0xFF, "S": 1, "P": 1, "AC": 0, "CY": 1})

    def test_inr_dcr_memory(self):
        self.check("LXI H, 3000H\nMVI M, 41H\nINR M\nHLT", {"M[3000]": 0x42})
        self.check("LXI H, 3000H\nMVI M, 10H\nDCR M\nHLT", {"M[3000]": 0x0F, "AC": 0})

    def test_inx_dcx_affect_no_flags(self):
        self.check(
            "XRA A\nLXI H, 00FFH\nINX H\nLXI B, 1\nDCX B\nINX SP\nLXI D, 0\nDCX D\nHLT",
            {"HL": 0x100, "BC": 0, "DE": 0xFFFF, "SP": 0x0000, "Z": 1},
        )

    def test_dad_only_affects_carry(self):
        self.check("XRA A\nLXI H, 0FFFFH\nLXI B, 1\nDAD B\nHLT", {"HL": 0, "CY": 1, "Z": 1, "P": 1})
        self.check("LXI H, 4001H\nDAD H\nHLT", {"HL": 0x8002, "CY": 0})
        self.check("LXI SP, 1000H\nLXI H, 0234H\nDAD SP\nHLT", {"HL": 0x1234})
        self.check("STC\nLXI H, 1\nLXI D, 1\nDAD D\nHLT", {"HL": 2, "CY": 0})

    def test_daa_examples(self):
        cases = [
            (0x15, 0x27, 0x42, 0), (0x99, 0x01, 0x00, 1), (0x09, 0x09, 0x18, 0),
            (0x88, 0x88, 0x76, 1), (0x50, 0x50, 0x00, 1), (0x99, 0x61, 0x60, 1),
            (0x99, 0x99, 0x98, 1), (0x98, 0x05, 0x03, 1),
        ]
        for x, y, result, carry in cases:
            with self.subTest(x=hex(x), y=hex(y)):
                self.check(f"MVI A, {x:X}H\nADI {y:X}H\nDAA\nHLT", {"A": result, "CY": carry})


class LogicalTests(InstructionTestCase):
    def test_ana_ani_set_ac_clear_cy(self):
        self.check("STC\nMVI A, 0F0H\nMVI B, 0FH\nANA B\nHLT", {"A": 0, "Z": 1, "CY": 0, "AC": 1, "P": 1})
        self.check("STC\nMVI A, 0FFH\nANI 81H\nHLT", {"A": 0x81, "S": 1, "AC": 1, "P": 1, "CY": 0})

    def test_ora_ori_xra_xri_clear_ac_and_cy(self):
        self.check("STC\nMVI A, 1\nMVI B, 2\nORA B\nHLT", {"A": 3, "CY": 0, "AC": 0, "P": 1})
        self.check("STC\nMVI A, 80H\nORI 1\nHLT", {"A": 0x81, "S": 1, "CY": 0})
        self.check("STC\nMVI A, 55H\nXRA A\nHLT", {"A": 0, "Z": 1, "CY": 0, "AC": 0, "P": 1})
        self.check("MVI A, 0FH\nXRI 0FFH\nHLT", {"A": 0xF0, "P": 1})

    def test_cmp_cpi(self):
        self.check("MVI A, 5\nMVI B, 5\nCMP B\nHLT", {"A": 5, "Z": 1, "CY": 0, "AC": 1})
        self.check("MVI A, 4\nMVI B, 5\nCMP B\nHLT", {"A": 4, "Z": 0, "CY": 1, "AC": 0})
        self.check("MVI A, 6\nMVI B, 5\nCMP B\nHLT", {"Z": 0, "CY": 0})
        self.check("MVI A, 10H\nCPI 20H\nHLT", {"A": 0x10, "CY": 1, "S": 1})
        self.check("LXI H, 3000H\nMVI M, 10H\nMVI A, 10H\nCMP M\nHLT", {"Z": 1})

    def test_cma_affects_no_flags(self):
        self.check("XRA A\nMVI A, 51H\nCMA\nHLT", {"A": 0xAE, "Z": 1, "P": 1})

    def test_stc_cmc(self):
        self.check("STC\nHLT", {"CY": 1})
        self.check("STC\nCMC\nHLT", {"CY": 0})
        self.check("STC\nCMC\nCMC\nHLT", {"CY": 1})

    def test_rotates(self):
        self.check("MVI A, 85H\nRLC\nHLT", {"A": 0x0B, "CY": 1})
        self.check("MVI A, 85H\nRRC\nHLT", {"A": 0xC2, "CY": 1})
        self.check("MVI A, 85H\nRAL\nHLT", {"A": 0x0A, "CY": 1})
        self.check("STC\nMVI A, 84H\nRAR\nHLT", {"A": 0xC2, "CY": 0})
        # Rotates change only CY
        self.check("XRA A\nMVI A, 1\nRRC\nHLT", {"A": 0x80, "Z": 1, "S": 0})


class BranchTests(InstructionTestCase):
    CONDITIONS = [
        # (mnemonic suffix, setup making it true, setup making it false)
        ("Z", "XRA A", "MVI A, 1\nORA A"),
        ("NZ", "MVI A, 1\nORA A", "XRA A"),
        ("C", "STC", "STC\nCMC"),
        ("NC", "STC\nCMC", "STC"),
        ("PE", "MVI A, 3\nORA A", "MVI A, 1\nORA A"),
        ("PO", "MVI A, 1\nORA A", "MVI A, 3\nORA A"),
        ("P", "MVI A, 1\nORA A", "MVI A, 80H\nORA A"),
        ("M", "MVI A, 80H\nORA A", "MVI A, 1\nORA A"),
    ]

    def test_conditional_jumps(self):
        for cc, true_setup, false_setup in self.CONDITIONS:
            for taken, setup in ((True, true_setup), (False, false_setup)):
                with self.subTest(op="J" + cc, taken=taken):
                    self.check(
                        f"{setup}\nJ{cc} T\nMVI B, 1\nHLT\nT: MVI B, 2\nHLT",
                        {"B": 2 if taken else 1},
                    )

    def test_conditional_calls(self):
        for cc, true_setup, false_setup in self.CONDITIONS:
            for taken, setup in ((True, true_setup), (False, false_setup)):
                with self.subTest(op="C" + cc, taken=taken):
                    self.check(
                        STACK + f"MVI C, 0\n{setup}\nC{cc} SUB1\nHLT\nSUB1: MVI C, 7\nRET",
                        {"C": 7 if taken else 0, "SP": 0x4000},
                    )

    def test_conditional_returns(self):
        for cc, true_setup, false_setup in self.CONDITIONS:
            for taken, setup in ((True, true_setup), (False, false_setup)):
                with self.subTest(op="R" + cc, taken=taken):
                    self.check(
                        STACK + f"MVI C, 0\nCALL SUB1\nHLT\nSUB1: {setup}\nR{cc}\nMVI C, 9\nRET",
                        {"C": 0 if taken else 9, "SP": 0x4000},
                    )

    def test_jmp(self):
        self.check("JMP T\nMVI B, 1\nHLT\nT: MVI B, 2\nHLT", {"B": 2})

    def test_call_pushes_return_address_high_byte_first(self):
        self.check(
            STACK + "CALL SUB1\nMVI B, 1\nHLT\nSUB1: MVI C, 5\nRET",
            {"B": 1, "C": 5, "SP": 0x4000, "M[3FFF]": 0x00, "M[3FFE]": 0x06},
        )

    def test_rst_all_vectors(self):
        for n in range(8):
            with self.subTest(n=n):
                source = (
                    f"ORG {n * 8:X}H\nMVI C, {n + 1}\nRET\n"
                    f"ORG 2000H\nLXI SP, 4000H\nRST {n}\nMVI B, 1\nHLT"
                )
                cpu = Processor8085()
                cpu.load_program(assemble(source))
                cpu.registers["PC"] = 0x2000  # main program, not the vector
                status = "OK"
                for _ in range(10):
                    status = cpu.step()
                    if status != "OK":
                        break
                self.assertEqual(status, "HALT")
                self.assertEqual((cpu.registers["C"], cpu.registers["B"]), (n + 1, 1))
                self.assertEqual(cpu.registers["SP"], 0x4000)

    def test_rst_pushes_address_of_next_instruction(self):
        cpu, _ = run("ORG 2000H\nLXI SP, 4000H\nRST 7\n", max_steps=2)
        self.assertEqual((cpu.registers["PC"], cpu.registers["SP"]), (0x0038, 0x3FFE))
        self.assertEqual(cpu.memory[0x3FFE] | (cpu.memory[0x3FFF] << 8), 0x2004)

    def test_pchl(self):
        self.check("LXI H, T\nPCHL\nMVI B, 1\nHLT\nT: MVI B, 2\nHLT", {"B": 2})


class StackTests(InstructionTestCase):
    def test_push_layout(self):
        self.check(STACK + "LXI B, 1234H\nPUSH B\nHLT", {"SP": 0x3FFE, "M[3FFF]": 0x12, "M[3FFE]": 0x34})

    def test_push_pop_all_pairs(self):
        self.check(STACK + "LXI B, 1234H\nPUSH B\nPOP D\nHLT", {"DE": 0x1234, "SP": 0x4000})
        self.check(STACK + "LXI D, 5678H\nPUSH D\nPOP H\nHLT", {"HL": 0x5678})
        self.check(STACK + "LXI H, 0ABCDH\nPUSH H\nPOP B\nHLT", {"BC": 0xABCD})

    def test_push_psw(self):
        # A=ABH, only CY set: flag byte 01H
        self.check(STACK + "MVI A, 0ABH\nSTC\nPUSH PSW\nPOP B\nHLT", {"B": 0xAB, "C": 0x01})
        # 7FH + 01H: S=1, Z=0, K=0 (V^S), AC=1, P=0, V=1, CY=0 -> 1001 0010
        self.check(STACK + "MVI A, 7FH\nADI 1\nPUSH PSW\nPOP B\nHLT", {"C": 0x92})

    def test_pop_psw_restores_flags(self):
        self.check(
            STACK + "LXI B, 12D5H\nPUSH B\nPOP PSW\nHLT",
            {"A": 0x12, "S": 1, "Z": 1, "AC": 1, "P": 1, "CY": 1},
        )
        self.check(STACK + "LXI B, 3400H\nPUSH B\nPOP PSW\nHLT", {"A": 0x34, "S": 0, "Z": 0, "AC": 0, "P": 0, "CY": 0})

    def test_xthl(self):
        self.check(
            STACK + "LXI B, 1234H\nPUSH B\nLXI H, 5678H\nXTHL\nHLT",
            {"HL": 0x1234, "M[3FFE]": 0x78, "M[3FFF]": 0x56, "SP": 0x3FFE},
        )

    def test_sphl(self):
        self.check("LXI H, 3000H\nSPHL\nHLT", {"SP": 0x3000})

    def test_stack_wraps_around(self):
        self.check("LXI SP, 0\nLXI B, 1234H\nPUSH B\nHLT", {"SP": 0xFFFE, "M[FFFF]": 0x12, "M[FFFE]": 0x34})
        self.check("LXI SP, 0FFFFH\nPOP B\nHLT", {"SP": 0x0001})


class ControlAndIOTests(InstructionTestCase):
    def test_out_writes_output_latch(self):
        cpu = self.check("MVI A, 42H\nOUT 10H\nMVI A, 0\nOUT 11H\nHLT", {"A": 0})
        self.assertEqual((cpu.output_ports[0x10], cpu.output_ports[0x11]), (0x42, 0x00))
        self.assertEqual(cpu.input_ports[0x10], 0)  # IN and OUT latches are separate

    def test_in_reads_input_device(self):
        cpu = Processor8085()
        cpu.load_program(assemble("MVI A, 0FFH\nOUT 20H\nIN 20H\nMOV B, A\nIN 21H\nHLT"))
        cpu.input_ports[0x20] = 0x5A  # value driven by the input device
        cpu.input_ports[0x21] = 0xC3
        while cpu.step() == "OK":
            pass
        self.assertEqual((cpu.registers["B"], cpu.registers["A"]), (0x5A, 0xC3))
        self.assertEqual(cpu.output_ports[0x20], 0xFF)

    def test_last_io_reports_transfers(self):
        cpu = Processor8085()
        cpu.load_program(assemble("MVI A, 7\nOUT 3\nIN 4\nNOP"))
        cpu.input_ports[4] = 9
        cpu.step()
        self.assertIsNone(cpu.last_io)
        cpu.step()
        self.assertEqual(cpu.last_io, ("OUT", 3, 7))
        cpu.step()
        self.assertEqual(cpu.last_io, ("IN", 4, 9))
        cpu.step()
        self.assertIsNone(cpu.last_io)

    def test_nop_changes_nothing_but_pc(self):
        cpu = self.check("MVI A, 5\nNOP\nHLT", {"A": 5, "PC": 0x0004})
        self.assertEqual(cpu.get_flags_byte(), 0x00)

    def test_hlt_leaves_pc_after_hlt_and_stays_halted(self):
        cpu = self.check("NOP\nHLT\nMVI A, 1", {"PC": 0x0002, "A": 0})
        self.assertTrue(cpu.halted)
        self.assertEqual(cpu.step(), "HALT")
        self.assertEqual(cpu.registers["PC"], 0x0002)
        self.assertEqual(cpu.last_address, 0x0001)

    def test_ei_di_reflected_by_rim(self):
        # After reset: interrupts disabled, RST 7.5/6.5/5.5 masked
        self.check("RIM\nHLT", {"A": 0x07})
        self.check("EI\nRIM\nHLT", {"A": 0x0F})
        self.check("EI\nDI\nRIM\nHLT", {"A": 0x07})

    def test_sim_sets_masks_only_when_mse_set(self):
        self.check("MVI A, 0AH\nSIM\nRIM\nHLT", {"A": 0x02})  # MSE=1, masks=010
        self.check("MVI A, 00H\nSIM\nRIM\nHLT", {"A": 0x07})  # MSE=0: masks unchanged

    def test_sim_serial_output(self):
        cpu, _ = run("MVI A, 0C0H\nSIM\nHLT")  # SDE=1, SOD=1
        self.assertEqual(cpu.sod, 1)
        cpu, _ = run("MVI A, 80H\nSIM\nHLT")  # SDE=0: SOD latch unchanged
        self.assertEqual(cpu.sod, 0)


class MachineCodeExecutionTests(InstructionTestCase):
    """The CPU must execute the bytes in memory, not the source text."""

    def test_executes_code_written_at_runtime(self):
        self.check("LXI H, 3000H\nMVI M, 76H\nJMP 3000H", {"PC": 0x3001})

    def test_self_modifying_code(self):
        self.check("LXI H, P\nINX H\nMVI M, 99H\nP: MVI A, 11H\nHLT", {"A": 0x99})

    def test_return_into_ram_code(self):
        self.check(STACK + "LXI H, 3000H\nMVI M, 76H\nPUSH H\nRET", {"PC": 0x3001})

    def test_memory_edits_change_execution(self):
        cpu = Processor8085()
        cpu.load_program(assemble("MVI A, 1\nHLT"))
        cpu.memory[1] = 0x2A  # patch the immediate operand
        cpu.step()
        self.assertEqual(cpu.registers["A"], 0x2A)

    def test_ds_area_executes_as_nops(self):
        cpu = self.check("BUF: DS 3\nMVI A, 7\nHLT", {"A": 7})
        self.assertEqual(cpu.t_states, 3 * 4 + 7 + 5)

    def test_pc_wraps_at_end_of_memory(self):
        cpu = Processor8085()
        cpu.memory[0xFFFF] = 0x00  # NOP at FFFFH
        cpu.memory[0x0000] = 0x76  # HLT at 0000H
        cpu.registers["PC"] = 0xFFFF
        self.assertEqual(cpu.step(), "OK")
        self.assertEqual(cpu.registers["PC"], 0x0000)
        self.assertEqual(cpu.step(), "HALT")

    def test_operand_fetch_wraps_at_end_of_memory(self):
        cpu = Processor8085()
        cpu.memory[0xFFFE] = 0x3E  # MVI A, d8 with the operand at FFFFH
        cpu.memory[0xFFFF] = 0x5C
        cpu.registers["PC"] = 0xFFFE
        cpu.step()
        self.assertEqual((cpu.registers["A"], cpu.registers["PC"]), (0x5C, 0x0000))

    def test_every_opcode_executes(self):
        for opcode in range(256):
            with self.subTest(opcode=hex(opcode)):
                cpu = Processor8085()
                cpu.registers["SP"] = 0x8000
                cpu.memory[0x100:0x103] = bytes([opcode, 0x34, 0x12])
                cpu.registers["PC"] = 0x100
                self.assertIn(cpu.step(), ("OK", "HALT"))
                self.assertIsNone(cpu.error)

    def test_last_instruction_is_disassembled_from_memory(self):
        cpu, _ = run("LOOP: MVI A, 0FFH\nJMP DONE\nDONE: HLT")
        self.assertEqual(cpu.last_instruction, "HLT")
        cpu, _ = run("JMP DONE\nDONE: HLT", max_steps=1)
        self.assertEqual(cpu.last_instruction, "JMP 0003H (DONE)")


class UndocumentedFlagTests(InstructionTestCase):
    """V (bit 1) and K (bit 5) as implemented in the 8085 silicon (Ken Shirriff's analysis)."""

    def flags(self, source):
        cpu, status = run(source)
        self.assertEqual(status, "HALT", cpu.error)
        return cpu.flags

    def test_cmp_k_is_signed_less_than(self):
        # "For subtraction and comparison, the K flag is 1 if the second value is larger than the first"
        from helpers import signed

        cpu = Processor8085()
        cpu.memory[0] = 0xB8  # CMP B
        for a in range(256):
            for b in range(256):
                cpu.registers.update(A=a, B=b, PC=0)
                cpu.step()
                self.assertEqual(cpu.flags["K"], 1 if signed(a) < signed(b) else 0, f"A={a:02X} B={b:02X}")
                self.assertEqual(cpu.flags["V"], 1 if not -128 <= signed(a) - signed(b) <= 127 else 0)

    def test_add_signed_overflow(self):
        from helpers import signed

        cpu = Processor8085()
        cpu.memory[0] = 0x80  # ADD B
        for a in range(256):
            for b in range(256):
                cpu.registers.update(A=a, B=b, PC=0)
                cpu.step()
                self.assertEqual(cpu.flags["V"], 1 if not -128 <= signed(a) + signed(b) <= 127 else 0)

    def test_inr_dcr_overflow_only_at_7f_80(self):
        self.assertEqual(self.flags("MVI A, 7FH\nINR A\nHLT")["V"], 1)
        self.assertEqual(self.flags("MVI A, 0FFH\nINR A\nHLT")["V"], 0)
        self.assertEqual(self.flags("MVI A, 80H\nDCR A\nHLT")["V"], 1)
        self.assertEqual(self.flags("MVI A, 0\nDCR A\nHLT")["V"], 0)

    def test_logic_ops_clear_v_and_k_equals_sign(self):
        for source in ("MVI A, 80H\nMVI B, 0FFH\nXRA B", "MVI A, 0F0H\nANI 80H", "MVI A, 1\nORI 80H", "MVI A, 1\nORA A"):
            with self.subTest(source=source):
                flags = self.flags("MVI A, 7FH\nADI 1\n" + source + "\nHLT")  # V=1 beforehand
                self.assertEqual(flags["V"], 0)
                self.assertEqual(flags["K"], flags["S"])

    def test_inx_dcx_set_k_on_wrap(self):
        cases = [
            ("LXI B, 0FFFFH\nINX B", 1), ("LXI B, 1234H\nINX B", 0),
            ("LXI D, 0\nDCX D", 1), ("LXI D, 1\nDCX D", 0),
            ("LXI H, 0FFFFH\nINX H", 1), ("LXI SP, 0\nDCX SP", 1), ("LXI SP, 0FFFFH\nINX SP", 1),
            ("LXI H, 7FFFH\nINX H", 0),
        ]
        for source, k in cases:
            with self.subTest(source=source):
                # Start with K=1 (CMP 0 vs 1: 0 < 1 signed) so clearing is visible too
                flags = self.flags("XRA A\nCPI 1\n" + source + "\nHLT")
                self.assertEqual(flags["K"], k)
                self.assertEqual((flags["S"], flags["C"]), (1, 1))  # other flags untouched

    def test_dad_sets_16_bit_overflow_only(self):
        flags = self.flags("LXI H, 7FFFH\nLXI B, 1\nDAD B\nHLT")
        self.assertEqual((flags["V"], flags["C"]), (1, 0))
        flags = self.flags("LXI H, 8000H\nLXI B, 8000H\nDAD B\nHLT")
        self.assertEqual((flags["V"], flags["C"]), (1, 1))
        flags = self.flags("LXI H, 0FFFFH\nLXI B, 1\nDAD B\nHLT")
        self.assertEqual((flags["V"], flags["C"]), (0, 1))
        # K is not changed by DAD
        self.assertEqual(self.flags("XRA A\nCPI 1\nLXI H, 1\nDAD H\nHLT")["K"], 1)

    def test_rotates_v(self):
        self.assertEqual(self.flags("MVI A, 40H\nRLC\nHLT")["V"], 1)
        self.assertEqual(self.flags("MVI A, 0C0H\nRAL\nHLT")["V"], 0)
        self.assertEqual(self.flags("MVI A, 7FH\nADI 1\nMVI A, 1\nRRC\nHLT")["V"], 0)
        self.assertEqual(self.flags("MVI A, 7FH\nADI 1\nRAR\nHLT")["V"], 0)

    def test_flag_byte_layout_and_pop_psw(self):
        cpu = self.check(STACK + "LXI B, 00FFH\nPUSH B\nPOP PSW\nHLT", {"S": 1, "Z": 1, "AC": 1, "P": 1, "CY": 1})
        self.assertEqual((cpu.flags["K"], cpu.flags["V"]), (1, 1))
        self.assertEqual(cpu.get_flags_byte(), 0xF7)  # bit 3 always reads 0
        cpu = self.check(STACK + "LXI B, 0022H\nPUSH B\nPOP PSW\nPUSH PSW\nPOP D\nHLT", {"E": 0x22})
        self.assertEqual((cpu.flags["K"], cpu.flags["V"]), (1, 1))


class ExhaustiveAluTests(unittest.TestCase):
    """Every ALU operation for every A, operand and carry-in against the reference ALU."""

    def test_reference_subtraction_agrees_with_borrow_formulation(self):
        # Sanity check of the reference model itself using a different formulation:
        # CY = borrow out of bit 7, AC = NOT borrow out of bit 3 (two's complement add).
        for a in range(256):
            for b in range(256):
                for borrow in (0, 1):
                    result, ac, cy, _ = ripple_add(a, b ^ 0xFF, 1 - borrow)
                    q = a - b - borrow
                    self.assertEqual(result, q & 0xFF)
                    self.assertEqual(1 - cy, 1 if q < 0 else 0)
                    self.assertEqual(ac, (~(a ^ b ^ q) >> 4) & 1)

    def test_register_alu_operations(self):
        names = ("ADD", "ADC", "SUB", "SBB", "ANA", "XRA", "ORA", "CMP")
        cpu = Processor8085()
        for operation, name in enumerate(names):
            cpu.memory[0] = 0x80 | (operation << 3)  # op B
            for a in range(256):
                for b in range(256):
                    for carry in (0, 1):
                        cpu.registers.update(A=a, B=b, PC=0)
                        cpu.flags.update(S=0, Z=0, AC=0, P=0, C=carry)
                        cpu.step()
                        want_a, want_flags = reference_alu(operation, a, b, carry)
                        got = (cpu.registers["A"], dict(cpu.flags))
                        if got != (want_a, want_flags):
                            self.fail(
                                f"{name} A={a:02X} B={b:02X} CY={carry}: "
                                f"got {got}, want {(want_a, want_flags)}"
                            )

    def test_immediate_alu_operations_match_register_forms(self):
        cpu_reg = Processor8085()
        cpu_imm = Processor8085()
        for operation in range(8):
            cpu_reg.memory[0] = 0x80 | (operation << 3)
            cpu_imm.memory[0] = 0xC6 | (operation << 3)
            for a in range(0, 256, 3):
                for b in range(256):
                    for carry in (0, 1):
                        cpu_reg.registers.update(A=a, B=b, PC=0)
                        cpu_reg.flags.update(C=carry)
                        cpu_imm.registers.update(A=a, PC=0)
                        cpu_imm.flags.update(C=carry)
                        cpu_imm.memory[1] = b
                        cpu_reg.step()
                        cpu_imm.step()
                        self.assertEqual(cpu_reg.registers["A"], cpu_imm.registers["A"])
                        self.assertEqual(cpu_reg.flags, cpu_imm.flags)

    def test_inr_dcr_all_values(self):
        cpu = Processor8085()
        for value in range(256):
            for carry in (0, 1):
                for opcode, operand in ((0x04, 0x01), (0x05, 0xFF)):  # INR B = B+1, DCR B = B+FFH
                    cpu.memory[0] = opcode
                    cpu.registers.update(B=value, PC=0)
                    cpu.flags.update(C=carry)
                    cpu.step()
                    result, ac, carry_out, carry_into7 = ripple_add(value, operand, 0)
                    self.assertEqual(cpu.flags["V"], carry_into7 ^ carry_out, f"V op {opcode:02X} {value:02X}")
                    self.assertEqual(cpu.flags["K"], cpu.flags["V"] ^ (result >> 7))
                    self.assertEqual(cpu.registers["B"], result)
                    self.assertEqual(cpu.flags["AC"], ac, f"op {opcode:02X} value {value:02X}")
                    self.assertEqual(cpu.flags["C"], carry, "INR/DCR must not change CY")
                    self.assertEqual(cpu.flags["Z"], 1 if result == 0 else 0)
                    self.assertEqual(cpu.flags["S"], result >> 7)
                    self.assertEqual(cpu.flags["P"], parity_even(result))

    def test_daa_produces_correct_bcd_sums(self):
        # Plain decimal arithmetic is the oracle: for every pair of valid BCD
        # bytes and carry-in, ADD/ADC followed by DAA must give the BCD sum.
        cpu = Processor8085()
        cpu.memory[0:2] = bytes([0x88, 0x27])  # ADC B, DAA
        to_bcd = lambda n: ((n // 10) << 4) | (n % 10)
        for x in range(100):
            for y in range(100):
                for carry in (0, 1):
                    cpu.registers.update(A=to_bcd(x), B=to_bcd(y), PC=0)
                    cpu.flags.update(C=carry)
                    cpu.step()
                    cpu.step()
                    total = x + y + carry
                    self.assertEqual(
                        (cpu.registers["A"], cpu.flags["C"]),
                        (to_bcd(total % 100), 1 if total >= 100 else 0),
                        f"{x} + {y} + {carry}",
                    )

    def test_daa_all_inputs(self):
        cpu = Processor8085()
        cpu.memory[0] = 0x27
        for a in range(256):
            for carry in (0, 1):
                for ac in (0, 1):
                    cpu.registers.update(A=a, PC=0)
                    cpu.flags.update(C=carry, AC=ac)
                    cpu.step()
                    low, high = a & 0x0F, a >> 4
                    correction = 0x06 if (low > 9 or ac) else 0
                    want_cy = carry
                    if high > 9 or carry or (high >= 9 and low > 9):
                        correction |= 0x60
                        want_cy = 1
                    want_a = (a + correction) & 0xFF
                    self.assertEqual(cpu.registers["A"], want_a, f"A={a:02X} CY={carry} AC={ac}")
                    self.assertEqual(cpu.flags["C"], want_cy)
                    self.assertEqual(cpu.flags["AC"], 1 if low + (correction & 0x0F) > 0x0F else 0)
                    self.assertEqual(cpu.flags["Z"], 1 if want_a == 0 else 0)
                    self.assertEqual(cpu.flags["P"], parity_even(want_a))


if __name__ == "__main__":
    unittest.main()
