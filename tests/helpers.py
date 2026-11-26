"""Shared helpers for the Neo8085 test suite."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from assembler import Assembler8085  # noqa: E402
from processor import Processor8085  # noqa: E402


def assemble(source):
    """Assemble a multi-line source string."""
    return Assembler8085().assemble(source.strip("\n").splitlines())


def run(source, max_steps=10000):
    """Assemble and run a program until HLT/ERROR. Returns (processor, status)."""
    processor = Processor8085()
    processor.load_program(assemble(source))
    status = "OK"
    for _ in range(max_steps):
        status = processor.step()
        if status != "OK":
            break
    return processor, status


def pair(processor, name):
    r = processor.registers
    return (r[name[0]] << 8) | r[name[1]]


# ----------------------------------------------------------------------
# Independent reference models
# ----------------------------------------------------------------------

def ripple_add(a, b, carry_in):
    """
    Bit-by-bit ripple-carry adder, the way the 8085 ALU is built.
    Returns (8-bit result, carry out of bit 3, carry out of bit 7, carry into bit 7).
    """
    carry = carry_in
    result = 0
    carry3 = 0
    carry_into7 = 0
    for bit in range(8):
        x = (a >> bit) & 1
        y = (b >> bit) & 1
        if bit == 7:
            carry_into7 = carry
        result |= (x ^ y ^ carry) << bit
        carry = (x & y) | (x & carry) | (y & carry)
        if bit == 3:
            carry3 = carry
    return result, carry3, carry, carry_into7


def parity_even(value):
    ones = 0
    for bit in range(8):
        ones += (value >> bit) & 1
    return 1 if ones % 2 == 0 else 0


def szp(value):
    return {"S": value >> 7, "Z": 1 if value == 0 else 0, "P": parity_even(value)}


def reference_alu(operation, a, b, carry):
    """
    Reference for ADD, ADC, SUB, SBB, ANA, XRA, ORA, CMP (operation 0-7).
    Returns (new accumulator, flags dict).
    Subtraction is A + ~B + !borrow; CY is the complemented carry, AC is not.
    Undocumented flags (Ken Shirriff's analysis of the 8085 silicon):
    V = carry into bit 7 XOR carry out of bit 7, K = V XOR S.
    """
    if operation in (0, 1):
        result, ac, cy, c7 = ripple_add(a, b, carry if operation == 1 else 0)
        flags = {**szp(result), "AC": ac, "C": cy, "V": c7 ^ cy}
    elif operation in (2, 3, 7):
        borrow = carry if operation == 3 else 0
        result, ac, cy, c7 = ripple_add(a, b ^ 0xFF, 1 - borrow)
        flags = {**szp(result), "AC": ac, "C": 1 - cy, "V": c7 ^ cy}
        if operation == 7:
            flags["K"] = flags["V"] ^ flags["S"]
            return a, flags
    else:
        result = {4: a & b, 5: a ^ b, 6: a | b}[operation]
        flags = {**szp(result), "AC": 1 if operation == 4 else 0, "C": 0, "V": 0}
    flags["K"] = flags["V"] ^ flags["S"]
    return result, flags


def signed(value):
    return value - 256 if value & 0x80 else value
