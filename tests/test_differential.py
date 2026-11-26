"""
Differential testing: the simulator and an independently written reference
model (reference_8085.py) execute the same instructions from the same random
states, and must agree exactly on every register, every flag, all 64 KB of
memory, the output ports, the T-states, HALT, INTE, the interrupt masks and SOD.
"""

import random
import unittest

from helpers import Processor8085
from reference_8085 import Ref8085

REGS = ("A", "B", "C", "D", "E", "H", "L", "SP", "PC")


def random_pair(rng):
    memory = rng.randbytes(0x10000)
    regs = {name: rng.randrange(256) for name in "ABCDEHL"}
    regs["SP"] = rng.randrange(0x10000)
    regs["PC"] = rng.randrange(0x10000)
    flags = rng.randrange(256) & ~0x08  # bit 3 always reads 0
    inputs = rng.randbytes(256)

    cpu = Processor8085()
    cpu.memory = bytearray(memory)
    cpu.registers.update(regs)
    cpu.set_flags_byte(flags)
    cpu.input_ports = bytearray(inputs)
    ref = Ref8085(memory, regs, flags, inputs)
    return cpu, ref


def state(cpu):
    return (
        {name: cpu.registers[name] for name in REGS},
        cpu.get_flags_byte(),
        cpu.t_states,
        cpu.halted,
        cpu.interrupt_enable,
        cpu.interrupt_masks,
        cpu.sod,
    )


def ref_state(ref):
    return ({name: ref.r[name] for name in REGS}, ref.flags_byte(), ref.t, ref.halted, ref.inte, ref.masks, ref.sod)


class Differential(unittest.TestCase):
    def compare(self, cpu, ref, context):
        self.assertEqual(state(cpu), ref_state(ref), context)
        if cpu.memory != ref.m:
            diff = next(a for a in range(0x10000) if cpu.memory[a] != ref.m[a])
            self.fail(f"{context}: memory differs at {diff:04X}H ({cpu.memory[diff]:02X}H vs {ref.m[diff]:02X}H)")
        self.assertEqual(bytes(cpu.output_ports), bytes(ref.out), context)

    def test_every_opcode_from_random_states(self):
        rng = random.Random(80851)
        for op in range(256):
            for trial in range(150):
                cpu, ref = random_pair(rng)
                pc = cpu.registers["PC"]
                cpu.memory[pc] = op
                ref.m[pc] = op
                cpu.step()
                ref.step()
                self.compare(cpu, ref, f"opcode {op:02X}H, trial {trial}")

    def test_random_programs(self):
        """Long runs through random memory: every instruction mix, flags carried between instructions."""
        rng = random.Random(2026)
        for program in range(60):
            cpu, ref = random_pair(rng)
            for step in range(2000):
                cpu.step()
                ref.step()
                if step % 50 == 0 or cpu.halted:
                    self.compare(cpu, ref, f"program {program}, step {step}")
                if cpu.halted:
                    break
            self.compare(cpu, ref, f"program {program} end")

    def test_programs_biased_towards_arithmetic(self):
        """Random ALU-heavy code (ALU, DAA, rotates, INR/DCR, DAD, DSUB) with frequent comparisons."""
        rng = random.Random(7)
        alu_ops = ([0x80 | i for i in range(64)] + [0xC6, 0xCE, 0xD6, 0xDE, 0xE6, 0xEE, 0xF6, 0xFE]
                   + [0x27, 0x07, 0x0F, 0x17, 0x1F, 0x2F, 0x37, 0x3F, 0x08, 0x10, 0x18]
                   + [0x04 | (r << 3) for r in range(8)] + [0x05 | (r << 3) for r in range(8)]
                   + [0x09, 0x19, 0x29, 0x39, 0x03, 0x13, 0x23, 0x33, 0x0B, 0x1B, 0x2B, 0x3B])
        for program in range(40):
            cpu, ref = random_pair(rng)
            start = 0x1000
            for i in range(3000):
                op = rng.choice(alu_ops)
                operand = rng.randrange(256)
                for model in (cpu.memory, ref.m):
                    model[start + i * 2] = op
                    model[start + i * 2 + 1] = operand
            cpu.registers["PC"] = ref.r["PC"] = start
            for step in range(2500):
                cpu.step()
                ref.step()
                self.compare(cpu, ref, f"ALU program {program}, step {step}")


if __name__ == "__main__":
    unittest.main()
