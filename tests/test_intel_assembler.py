"""
Intel 8080/8085 assembly language compatibility: constants, operator
precedence, data directives, SET, conditional assembly and macros.
"""

import unittest

from helpers import assemble, run


def words(source):
    """Assemble 'DW <expr>' and return the 16-bit value."""
    out = assemble(f"DW {source}")
    return out.memory[0] | (out.memory[1] << 8)


def code(source, length=None):
    out = assemble(source)
    end = length if length is not None else max(out.program_end_address, 1)
    return list(out.memory[:end])


class ConstantTests(unittest.TestCase):
    def test_number_bases(self):
        self.assertEqual(words("1010B"), 10)
        self.assertEqual(words("17O"), 15)
        self.assertEqual(words("17Q"), 15)
        self.assertEqual(words("99D"), 99)
        self.assertEqual(words("99"), 99)
        self.assertEqual(words("0FFFFH"), 0xFFFF)
        self.assertEqual(words("0ffh"), 0xFF)

    def test_character_constants(self):
        self.assertEqual(words("'A'"), 0x41)
        self.assertEqual(words("'AB'"), 0x4142)
        self.assertEqual(words("'a'"), 0x61)  # case preserved inside quotes
        self.assertEqual(words("''''"), 0x27)  # doubled quote = apostrophe
        self.assertEqual(code("MVI A, 'z'"), [0x3E, 0x7A])

    def test_invalid_numbers(self):
        for text, fragment in (
            ("FFH", "must start with a digit"),
            ("12B", "Invalid number"),
            ("1G", "Invalid number"),
            ("10000H", "out of range"),
            ("'ABC'", "1 or 2 characters"),
        ):
            with self.subTest(text=text):
                with self.assertRaises(SyntaxError) as context:
                    assemble(f"DW {text}")
                self.assertIn(fragment, str(context.exception))

    def test_location_counter(self):
        self.assertEqual(code("JMP $"), [0xC3, 0x00, 0x00])
        out = assemble("ORG 100H\nNOP\nLXI H, $ + 3")
        self.assertEqual(list(out.memory[0x101:0x104]), [0x21, 0x04, 0x01])
        out = assemble("ORG 200H\nHERE EQU $\nDW HERE")
        self.assertEqual(out.symbols["HERE"], 0x200)


class PrecedenceTests(unittest.TestCase):
    def test_arithmetic_precedence(self):
        self.assertEqual(words("2 + 3 * 4"), 14)
        self.assertEqual(words("(2 + 3) * 4"), 20)
        self.assertEqual(words("10 - 2 - 3"), 5)
        self.assertEqual(words("100 / 10 / 5"), 2)
        self.assertEqual(words("7 MOD 3 + 1"), 2)
        self.assertEqual(words("1 SHL 4 + 1"), 17)
        self.assertEqual(words("-2 * 3"), (-6) & 0xFFFF)
        self.assertEqual(words("2 * -3"), (-6) & 0xFFFF)

    def test_high_low(self):
        self.assertEqual(words("HIGH 1234H"), 0x12)
        self.assertEqual(words("LOW 1234H"), 0x34)
        self.assertEqual(words("HIGH 1234H + 1"), 0x13)  # HIGH binds tighter than +
        self.assertEqual(words("LOW (1234H + 1)"), 0x35)

    def test_relational_and_logical(self):
        self.assertEqual(words("5 EQ 5"), 0xFFFF)
        self.assertEqual(words("5 NE 5"), 0)
        self.assertEqual(words("3 LT 2"), 0)
        self.assertEqual(words("2 LE 2"), 0xFFFF)
        self.assertEqual(words("NOT 0"), 0xFFFF)
        self.assertEqual(words("NOT 0 AND 0FH"), 0x0F)
        self.assertEqual(words("1 OR 2 AND 0"), 1)  # AND before OR
        self.assertEqual(words("0F0H XOR 0FFH"), 0x0F)
        self.assertEqual(words("1 + 1 EQ 2"), 0xFFFF)  # arithmetic before relational
        self.assertEqual(words("NOT 1 EQ 2"), 0xFFFF)  # relational before NOT

    def test_symbolic_operator_aliases(self):
        self.assertEqual(words("1 | 2 & 0"), 1)
        self.assertEqual(words("0F3H ^ 0FH"), 0xFC)
        self.assertEqual(words("1 << 3"), 8)
        self.assertEqual(words("80H >> 4"), 8)
        self.assertEqual(words("~0"), 0xFFFF)

    def test_unsigned_16_bit_arithmetic(self):
        self.assertEqual(words("0FFFFH + 2"), 1)
        self.assertEqual(words("0 - 1"), 0xFFFF)
        self.assertEqual(words("8000H * 2"), 0)
        self.assertEqual(words("(0 - 1) / 2"), 0x7FFF)  # unsigned division
        self.assertEqual(words("-1 / 2"), 0)  # unary minus binds like binary minus: -(1/2)
        self.assertEqual(words("1 SHL 16"), 0)

    def test_division_by_zero(self):
        with self.assertRaises(SyntaxError):
            assemble("DW 1 / 0")


class RangeTests(unittest.TestCase):
    def test_byte_operands_must_fit(self):
        self.assertEqual(code("MVI A, -1"), [0x3E, 0xFF])
        self.assertEqual(code("MVI A, -128"), [0x3E, 0x80])
        self.assertEqual(code("CPI 0FF00H + 100H"), [0xFE, 0x00])  # wraps to 0
        self.assertEqual(code("ADI 255"), [0xC6, 0xFF])
        for source in ("MVI A, 300", "ADI 100H", "OUT 256", "DB 1234H", "CPI 1FFH"):
            with self.subTest(source=source):
                with self.assertRaises(SyntaxError) as context:
                    assemble(source)
                self.assertIn("out of 8-bit range", str(context.exception))

    def test_register_names_are_not_values(self):
        with self.assertRaises(SyntaxError) as context:
            assemble("MVI A, B")
        self.assertIn("Register name B", str(context.exception))


class DataDirectiveTests(unittest.TestCase):
    def test_db(self):
        out = assemble("MSG: DB 'Hi', 0DH, 0AH, -1, 'A' + 1\nNEXT: NOP")
        self.assertEqual(list(out.memory[:7]), [0x48, 0x69, 0x0D, 0x0A, 0xFF, 0x42, 0x00])
        self.assertEqual(out.labels, {"MSG": 0, "NEXT": 6})
        self.assertEqual(out.data_memory_range, set(range(6)))

    def test_db_strings_with_commas_semicolons_and_quotes(self):
        out = assemble("DB 'a,b;c', 'it''s' ; comment")
        self.assertEqual(bytes(out.memory[:9]), b"a,b;cit's")

    def test_dw_is_little_endian(self):
        out = assemble("ORG 10H\nTABLE: DW 1234H, TABLE, 'AB'")
        self.assertEqual(list(out.memory[0x10:0x16]), [0x34, 0x12, 0x10, 0x00, 0x42, 0x41])

    def test_data_is_usable_by_code(self):
        cpu, status = run("LXI H, MSG\nMOV A, M\nINX H\nMOV B, M\nHLT\nMSG: DB 'OK'")
        self.assertEqual((cpu.registers["A"], cpu.registers["B"]), (ord("O"), ord("K")))

    def test_line_map_for_data(self):
        out = assemble("NOP\nDATA: DB 1, 2\nBUF: DS 2\nHLT")
        self.assertEqual(out.line_to_address_map, {1: 0, 2: 1, 3: 3, 4: 5})
        self.assertEqual(out.address_to_line_map, {0: 1, 5: 4})  # instructions only


class SymbolTests(unittest.TestCase):
    def test_set_can_be_redefined(self):
        out = assemble("X SET 1\nMVI A, X\nX SET X + 1\nMVI B, X")
        self.assertEqual(list(out.memory[:4]), [0x3E, 1, 0x06, 2])

    def test_set_cannot_redefine_equ(self):
        with self.assertRaises(SyntaxError):
            assemble("X EQU 1\nX SET 2")

    def test_reserved_words_rejected(self):
        for source in ("MOV: NOP", "HIGH: NOP", "A: NOP", "DB EQU 1", "IF SET 2"):
            with self.subTest(source=source):
                with self.assertRaises(SyntaxError):
                    assemble(source)

    def test_intel_name_characters(self):
        out = assemble("?LOOP: NOP\n@TMP: NOP\nJMP ?LOOP")
        self.assertEqual(out.labels, {"?LOOP": 0, "@TMP": 1})

    def test_register_symbols_in_register_operands(self):
        self.assertEqual(code("PTR EQU H\nINX PTR"), [0x23])
        self.assertEqual(code("MOV 7, 0"), [0x78])  # MOV A,B
        self.assertEqual(code("PUSH 6"), [0xF5])  # 6 = PSW
        self.assertEqual(code("LXI 6, 0"), [0x31, 0, 0])  # 6 = SP

    def test_end_sets_start_address(self):
        out = assemble("ORG 2000H\nNOP\nSTART: HLT\nEND START")
        self.assertEqual(out.starting_address, 0x2001)

    def test_forward_equ_in_ds(self):
        out = assemble("BUF: DS N\nX: NOP\nN EQU 4")
        self.assertEqual(out.labels["X"], 4)

    def test_circular_equ(self):
        with self.assertRaises(SyntaxError) as context:
            assemble("A1 EQU B1\nB1 EQU A1\nNOP")
        self.assertIn("Could not resolve", str(context.exception))


class ConditionalAssemblyTests(unittest.TestCase):
    def test_if_else_endif(self):
        source = "DEBUG EQU 1\nIF DEBUG\nMVI A, 1\nELSE\nMVI A, 2\nENDIF\nHLT"
        self.assertEqual(code(source, 3), [0x3E, 1, 0x76])
        self.assertEqual(code(source.replace("EQU 1", "EQU 0"), 3), [0x3E, 2, 0x76])

    def test_nested_and_relational(self):
        source = (
            "SIZE EQU 10\n"
            "IF SIZE GT 5\n"
            "  IF SIZE GT 20\n MVI A, 3\n  ELSE\n MVI A, 2\n  ENDIF\n"
            "ELSE\n MVI A, 1\nENDIF"
        )
        self.assertEqual(code(source), [0x3E, 2])

    def test_skipped_branch_is_not_assembled(self):
        out = assemble("IF 0\nSKIPPED: DB 'garbage'\nBOGUS INSTRUCTION\nENDIF\nKEPT: NOP")
        self.assertEqual(out.labels, {"KEPT": 0})

    def test_conditional_errors(self):
        for source, fragment in (
            ("IF 1\nNOP", "IF without ENDIF"),
            ("ELSE", "ELSE without IF"),
            ("ENDIF", "ENDIF without IF"),
            ("IF 1\nELSE\nELSE\nENDIF", "Multiple ELSE"),
            ("IF LATER\nENDIF\nLATER: NOP", "Undefined symbol"),
        ):
            with self.subTest(source=source):
                with self.assertRaises(SyntaxError) as context:
                    assemble(source)
                self.assertIn(fragment, str(context.exception))


class MacroTests(unittest.TestCase):
    def test_macro_with_parameters(self):
        source = "LOADP MACRO RP, VALUE\nLXI RP, VALUE\nENDM\nLOADP H, 1234H\nLOADP D, 5678H"
        self.assertEqual(code(source), [0x21, 0x34, 0x12, 0x11, 0x78, 0x56])

    def test_local_labels_are_unique(self):
        source = (
            "DELAY MACRO COUNT\nLOCAL AGAIN\nMVI C, COUNT\nAGAIN: DCR C\nJNZ AGAIN\nENDM\n"
            "DELAY 3\nDELAY 5\nHLT"
        )
        out = assemble(source)
        self.assertEqual(list(out.memory[:11]), [0x0E, 3, 0x0D, 0xC2, 2, 0, 0x0E, 5, 0x0D, 0xC2, 8])
        cpu, status = run(source)
        self.assertEqual(status, "HALT")

    def test_concatenation_and_nested_calls(self):
        source = (
            "JIF MACRO COND, TARGET\nJ&COND TARGET\nENDM\n"
            "TWICE MACRO COND\nJIF COND, DONE\nJIF COND, DONE\nENDM\n"
            "TWICE NZ\nDONE: HLT"
        )
        self.assertEqual(code(source, 7), [0xC2, 6, 0, 0xC2, 6, 0, 0x76])

    def test_angle_bracket_arguments_and_nul(self):
        source = (
            "BYTES MACRO LIST, EXTRA\nDB LIST\nIF NUL EXTRA\nDB 0\nELSE\nDB EXTRA\nENDIF\nENDM\n"
            "BYTES <1, 2, 3>\nBYTES <4>, 9"
        )
        self.assertEqual(code(source, 6), [1, 2, 3, 0, 4, 9])

    def test_exitm(self):
        source = "MAC MACRO X\nIF X EQ 0\nEXITM\nENDIF\nDB X\nENDM\nMAC 0\nMAC 5"
        self.assertEqual(code(source, 1), [5])

    def test_macro_lines_map_to_invocation_line(self):
        out = assemble("TWO MACRO\nNOP\nNOP\nENDM\nTWO\nHLT")
        self.assertEqual(out.address_to_line_map, {0: 5, 1: 5, 2: 6})
        self.assertEqual(out.line_to_address_map, {5: 0, 6: 2})

    def test_macro_errors(self):
        for source, fragment in (
            ("MAC MACRO\nNOP", "Missing ENDM"),
            ("ENDM", "ENDM without"),
            ("MAC MACRO\nMAC\nENDM\nMAC", "nested too deeply"),
            ("MAC MACRO A1\nENDM\nMAC 1, 2", "at most 1 argument"),
            ("EXITM", "outside a macro"),
            ("MAC MACRO\nMOV A\nENDM\nMAC", "in macro MAC"),
            ("M MACRO\nENDM", "reserved word"),
        ):
            with self.subTest(source=source):
                with self.assertRaises(SyntaxError) as context:
                    assemble(source)
                self.assertIn(fragment, str(context.exception))

    def test_rept_irp_irpc(self):
        self.assertEqual(code("REPT 3\nNOP\nENDM\nHLT", 4), [0, 0, 0, 0x76])
        self.assertEqual(code("IRP R, <B, C, D>\nINR R\nENDM"), [0x04, 0x0C, 0x14])
        self.assertEqual(code("IRPC CH, ABC\nDB '&CH'\nENDM", 3), [0x41, 0x42, 0x43])
        self.assertEqual(code("N SET 0\nREPT 4\nN SET N + 1\nDB N\nENDM", 4), [1, 2, 3, 4])


class IntelProgramTests(unittest.TestCase):
    def test_complete_program(self):
        source = """
; String length and checksum - Intel-style source
CR      EQU     0DH
LF      EQU     0AH
        ORG     2000H
START:  LXI     SP, STACK
        LXI     H, MSG
        MVI     B, 0            ; length
        MVI     C, 0            ; checksum
NEXT:   MOV     A, M
        CPI     '$'
        JZ      DONE
        ADD     C
        MOV     C, A
        INR     B
        INX     H
        JMP     NEXT
DONE:   MOV     A, B
        STA     RESULT
        MOV     A, C
        STA     RESULT + 1
        HLT
MSG:    DB      'Hello', CR, LF, '$'
RESULT: DS      2
        DS      16
STACK   EQU     $
        END     START
"""
        cpu, status = run(source)
        self.assertEqual(status, "HALT", cpu.error)
        result = cpu.labels["RESULT"]
        text = b"Hello\r\n"
        self.assertEqual(cpu.memory[result], len(text))
        self.assertEqual(cpu.memory[result + 1], sum(text) & 0xFF)
        self.assertEqual(cpu.symbols["STACK"], result + 18)


if __name__ == "__main__":
    unittest.main()
