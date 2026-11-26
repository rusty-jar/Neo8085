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
Intel HEX object files (Intel "Hexadecimal Object File Format", 8-bit form).

Each record is  :LLAAAATT<data>CC  where LL is the number of data bytes,
AAAA the load address, TT the record type and CC the two's complement of the
8-bit sum of all preceding bytes of the record.

Export writes data records (type 00) of up to 16 bytes, never crossing a gap
in the object code, followed by the end-of-file record :00000001FF. That is
the 8-bit format of Intel's specification, which has no start-address record
(the end-of-file record's address "is not used"). On request a Start Segment
Address record (type 03, CS = 0000, IP = start) from the 16-bit format can be
added; most tools accept it, strict 8-bit loaders may not.

Import accepts record types 00 (data) and 01 (end of file), 02/04 (extended
address, only with a zero base since the 8085 has a 16-bit address space)
and 03/05 (start address, used as the program's start). A non-zero address
in the end-of-file record, used as the start address by some 8080-era tools,
is accepted too. Checksums, lengths and hexadecimal digits are verified for
every record.

Imported files are turned into assembly source (hex_to_source): the bytes the
program can execute are found by following its jumps, calls and restarts from
the start address and the interrupt vectors, and are disassembled with labels;
all other bytes are written as DB data. Assembling the source reproduces
exactly the same bytes at the same addresses.
"""

from processor import INSTRUCTION_SIZES, disassemble_opcode


class IntelHexError(ValueError):
    """Malformed Intel HEX file (the message names the line)."""


def _record(address, record_type, data=b""):
    body = bytes([len(data), (address >> 8) & 0xFF, address & 0xFF, record_type]) + bytes(data)
    checksum = (-sum(body)) & 0xFF
    return ":" + body.hex().upper() + f"{checksum:02X}"


def to_intel_hex(memory, addresses, record_length=16, start=None):
    """
    Intel HEX text for the bytes of `memory` at `addresses` (any iterable of
    0000H-FFFFH addresses). Contiguous addresses are packed into records of up
    to `record_length` bytes; a gap always starts a new record. With `start`,
    a Start Segment Address record (CS = 0000, IP = start) is added before the
    end-of-file record.
    """
    if not 1 <= record_length <= 255:
        raise ValueError("record length must be 1-255")
    lines = []
    run_start = None
    run = bytearray()
    previous = None

    def flush():
        if run:
            for offset in range(0, len(run), record_length):
                lines.append(_record(run_start + offset, 0x00, run[offset:offset + record_length]))

    for address in sorted(set(addresses)):
        if not 0 <= address <= 0xFFFF:
            raise ValueError(f"address out of range: {address}")
        if previous is None or address != previous + 1:
            flush()
            run_start = address
            run = bytearray()
        run.append(memory[address])
        previous = address
    flush()
    if start is not None:
        if not 0 <= start <= 0xFFFF:
            raise ValueError(f"start address out of range: {start}")
        lines.append(_record(0x0000, 0x03, bytes([0, 0, start >> 8, start & 0xFF])))
    lines.append(_record(0x0000, 0x01))
    return "\n".join(lines) + "\n"


def parse_intel_hex(text):
    """
    Parses Intel HEX text. Returns (data, start) where data maps address ->
    byte (in file order) and start is the start address from a type 03/05
    record, or None.
    """
    data = {}
    start = None
    base = 0
    seen_eof = False
    eof_address = 0
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if seen_eof:
            break  # anything after the end-of-file record is ignored
        if not line.startswith(":"):
            raise IntelHexError(f"Line {number}: a record must start with ':'")
        digits = line[1:]
        if len(digits) < 10 or len(digits) % 2:
            raise IntelHexError(f"Line {number}: record is too short or has an odd number of digits")
        try:
            record = bytes.fromhex(digits)
        except ValueError:
            raise IntelHexError(f"Line {number}: invalid hexadecimal digits") from None
        length, record_type = record[0], record[3]
        address = (record[1] << 8) | record[2]
        payload = record[4:-1]
        if len(payload) != length:
            raise IntelHexError(f"Line {number}: length field says {length} bytes, record has {len(payload)}")
        if sum(record) & 0xFF:
            expected = (-sum(record[:-1])) & 0xFF
            raise IntelHexError(f"Line {number}: checksum error (is {record[-1]:02X}H, should be {expected:02X}H)")

        if record_type == 0x00:
            for offset, byte in enumerate(payload):
                target = base + address + offset
                if target > 0xFFFF:
                    raise IntelHexError(f"Line {number}: data beyond FFFFH (the 8085 addresses 64 KB)")
                if target in data and data[target] != byte:
                    raise IntelHexError(f"Line {number}: address {target:04X}H is loaded twice with different values")
                data[target] = byte
        elif record_type == 0x01:
            seen_eof = True
            eof_address = address  # some 8080-era tools put the start address here
        elif record_type in (0x02, 0x04):
            if length != 2:
                raise IntelHexError(f"Line {number}: extended address record needs 2 data bytes")
            value = (payload[0] << 8) | payload[1]
            base = value << 4 if record_type == 0x02 else value << 16
            if base:
                raise IntelHexError(f"Line {number}: extended address {base:X}H is outside the 8085's 64 KB")
        elif record_type == 0x03:
            if length != 4:
                raise IntelHexError(f"Line {number}: start address record needs 4 data bytes")
            segment = (payload[0] << 8) | payload[1]
            offset = (payload[2] << 8) | payload[3]
            start = ((segment << 4) + offset) & 0xFFFFF
        elif record_type == 0x05:
            if length != 4:
                raise IntelHexError(f"Line {number}: start address record needs 4 data bytes")
            start = int.from_bytes(payload, "big")
        else:
            raise IntelHexError(f"Line {number}: unknown record type {record_type:02X}H")
    if not seen_eof:
        raise IntelHexError("The file has no end-of-file record (:00000001FF) - it may be truncated")
    if not data:
        raise IntelHexError("The file contains no data records")
    if start is not None and start > 0xFFFF:
        raise IntelHexError(f"Start address {start:X}H is outside the 8085's 64 KB")
    if start is None and eof_address:
        start = eof_address
    return data, start


def _runs(data):
    """Contiguous address runs of the loaded bytes: [(start, bytes)]."""
    runs = []
    for address in sorted(data):
        if runs and address == runs[-1][0] + len(runs[-1][1]):
            runs[-1][1].append(data[address])
        else:
            runs.append((address, bytearray([data[address]])))
    return runs


def _hex(value, digits):
    """Hex constant the assembler accepts (a leading 0 before A-F)."""
    text = f"{value:0{digits}X}H"
    return "0" + text if text[0] in "ABCDEF" else text


def _db(values):
    return "DB " + ", ".join(_hex(value, 2) for value in values)


# Control flow of the 8085 instruction set, for finding the code in an image
_JUMPS = {0xC3, 0xDD, 0xFD} | {0xC2 | (cc << 3) for cc in range(8)}  # JMP, JNK, JK, Jcc
_CALLS = {0xCD} | {0xC4 | (cc << 3) for cc in range(8)}  # CALL, Ccc
_RESTARTS = {0xC7 | (n << 3): n * 8 for n in range(8)}  # RST n
_RESTARTS[0xCB] = 0x0040  # RSTV
_ENDS_FLOW = {0xC3, 0xC9, 0xE9}  # JMP, RET, PCHL: execution does not continue after them
_VECTORS = (0x0024, 0x002C, 0x0034, 0x003C)  # TRAP, RST 5.5, RST 6.5, RST 7.5


def find_code(data, entries):
    """
    Finds the instructions reachable from the entry addresses by following the
    jumps, calls and restarts. Returns {address: instruction size} for every
    instruction start. An instruction that would overlap one already found,
    or run past the loaded bytes, ends that path (it is left as data).
    """
    code = {}
    covered = set()
    pending = [e for e in entries if e in data]
    while pending:
        pc = pending.pop()
        while pc in data and pc not in code:
            op = data[pc]
            size = INSTRUCTION_SIZES[op]
            span = [(pc + i) & 0xFFFF for i in range(size)]
            if any(a not in data or a in covered for a in span):
                break
            code[pc] = size
            covered.update(span)
            if size == 3:
                target = data[span[1]] | (data[span[2]] << 8)
                if op in _JUMPS or op in _CALLS:
                    pending.append(target)
            if op in _RESTARTS:
                pending.append(_RESTARTS[op])
            if op in _ENDS_FLOW:
                break
            pc = (pc + size) & 0xFFFF
    return code


def hex_to_source(data, start=None, name="file"):
    """
    Assembly source reproducing the loaded bytes. The code is found by
    following the program's control flow from `start` (or the lowest loaded
    address) and from the interrupt vectors; it is disassembled with a label
    at every jump/call target. All other bytes are written as DB data.
    Assembling the source gives exactly the same bytes at the same addresses.
    """
    runs = _runs(data)
    if start is None:
        start = runs[0][0]
    total = sum(len(block) for _, block in runs)
    code = find_code(data, [start, *_VECTORS])

    # Labels at the jump/call targets that start an instruction
    labels = {}
    for pc, size in code.items():
        op = data[pc]
        if size == 3 and (op in _JUMPS or op in _CALLS):
            target = data[pc + 1] | (data[(pc + 2) & 0xFFFF] << 8)
            if target in code:
                labels[target] = f"L{target:04X}"
        if op in _RESTARTS and _RESTARTS[op] in code:
            labels[_RESTARTS[op]] = f"L{_RESTARTS[op]:04X}"
    if start in code:
        labels[start] = "START"
    code_bytes = sum(code.values())

    lines = [
        f"; Disassembled from the Intel HEX file {name}",
        f"; {total} bytes in {len(runs)} block(s): {code_bytes} bytes of code found by following",
        "; the jumps, calls and restarts from the start address and the interrupt vectors;",
        "; the other bytes are data (DB). Code reached only through PCHL or self-modifying",
        "; code cannot be found this way and also appears as data.",
        "",
    ]
    for block_start, block in runs:
        lines.append(f"        ORG {_hex(block_start, 4)}")
        offset = 0
        while offset < len(block):
            address = block_start + offset
            if address in code:
                size = code[address]
                chunk = block[offset:offset + size]
                b1 = chunk[1] if size > 1 else 0
                imm16 = (chunk[2] << 8 | chunk[1]) if size > 2 else b1
                text = disassemble_opcode(chunk[0], b1, imm16)
                op = chunk[0]
                if size == 3 and (op in _JUMPS or op in _CALLS) and imm16 in labels:
                    text = text[: text.rindex(_hex(imm16, 4))] + labels[imm16]
            else:
                # data: up to 8 bytes per line, up to the next instruction
                end = offset
                while end < len(block) and end - offset < 8 and (block_start + end) not in code:
                    end += 1
                chunk = block[offset:end]
                text = _db(chunk)
            label = f"{labels[address]}:" if address in labels else ""
            obj = " ".join(f"{b:02X}" for b in chunk)
            lines.append(f"{label:<8}{text:<24} ; {address:04X}: {obj}")
            offset += len(chunk)
        lines.append("")
    lines.append(f"        END {labels.get(start, _hex(start, 4))}")
    return "\n".join(lines) + "\n"
