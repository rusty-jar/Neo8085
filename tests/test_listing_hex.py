"""Opcode listing, Intel HEX export/import and the disassembly round trip."""

import random
import re
import unittest

from helpers import assemble
from examples import EXAMPLES
from intel_hex import IntelHexError, hex_to_source, parse_intel_hex, to_intel_hex
from listing import build_listing
from processor import INSTRUCTION_SIZES, disassemble_opcode



def object_bytes(output):
    return {address: output.memory[address] for address in output.object_addresses}


def listing_bytes(text):
    """Address -> byte as shown in the LOC/OBJ columns of a listing (later rows win)."""
    shown = {}
    for line in text.splitlines():
        match = re.match(r"^([0-9A-F]{4})  ((?:[0-9A-F]{2} ){0,3}[0-9A-F]{2})(?:\s|$)", line)
        if match:
            address = int(match.group(1), 16)
            for offset, byte in enumerate(match.group(2).split()):
                shown[(address + offset) & 0xFFFF] = int(byte, 16)
    return shown


class IntelHexExport(unittest.TestCase):
    def test_known_records(self):
        memory = bytearray(0x10000)
        memory[0x2000:0x2003] = b"\x3E\x05\x76"
        self.assertEqual(to_intel_hex(memory, [0x2000, 0x2001, 0x2002]),
                         ":032000003E057624\n:00000001FF\n")

    def test_records_split_at_16_bytes_and_at_gaps(self):
        memory = bytearray(range(256)) * 256
        addresses = list(range(0x1000, 0x1021)) + [0x1030, 0xFFFF]
        lines = to_intel_hex(memory, addresses).splitlines()
        self.assertEqual([line[:9] for line in lines],
                         [":10100000", ":10101000", ":01102000", ":01103000", ":01FFFF00", ":00000001"])
        for line in lines:
            self.assertEqual(sum(bytes.fromhex(line[1:])) & 0xFF, 0)

    def test_examples_round_trip(self):
        for example in EXAMPLES:
            with self.subTest(example.title):
                output = assemble(example.source)
                expected = object_bytes(output)
                data, start = parse_intel_hex(to_intel_hex(output.memory, output.object_addresses))
                self.assertEqual(data, expected)
                self.assertIsNone(start)


class IntelHexImport(unittest.TestCase):
    def test_errors_are_reported_with_line_numbers(self):
        good = ":032000003E057624"
        cases = {
            "3E057624\n:00000001FF": "must start with ':'",
            ":032000003E057625\n:00000001FF": "Line 1: checksum error",
            ":042000003E057624\n:00000001FF": "length field",
            ":0320000G3E057624\n:00000001FF": "invalid hexadecimal",
            good: "no end-of-file record",
            ":00000001FF": "no data records",
            good + "\n:00000006FA\n:00000001FF": "unknown record type",
            ":02FFFF001122CD\n:00000001FF": "beyond FFFFH",
            good + "\n:01200000FFE0\n:00000001FF": "loaded twice",
            ":020000040001F9\n" + good + "\n:00000001FF": "outside the 8085",
        }
        for text, message in cases.items():
            with self.subTest(message):
                with self.assertRaises(IntelHexError) as context:
                    parse_intel_hex(text)
                self.assertIn(message, str(context.exception))

    def test_accepted_records(self):
        text = "\n".join([
            ":020000040000FA",  # extended linear address 0
            ":020000020000FC",  # extended segment address 0
            ":032000003E057624",
            ":0400000300002000D9",  # start segment address 0000:2000
            ":00000001FF",
            "this text after EOF is ignored",
        ])
        data, start = parse_intel_hex(text)
        self.assertEqual(data, {0x2000: 0x3E, 0x2001: 0x05, 0x2002: 0x76})
        self.assertEqual(start, 0x2000)
        # Same bytes twice is not a conflict; lower-case digits are fine
        data, _ = parse_intel_hex(":032000003e057624\n:032000003E057624\n:00000001ff")
        self.assertEqual(len(data), 3)


class DisassemblyRoundTrip(unittest.TestCase):
    def test_every_opcode_reassembles_to_the_same_bytes(self):
        for op in range(256):
            size = INSTRUCTION_SIZES[op]
            for operand in (0x0000, 0x0012, 0x00FF, 0x1234, 0xA0FF, 0xFFFF):
                b1 = operand & 0xFF
                imm16 = operand if size == 3 else b1
                text = disassemble_opcode(op, b1, imm16)
                expected = bytes([op, b1, operand >> 8][:size])
                with self.subTest(op=f"{op:02X}H", text=text):
                    output = assemble(f"ORG 1000H\n{text}")
                    self.assertEqual(bytes(output.memory[0x1000:0x1000 + size]), expected)

    def test_hex_to_source_reproduces_random_images(self):
        rng = random.Random(85)
        for _ in range(30):
            data = {}
            for _ in range(rng.randrange(1, 4)):
                base = rng.randrange(0x10000)
                for offset in range(rng.randrange(1, 80)):
                    if base + offset <= 0xFFFF:
                        data[base + offset] = rng.randrange(256)
            start = rng.choice([None, min(data), rng.randrange(0x10000)])
            source = hex_to_source(data, start, "random.hex")
            output = assemble(source)
            self.assertEqual(object_bytes(output), data)
            self.assertEqual(output.starting_address, start if start is not None else min(data))

    def test_examples_survive_hex_and_disassembly(self):
        for example in EXAMPLES:
            with self.subTest(example.title):
                original = assemble(example.source)
                data, _ = parse_intel_hex(to_intel_hex(original.memory, original.object_addresses))
                rebuilt = assemble(hex_to_source(data, original.starting_address, "x.hex"))
                self.assertEqual(object_bytes(rebuilt), object_bytes(original))
                self.assertEqual(rebuilt.starting_address, original.starting_address)


class Listing(unittest.TestCase):
    def test_listing_shows_every_byte_and_every_line(self):
        for example in EXAMPLES:
            with self.subTest(example.title):
                output = assemble(example.source)
                text = build_listing(output, example.title)
                self.assertEqual(listing_bytes(text), object_bytes(output))
                numbered = [int(m.group(1)) for m in re.finditer(r"^.{18}\s*(\d+)(?: [ +] |$)", text, re.M)]
                self.assertEqual(numbered, list(range(1, len(output.source_lines) + 1)))

    def test_format(self):
        source = "\n".join([
            "COUNT   EQU 10          ; a constant",
            "        ORG 2000H",
            "START:  LXI H, 2050H",
            "        MVI A, COUNT",
            "        HLT",
            "MSG:    DB 'HELLO', 0",
            "BUF:    DS 4",
            "        END START",
        ])
        text = build_listing(assemble(source), "test.asm")
        self.assertIn("Listing of test.asm", text)
        self.assertIn("      = 000A          1   COUNT   EQU 10          ; a constant", text)
        self.assertIn("2000  21 50 20        3   START:  LXI H, 2050H", text)
        self.assertIn("2003  3E 0A           4           MVI A, COUNT", text)
        self.assertIn("2006  48 45 4C 4C     6   MSG:    DB 'HELLO', 0", text)
        self.assertIn("\n200A  4F 00\n", text)  # continuation row of the DB
        self.assertIn("200C  (4 bytes)       7   BUF:    DS 4", text)
        self.assertRegex(text, r"START\s+L 2000")
        self.assertRegex(text, r"COUNT\s+S 000A")
        self.assertIn("Start address: 2000H", text)
        self.assertIn("Object code:   2000H-200BH", text)

    def test_macro_and_rept_expansions(self):
        example = next(e for e in EXAMPLES if e.title == "Macros and Conditional Assembly")
        text = build_listing(assemble(example.source), example.title)
        lines = text.splitlines()
        self.assertIn("+ LXI H, VAL1", text)
        self.assertIn("+ JNZ ??0001", text)
        # REPT expansion is listed after its ENDM, with the DB bytes
        endm = max(i for i, line in enumerate(lines) if re.search(r"^\s.{17}\s*\d+\s+ENDM", line))
        self.assertIn("+ DB N * N", lines[endm + 1])
        self.assertIn("+ N SET N + 1", lines[endm + 2])


if __name__ == "__main__":
    unittest.main()


class IntelHexStartAddress(unittest.TestCase):
    def test_start_record_round_trip(self):
        memory = bytearray(0x10000)
        memory[0x2000:0x2003] = b"\x3E\x05\x76"
        text = to_intel_hex(memory, [0x2000, 0x2001, 0x2002], start=0x2000)
        self.assertEqual(text.splitlines()[-2:], [":0400000300002000D9", ":00000001FF"])
        self.assertEqual(parse_intel_hex(text)[1], 0x2000)

    def test_default_export_is_the_8bit_format(self):
        memory = bytearray(0x10000)
        text = to_intel_hex(memory, [0x2000])
        self.assertEqual({line[7:9] for line in text.splitlines()}, {"00", "01"})

    def test_start_address_in_the_end_of_file_record(self):
        # some 8080-era tools put the start address in the end-of-file record
        data, start = parse_intel_hex(":032000003E057624\n:00200001DF\n")
        self.assertEqual(start, 0x2000)


class HexImportFindsCode(unittest.TestCase):
    def test_code_and_data_are_separated(self):
        example = next(e for e in EXAMPLES if e.title == "Bubble Sort")
        output = assemble(example.source)
        data, _ = parse_intel_hex(to_intel_hex(output.memory, output.object_addresses))
        source = hex_to_source(data, output.starting_address, "sort.hex")
        self.assertIn("START:  MVI B, 09H", source)
        self.assertIn("JNZ L2009", source)  # jump targets become labels
        self.assertIn("DB 39H, 0F2H, 05H, 7AH", source)  # the list is data, not instructions
        self.assertNotIn("DAD", source)
        self.assertEqual(object_bytes(assemble(source)), object_bytes(output))

    def test_interrupt_vectors_and_restarts_are_followed(self):
        source = "\n".join(["ORG 003CH", "JMP 2100H", "ORG 2000H", "RST 1", "HLT",
                            "ORG 0008H", "RET", "ORG 2100H", "EI", "RET", "END 2000H"])
        output = assemble(source)
        data, _ = parse_intel_hex(to_intel_hex(output.memory, output.object_addresses))
        text = hex_to_source(data, 0x2000, "x.hex")
        self.assertIn("JMP L2100", text)  # from the RST 7.5 vector
        self.assertIn("L0008:  RET", text)  # RST 1 target
        self.assertEqual(object_bytes(assemble(text)), object_bytes(output))
