"""
8085 interrupt system: TRAP, RST 7.5, RST 6.5, RST 5.5, INTR, EI/DI, SIM/RIM,
HALT wake-up and RESET, following the Intel 8085A interrupt structure:

    VALID INT = TRAP + INTE.(INTR + R7.5.!M7.5 + RST6.5.!M6.5 + RST5.5.!M5.5)
"""

import unittest

from helpers import Processor8085, assemble

# Interrupt service routines at the hardware vectors. Each increments a
# counter in memory (TRAP 3000H, 7.5 3001H, 6.5 3002H, 5.5 3003H, RST 5 3004H)
# and returns with EI; RET. The main program starts at 2000H.
VECTORS = """
ORG 0024H           ; TRAP (vectors are only 4 bytes apart: each holds a JMP)
    JMP ISR_TRAP
ORG 0028H           ; RST 5 (used by INTR)
    JMP ISR_RST5
ORG 002CH           ; RST 5.5
    JMP ISR_55
ORG 0034H           ; RST 6.5
    JMP ISR_65
ORG 003CH           ; RST 7.5
    JMP ISR_75
ORG 0100H
ISR_TRAP: PUSH H
    LXI H, 3000H
    JMP COUNT
ISR_75: PUSH H
    LXI H, 3001H
    JMP COUNT
ISR_65: PUSH H
    LXI H, 3002H
    JMP COUNT
ISR_55: PUSH H
    LXI H, 3003H
    JMP COUNT
ISR_RST5: PUSH H
    LXI H, 3004H
    JMP COUNT
COUNT:
    INR M
    POP H
    EI
    RET
ORG 2050H
CALLED:             ; target of INTR with CALL 2050H
    MVI E, 77H
    EI
    RET
"""


def make_cpu(main_program):
    cpu = Processor8085()
    cpu.load_program(assemble(VECTORS + "ORG 2000H\nSTART:\n" + main_program + "\nEND START"))
    return cpu


def run_steps(cpu, count):
    for _ in range(count):
        if cpu.step() == "ERROR":
            raise AssertionError(cpu.error)


def counts(cpu):
    return list(cpu.memory[0x3000:0x3005])


LOOP = "LXI SP, 4000H\n{setup}\nIDLE: JMP IDLE"


class TrapTests(unittest.TestCase):
    def test_trap_is_non_maskable(self):
        cpu = make_cpu(LOOP.format(setup="DI"))  # interrupts disabled, masks set
        run_steps(cpu, 3)
        cpu.set_pin("TRAP", 1)
        cpu.step()
        self.assertEqual(cpu.last_interrupt, "TRAP")
        self.assertEqual(cpu.registers["PC"], 0x0024)
        self.assertEqual(cpu.registers["SP"], 0x3FFE)
        return_address = cpu.memory[0x3FFE] | (cpu.memory[0x3FFF] << 8)
        self.assertEqual(return_address, 0x2004)  # JMP IDLE
        run_steps(cpu, 20)
        self.assertEqual(counts(cpu), [1, 0, 0, 0, 0])

    def test_trap_needs_edge_and_level(self):
        cpu = make_cpu(LOOP.format(setup="NOP"))
        run_steps(cpu, 2)
        cpu.set_pin("TRAP", 1)
        cpu.set_pin("TRAP", 0)  # edge seen, but the level is gone before it is sampled
        run_steps(cpu, 10)
        self.assertEqual(counts(cpu)[0], 0)
        cpu.set_pin("TRAP", 1)
        run_steps(cpu, 10)
        self.assertEqual(counts(cpu)[0], 1)

    def test_trap_held_high_is_recognized_once(self):
        cpu = make_cpu(LOOP.format(setup="NOP"))
        run_steps(cpu, 2)
        cpu.set_pin("TRAP", 1)
        run_steps(cpu, 50)
        self.assertEqual(counts(cpu)[0], 1)
        cpu.set_pin("TRAP", 0)
        cpu.set_pin("TRAP", 1)  # new rising edge
        run_steps(cpu, 50)
        self.assertEqual(counts(cpu)[0], 2)

    def test_trap_auto_release(self):
        cpu = make_cpu(LOOP.format(setup="NOP"))
        cpu.set_pin("TRAP", 1, auto_release=True)
        cpu.step()
        self.assertEqual(cpu.last_interrupt, "TRAP")
        self.assertEqual(cpu.pins["TRAP"], 0)

    def test_trap_clears_inte_and_rim_reports_previous_state(self):
        program = "LXI SP, 4000H\nEI\nIDLE: JMP IDLE"
        cpu = Processor8085()
        cpu.load_program(assemble(
            "ORG 0024H\nRIM\nMOV B, A\nRIM\nMOV C, A\nHLT\n" + "ORG 2000H\n" + program + "\nEND 2000H"
        ))
        run_steps(cpu, 3)
        self.assertEqual(cpu.interrupt_enable, 1)
        cpu.set_pin("TRAP", 1)
        cpu.step()
        self.assertEqual(cpu.interrupt_enable, 0)
        while cpu.step() == "OK":
            pass
        self.assertEqual(cpu.registers["B"] & 0x08, 0x08)  # first RIM: INTE before the TRAP
        self.assertEqual(cpu.registers["C"] & 0x08, 0x00)  # later RIM: current INTE


class RestartInterruptTests(unittest.TestCase):
    def test_rst75_is_edge_triggered_and_remembered(self):
        cpu = make_cpu(LOOP.format(setup="DI"))
        run_steps(cpu, 2)
        cpu.pulse_rst75()  # arrives while interrupts are disabled
        run_steps(cpu, 10)
        self.assertEqual(counts(cpu)[1], 0)
        self.assertEqual(cpu.rim_value() & 0x40, 0x40)  # I7.5 pending
        # Enable and unmask 7.5: the remembered request is serviced
        cpu2 = make_cpu(LOOP.format(setup="MVI A, 0BH\nSIM\nEI"))
        run_steps(cpu2, 2)
        cpu2.pulse_rst75()
        run_steps(cpu2, 40)
        self.assertEqual(counts(cpu2)[1], 1)
        self.assertEqual(cpu2.rst75_ff, 0)

    def test_rst75_flip_flop_reset_by_sim(self):
        cpu = make_cpu(LOOP.format(setup="NOP"))
        cpu.pulse_rst75()
        run_steps(cpu, 3)
        self.assertEqual(cpu.rst75_ff, 1)
        cpu2 = make_cpu("LXI SP, 4000H\nMVI A, 10H\nSIM\nRIM\nHLT")
        cpu2.pulse_rst75()
        while cpu2.step() == "OK":
            pass
        self.assertEqual(cpu2.rst75_ff, 0)
        self.assertEqual(cpu2.registers["A"] & 0x40, 0)

    def test_masks_and_vectors(self):
        # Unmask 6.5 only (M7.5=1, M6.5=0, M5.5=1)
        cpu = make_cpu(LOOP.format(setup="MVI A, 0DH\nSIM\nEI"))
        run_steps(cpu, 4)
        cpu.set_pin("RST5.5", 1)
        cpu.pulse_rst75()
        run_steps(cpu, 30)
        self.assertEqual(counts(cpu), [0, 0, 0, 0, 0])  # both masked
        cpu.set_pin("RST6.5", 1)
        cpu.step()
        self.assertEqual((cpu.last_interrupt, cpu.registers["PC"]), ("RST6.5", 0x0034))

    def test_rst65_rst55_are_level_sensitive(self):
        cpu = make_cpu(LOOP.format(setup="MVI A, 08H\nSIM\nEI"))  # all unmasked
        run_steps(cpu, 5)  # LXI, MVI, SIM, EI and the instruction after EI
        cpu.set_pin("RST5.5", 1)
        cpu.step()
        self.assertEqual((cpu.last_interrupt, cpu.registers["PC"]), ("RST5.5", 0x002C))
        run_steps(cpu, 20)  # ISR ends with EI; RET while the pin is still high
        self.assertGreaterEqual(counts(cpu)[3], 2)  # level held high -> interrupts again
        cpu.set_pin("RST5.5", 0)
        before = counts(cpu)[3]
        run_steps(cpu, 30)
        self.assertLessEqual(counts(cpu)[3] - before, 1)  # at most the one already in progress

    def test_rim_shows_pins_even_when_masked(self):
        cpu = make_cpu("LXI SP, 4000H\nRIM\nHLT")
        cpu.set_pin("RST6.5", 1)
        cpu.set_pin("RST5.5", 1)
        cpu.sid = 1
        while cpu.step() == "OK":
            pass
        self.assertEqual(cpu.registers["A"], 0b10110111)  # SID, P6.5, P5.5, masks set, INTE=0


class IntrTests(unittest.TestCase):
    def test_intr_with_rst_instruction(self):
        cpu = make_cpu(LOOP.format(setup="EI"))
        run_steps(cpu, 3)
        cpu.set_intr_instruction([0xEF])  # RST 5
        cpu.set_pin("INTR", 1, auto_release=True)
        t_before = cpu.t_states
        cpu.step()
        self.assertEqual((cpu.last_interrupt, cpu.registers["PC"]), ("INTR", 0x0028))
        self.assertEqual(cpu.t_states - t_before, 12)
        self.assertEqual(cpu.pins["INTR"], 0)  # device released INTR on INTA
        run_steps(cpu, 20)
        self.assertEqual(counts(cpu)[4], 1)

    def test_intr_with_call_instruction(self):
        cpu = make_cpu(LOOP.format(setup="EI"))
        run_steps(cpu, 3)
        cpu.set_intr_instruction([0xCD, 0x50, 0x20])  # CALL 2050H
        cpu.set_pin("INTR", 1, auto_release=True)
        t_before = cpu.t_states
        cpu.step()
        self.assertEqual(cpu.registers["PC"], 0x2050)
        self.assertEqual(cpu.t_states - t_before, 18)
        run_steps(cpu, 5)
        self.assertEqual(cpu.registers["E"], 0x77)

    def test_intr_ignores_masks_but_needs_inte(self):
        cpu = make_cpu(LOOP.format(setup="DI"))
        cpu.set_pin("INTR", 1)
        run_steps(cpu, 20)
        self.assertEqual(counts(cpu)[4], 0)
        cpu = make_cpu(LOOP.format(setup="MVI A, 0FH\nSIM\nEI"))  # all RST masks set
        cpu.set_intr_instruction([0xEF])
        cpu.set_pin("INTR", 1, auto_release=True)
        run_steps(cpu, 30)
        self.assertEqual(counts(cpu)[4], 1)

    def test_invalid_inta_instruction(self):
        # any instruction except EI and DI may be supplied (MCS-80/85 User's Manual 2.3.4)
        with self.assertRaises(ValueError):
            Processor8085().set_intr_instruction([0xFB])
        Processor8085().set_intr_instruction([0x00])  # NOP is allowed


class EnableAndPriorityTests(unittest.TestCase):
    def test_ei_takes_effect_after_next_instruction(self):
        cpu = make_cpu("LXI SP, 4000H\nEI\nMVI B, 1\nMVI C, 2\nIDLE: JMP IDLE")
        cpu.set_intr_instruction([0xEF])
        cpu.set_pin("INTR", 1, auto_release=True)
        cpu.step()  # LXI
        cpu.step()  # EI
        cpu.step()  # MVI B: still executes (EI delay)
        self.assertIsNone(cpu.last_interrupt)
        self.assertEqual(cpu.registers["B"], 1)
        cpu.step()  # interrupt is accepted now, before MVI C
        self.assertEqual(cpu.last_interrupt, "INTR")
        self.assertEqual(cpu.memory[0x3FFE] | (cpu.memory[0x3FFF] << 8), 0x2006)

    def test_ei_ret_returns_before_next_interrupt(self):
        # The ISR's EI; RET must return to the main program before a pending
        # level-triggered interrupt is taken again (stack must not grow).
        cpu = make_cpu(LOOP.format(setup="MVI A, 08H\nSIM\nEI"))
        cpu.set_pin("RST6.5", 1)
        run_steps(cpu, 200)
        self.assertGreaterEqual(cpu.registers["SP"], 0x3FFC)

    def test_acknowledge_disables_interrupts(self):
        cpu = make_cpu("LXI SP, 4000H\nMVI A, 08H\nSIM\nEI\nIDLE: JMP IDLE")
        run_steps(cpu, 5)
        cpu.set_pin("RST5.5", 1)
        cpu.step()
        self.assertEqual(cpu.interrupt_enable, 0)

    def test_priority_order(self):
        cpu = make_cpu(LOOP.format(setup="MVI A, 08H\nSIM\nEI"))
        run_steps(cpu, 5)
        cpu.set_intr_instruction([0xEF])
        cpu.set_pin("INTR", 1, auto_release=True)
        cpu.set_pin("RST5.5", 1, auto_release=False)
        cpu.set_pin("RST6.5", 1)
        cpu.pulse_rst75()
        cpu.set_pin("TRAP", 1, auto_release=True)
        order = []
        for _ in range(400):
            cpu.step()
            if cpu.last_interrupt:
                order.append(cpu.last_interrupt)
                # the device behind each level-triggered input drops its request
                if cpu.last_interrupt in ("RST6.5", "RST5.5"):
                    cpu.set_pin(cpu.last_interrupt, 0)
        self.assertEqual(order, ["TRAP", "RST7.5", "RST6.5", "RST5.5", "INTR"])
        self.assertEqual(counts(cpu), [1, 1, 1, 1, 1])


class HaltTests(unittest.TestCase):
    def test_interrupt_wakes_halted_cpu(self):
        cpu = make_cpu("LXI SP, 4000H\nMVI A, 08H\nSIM\nEI\nHLT\nMVI B, 55H\nHLT")
        status = None
        for _ in range(10):
            status = cpu.step()
        self.assertEqual(status, "HALT")
        self.assertTrue(cpu.halted)
        cpu.set_pin("RST6.5", 1)
        self.assertEqual(cpu.step(), "OK")  # wakes and enters the ISR
        self.assertFalse(cpu.halted)
        self.assertEqual(cpu.memory[0x3FFE] | (cpu.memory[0x3FFF] << 8), 0x2008)  # after HLT
        cpu.set_pin("RST6.5", 0)
        while cpu.step() == "OK":
            pass
        self.assertEqual(cpu.registers["B"], 0x55)
        self.assertEqual(counts(cpu)[2], 1)

    def test_halt_with_interrupts_disabled_only_wakes_on_trap(self):
        cpu = make_cpu("LXI SP, 4000H\nHLT\nMVI B, 1\nHLT")
        cpu.step()
        cpu.step()
        self.assertTrue(cpu.halted)
        self.assertFalse(cpu.can_resume())
        cpu.set_pin("RST5.5", 1)
        cpu.set_pin("INTR", 1)
        self.assertEqual(cpu.step(), "HALT")
        cpu.set_pin("TRAP", 1, auto_release=True)
        self.assertTrue(cpu.can_resume())
        self.assertEqual(cpu.step(), "OK")
        self.assertEqual(cpu.registers["PC"], 0x0024)

    def test_ei_hlt_idiom(self):
        # EI; HLT waits for an interrupt even though EI's delay covers HLT
        cpu = make_cpu("LXI SP, 4000H\nEI\nHLT\nMVI B, 1\nHLT")
        cpu.set_intr_instruction([0xEF])
        run_steps(cpu, 4)
        self.assertTrue(cpu.halted)
        cpu.set_pin("INTR", 1, auto_release=True)
        run_steps(cpu, 30)
        self.assertEqual((counts(cpu)[4], cpu.registers["B"]), (1, 1))


class ResetTests(unittest.TestCase):
    def test_reset_state(self):
        cpu = make_cpu("LXI SP, 4000H\nMVI A, 0C8H\nSIM\nEI\nIDLE: JMP IDLE")
        run_steps(cpu, 6)
        cpu.pulse_rst75()
        cpu.set_pin("TRAP", 1)
        cpu.set_pin("TRAP", 0)
        self.assertEqual((cpu.interrupt_enable, cpu.interrupt_masks, cpu.sod), (1, 0, 1))
        cpu.registers["B"] = 0x12
        cpu.memory[0x5000] = 0x34
        cpu.reset()
        self.assertEqual(cpu.registers["PC"], 0x2000)
        self.assertEqual((cpu.interrupt_enable, cpu.interrupt_masks, cpu.rst75_ff, cpu.trap_ff, cpu.sod),
                         (0, 0b111, 0, 0, 0))
        self.assertEqual((cpu.registers["B"], cpu.memory[0x5000]), (0x12, 0x34))  # kept

    def test_power_on_state(self):
        cpu = Processor8085()
        self.assertEqual(cpu.rim_value(), 0x07)  # masks set, INTE clear, nothing pending


class InterruptDrivenProgramTests(unittest.TestCase):
    def test_counts_rst75_pulses_while_main_program_runs(self):
        cpu = make_cpu("LXI SP, 4000H\nMVI A, 0BH\nSIM\nEI\nMVI D, 0\nLOOP: INR D\nJMP LOOP")
        for _ in range(3):
            run_steps(cpu, 25)
            cpu.pulse_rst75()
        run_steps(cpu, 25)
        self.assertEqual(counts(cpu)[1], 3)
        self.assertGreater(cpu.registers["D"], 0)
        self.assertEqual(cpu.registers["SP"], 0x4000)
        self.assertEqual([entry[0] for entry in cpu.interrupt_log], ["RST7.5"] * 3)


if __name__ == "__main__":
    unittest.main()


class SamplingInNextToLastClock(unittest.TestCase):
    """Intel: interrupts are sampled during the next-to-last clock cycle of an instruction."""

    SOURCE = "\n".join([
        "ORG 0034H", "MVI C, 65H", "HLT",
        "ORG 002CH", "MVI C, 55H", "HLT",
        "ORG 2000H", "LXI SP, 3000H", "MVI A, 08H", "SIM", "EI", "NOP",
        "NOP", "NOP", "NOP", "HLT",  # 2008H: the interrupts arrive during these NOPs
        "END 2000H",
    ])

    def cpu_at_first_nop(self):
        cpu = Processor8085()
        cpu.load_program(assemble(self.SOURCE))
        for _ in range(5):  # LXI, MVI, SIM, EI, NOP (EI delay over)
            cpu.step()
        self.assertEqual(cpu.registers["PC"], 0x2008)
        return cpu

    def test_request_in_the_last_clock_waits_one_instruction(self):
        cpu = self.cpu_at_first_nop()
        t_end = cpu.t_states  # the instruction that just finished ended here
        cpu.set_pin("RST6.5", 1, at=t_end - 1)  # its last clock cycle: after the sample
        self.assertIsNone(cpu.pending_interrupt(sampled=True))
        self.assertEqual(cpu.peek_t_states(), 4)  # the next NOP runs first
        cpu.step()
        self.assertIsNone(cpu.last_interrupt)
        self.assertEqual(cpu.registers["PC"], 0x2009)
        self.assertEqual(cpu.peek_t_states(), 12)
        cpu.step()
        self.assertEqual(cpu.last_interrupt, "RST6.5")
        self.assertEqual(cpu.interrupt_log[-1][1], 0x2009)  # return address after that NOP

    def test_request_before_the_sample_is_taken_after_the_instruction(self):
        cpu = self.cpu_at_first_nop()
        cpu.set_pin("RST6.5", 1, at=cpu.t_states - 2)  # in the next-to-last clock: sampled
        cpu.step()
        self.assertEqual(cpu.last_interrupt, "RST6.5")
        self.assertEqual(cpu.interrupt_log[-1][1], 0x2008)

    def test_request_without_a_time_is_seen_at_once(self):
        cpu = self.cpu_at_first_nop()
        cpu.set_pin("RST6.5", 1)  # e.g. set between steps with the clock stopped
        cpu.step()
        self.assertEqual(cpu.last_interrupt, "RST6.5")

    def test_halt_samples_on_every_clock(self):
        cpu = self.cpu_at_first_nop()
        for _ in range(4):
            cpu.step()  # three NOPs and HLT
        self.assertTrue(cpu.halted)
        cpu.idle(50)
        t_request = cpu.t_states
        cpu.set_pin("RST6.5", 1, at=t_request)
        # MCS-80/85 User's Manual: sampled during a THALT state, the CPU enters
        # M1.T1 at the end of the next clock period - two T-states later
        self.assertEqual(cpu.step(), "HALT")
        self.assertEqual(cpu.idle(1000), 2)
        cpu.step()
        self.assertEqual(cpu.last_interrupt, "RST6.5")
        self.assertEqual(cpu.t_states, t_request + 2 + 12)

    def test_lower_priority_request_already_sampled_wins(self):
        cpu = self.cpu_at_first_nop()
        cpu.set_pin("RST5.5", 1, at=cpu.t_states - 3)  # sampled
        cpu.set_pin("RST6.5", 1, at=cpu.t_states)  # higher priority, but too late
        cpu.step()
        self.assertEqual(cpu.last_interrupt, "RST5.5")


class IntrSuppliesAnyInstruction(unittest.TestCase):
    """MCS-80/85 User's Manual 2.3.4: any instruction except EI or DI can be supplied during INTA."""

    def cpu(self, data):
        cpu = Processor8085()
        cpu.load_program(assemble("ORG 2000H\nLXI SP, 3000H\nEI\nNOP\nNOP\nHLT\nEND 2000H"))
        for _ in range(3):
            cpu.step()
        cpu.trace_bus = True
        cpu.set_intr_instruction(data)
        cpu.set_pin("INTR", 1, auto_release=True)
        return cpu

    def test_rst_and_call_unchanged(self):
        cpu = self.cpu((0xEF,))  # RST 5
        before = cpu.t_states
        cpu.step()
        self.assertEqual((cpu.registers["PC"], cpu.t_states - before), (0x0028, 12))
        cpu = self.cpu((0xCD, 0x00, 0x30))
        before = cpu.t_states
        cpu.step()
        self.assertEqual((cpu.registers["PC"], cpu.t_states - before), (0x3000, 18))
        self.assertEqual([c.kind for c in cpu.bus_cycles], ["INA", "INA", "INA", "MW", "MW"])

    def test_other_instructions_execute_with_the_pc_held(self):
        cpu = self.cpu((0x3E, 0x55))  # MVI A, 55H
        pc = cpu.registers["PC"]
        before = cpu.t_states
        cpu.step()
        self.assertEqual(cpu.registers["A"], 0x55)
        self.assertEqual(cpu.registers["PC"], pc)  # not incremented: the program continues
        self.assertEqual(cpu.t_states - before, 7)
        self.assertEqual([(c.kind, c.t_states, c.address, c.data) for c in cpu.bus_cycles],
                         [("INA", 4, pc, 0x3E), ("INA", 3, pc, 0x55)])
        self.assertEqual(cpu.interrupt_enable, 0)

    def test_jmp_and_ei_di_rules(self):
        cpu = self.cpu((0xC3, 0x34, 0x12))
        cpu.step()
        self.assertEqual(cpu.registers["PC"], 0x1234)
        for bad in ((0xFB,), (0xF3,), (0xCD, 0x00), (0x3E,)):
            with self.assertRaises(ValueError):
                Processor8085().set_intr_instruction(bad)
