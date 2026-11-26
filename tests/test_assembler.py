"""Assembler syntax, directives and error handling."""

import unittest

from helpers import assemble, run


class OperandSyntaxTests(unittest.TestCase):
    def test_commas_with_or_without_spaces(self):
        for text in ("MVI A,05H", "MVI A, 05H", "MVI A ,05H", "MVI   A ,  05H"):
            with self.subTest(text=text):
                self.assertEqual(list(assemble(text).memory[:2]), [0x3E, 0x05])
        self.assertEqual(list(assemble("LXI H,2050H").memory[:3]), [0x21, 0x50, 0x20])
        self.assertEqual(assemble("MOV A,B").memory[0], 0x78)

    def test_lowercase_source(self):
        self.assertEqual(list(assemble("loop: mvi a, 0ffh\njnz loop").memory[:5]), [0x3E, 0xFF, 0xC2, 0, 0])

    def test_label_forms(self):
        out = assemble("START: NOP\nNEXT:MVI A, 1\nEMPTY:\nEND_: HLT")
        self.assertEqual(out.labels, {"START": 0, "NEXT": 1, "EMPTY": 3, "END_": 3})

    def test_expressions_in_operands(self):
        source = "ORG 2000H\nBASE: EQU 2050H\nMVI A, BASE >> 8\nMVI B, BASE & 0FFH\nLXI H, BASE + 2\nMVI C, 0F3H ^ 0FH\nHLT"
        cpu, status = run(source)
        self.assertEqual(status, "HALT")
        self.assertEqual(
            (cpu.registers["A"], cpu.registers["B"], cpu.registers["H"], cpu.registers["L"], cpu.registers["C"]),
            (0x20, 0x50, 0x20, 0x52, 0xFC),
        )

    def test_negative_immediate(self):
        self.assertEqual(assemble("MVI A, -1").memory[1], 0xFF)
        self.assertEqual(assemble("ADI -2").memory[1], 0xFE)

    def test_label_arithmetic(self):
        out = assemble("JMP TARGET + 1\nTARGET: NOP\nHLT")
        self.assertEqual(list(out.memory[:3]), [0xC3, 0x04, 0x00])


class DirectiveTests(unittest.TestCase):
    def test_equ_with_and_without_colon(self):
        out = assemble("A1 EQU 5\nB1: EQU A1 * 2\nMVI A, A1\nMVI B, B1")
        self.assertEqual(out.symbols, {"A1": 5, "B1": 10})
        self.assertEqual(list(out.memory[:4]), [0x3E, 5, 0x06, 10])
        self.assertNotIn("A1", out.labels)

    def test_equ_forward_reference_and_labels(self):
        out = assemble("SIZE: EQU END_LABEL - START\nSTART: NOP\nNOP\nEND_LABEL: MVI A, SIZE")
        self.assertEqual(out.symbols["SIZE"], 2)
        self.assertEqual(out.memory[3], 2)

    def test_duplicate_symbols_rejected(self):
        with self.assertRaises(SyntaxError):
            assemble("X EQU 1\nX EQU 2")
        with self.assertRaises(SyntaxError):
            assemble("L: NOP\nL: NOP")
        with self.assertRaises(SyntaxError):
            assemble("X EQU 1\nX: NOP")

    def test_org_and_ds(self):
        out = assemble("ORG 2000H\nJMP START\nBUF: DS 4\nSTART: HLT")
        self.assertEqual(out.starting_address, 0x2000)
        self.assertEqual(out.labels, {"BUF": 0x2003, "START": 0x2007})
        self.assertEqual(out.data_memory_range, {0x2003, 0x2004, 0x2005, 0x2006})
        self.assertEqual(out.memory[0x2007], 0x76)

    def test_ds_with_symbol_and_expression(self):
        out = assemble("N: EQU 3\nBUF: DS N * 2\nAFTER: NOP")
        self.assertEqual(out.labels["AFTER"], 6)

    def test_end_stops_assembly(self):
        out = assemble("NOP\nEND\nHLT")
        self.assertEqual(out.program_end_address, 1)

    def test_line_maps(self):
        out = assemble("; comment\nORG 100H\nMVI A, 1\n\nLOOP: JMP LOOP")
        self.assertEqual(out.line_to_address_map, {3: 0x100, 5: 0x102})
        self.assertEqual(out.address_to_line_map, {0x100: 3, 0x102: 5})


class ErrorTests(unittest.TestCase):
    def assert_error(self, source, fragment):
        with self.assertRaises(SyntaxError) as context:
            assemble(source)
        self.assertIn(fragment, str(context.exception))

    def test_unknown_instruction(self):
        self.assert_error("FOO A", "Unknown instruction")

    def test_wrong_operand_counts(self):
        self.assert_error("MVI A", "expects 2 operands")
        self.assert_error("MOV A, B, C", "expects 2 operands")
        self.assert_error("ADD", "expects 1 operand")
        self.assert_error("ADD B, C", "expects 1 operand")
        self.assert_error("HLT A", "expects 0 operands")
        self.assert_error("MVI A,", "Missing operand")

    def test_invalid_registers(self):
        self.assert_error("MOV A, SP", "Invalid register")
        self.assert_error("INX A", "Invalid register pair")
        self.assert_error("LDAX H", "only supports B or D")
        self.assert_error("STAX SP", "only supports B or D")
        self.assert_error("MOV M, M", "MOV M,M")

    def test_push_pop_sp_rejected(self):
        # SP would otherwise encode as PSW (F5H / F1H)
        self.assert_error("PUSH SP", "B, D, H or PSW")
        self.assert_error("POP SP", "B, D, H or PSW")
        self.assert_error("LXI PSW, 0", "Invalid register pair")

    def test_rst_range(self):
        self.assert_error("RST 8", "0-7")

    def test_undefined_symbol(self):
        self.assert_error("JMP NOWHERE", "Undefined symbol: NOWHERE")

    def test_program_must_fit_in_memory(self):
        self.assert_error("ORG 0FFFEH\nLXI H, 0", "64KB")
        self.assertEqual(assemble("ORG 0FFFDH\nLXI H, 1234H").memory[0xFFFF], 0x12)
        self.assert_error("ORG 10000H\nNOP", "out of range")
        self.assert_error("ORG 0FFF0H\nDS 20H", "Invalid DS size")

    def test_invalid_label(self):
        self.assert_error("1ABC: NOP", "Invalid label")
        self.assert_error("A:B: NOP", "Invalid label")


class SampleProgramTests(unittest.TestCase):
    def test_bundled_fibonacci_program(self):
        # The example program shipped in the editor (src/main.py)
        source = """
ORG 2000H
JMP START
FIRST_ELEMENT:	EQU 0
SECOND_ELEMENT:	EQU 1
ELEMENTS_COUNT: 	EQU 0AH
LOOP_COUNTER:	EQU ELEMENTS_COUNT - 1
DATA_AREA: DS ELEMENTS_COUNT
START:	JMP FIBONACCI_SERIES_SETUP
FIBONACCI_SERIES_SETUP:
	MVI A, FIRST_ELEMENT
	MVI B, SECOND_ELEMENT
	MVI D, LOOP_COUNTER
	LXI H, DATA_AREA
	MOV M, A
	INX H
	JMP FIBONACCI_CALC_LOOP
FIBONACCI_CALC_LOOP:
	MOV C, A
	ADD B
	MOV B, C
	DCR D
	MOV M, A
	INX H
	JNZ FIBONACCI_CALC_LOOP
	JMP END_OF_PROGRAM
END_OF_PROGRAM:
	HLT
END
"""
        cpu, status = run(source)
        self.assertEqual(status, "HALT")
        data = cpu.labels["DATA_AREA"]
        self.assertEqual(list(cpu.memory[data : data + 10]), [0, 1, 1, 2, 3, 5, 8, 13, 21, 34])


if __name__ == "__main__":
    unittest.main()
