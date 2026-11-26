"""
Intel 8255A PPI and 8253 PIT, checked against the behaviour described in the
Intel data sheets, and their connection to the 8085 (I/O ports, CPU clock,
interrupt pins).
"""

import copy
import random
import unittest

from helpers import Processor8085, assemble
from peripherals import PPI8255, Counter8253, PeripheralBus, PIT8253

A, B, C, CTRL = 0, 1, 2, 3


# ======================================================================
# 8255
# ======================================================================


class PPIMode0(unittest.TestCase):
    def test_reset_state_is_all_inputs(self):
        ppi = PPI8255()
        self.assertEqual(ppi.control, 0x9B)
        ppi.set_pins(A, 0x12)
        ppi.set_pins(B, 0x34)
        ppi.set_pins(C, 0x56)
        self.assertEqual([ppi.read(p) for p in (A, B, C)], [0x12, 0x34, 0x56])
        self.assertEqual(ppi.port_pins(A), (0x12, 0x00))

    def test_all_sixteen_mode0_words(self):
        for word in range(0x80, 0xA0):
            if word & 0x64:  # only mode 0 for both groups
                continue
            ppi = PPI8255()
            ppi.write(CTRL, word)
            for port in (A, B, C):
                ppi.set_pins(port, 0xA5)
            ppi.write(A, 0x11)
            ppi.write(B, 0x22)
            ppi.write(C, 0x3C)
            a_in, cu_in, b_in, cl_in = word & 0x10, word & 0x08, word & 0x02, word & 0x01
            with self.subTest(word=f"{word:02X}H"):
                self.assertEqual(ppi.read(A), 0xA5 if a_in else 0x11)
                self.assertEqual(ppi.read(B), 0xA5 if b_in else 0x22)
                upper = (0xA5 if cu_in else 0x3C) & 0xF0
                lower = (0xA5 if cl_in else 0x3C) & 0x0F
                self.assertEqual(ppi.read(C), upper | lower)
                self.assertEqual(ppi.port_pins(A)[1], 0x00 if a_in else 0xFF)
                self.assertEqual(ppi.port_pins(C)[1], (0 if cu_in else 0xF0) | (0 if cl_in else 0x0F))

    def test_mode_set_clears_output_latches(self):
        ppi = PPI8255()
        ppi.write(CTRL, 0x80)
        ppi.write(A, 0xFF)
        ppi.write(C, 0xFF)
        ppi.write(CTRL, 0x80)
        self.assertEqual((ppi.read(A), ppi.read(C)), (0, 0))

    def test_bit_set_reset(self):
        ppi = PPI8255()
        ppi.write(CTRL, 0x80)  # all outputs
        for bit in range(8):
            ppi.write(CTRL, (bit << 1) | 1)
        self.assertEqual(ppi.read(C), 0xFF)
        ppi.write(CTRL, (5 << 1) | 0)  # reset PC5
        self.assertEqual(ppi.read(C), 0xDF)
        self.assertEqual(ppi.read(A), 0)  # BSR touches only port C

    def test_control_register_reads_floating_bus(self):
        self.assertEqual(PPI8255().read(CTRL), 0xFF)


class PPIMode1(unittest.TestCase):
    def test_port_a_strobed_input(self):
        ppi = PPI8255()
        ppi.write(CTRL, 0xB0)  # A mode 1 input, PC7-6 output, B mode 0 output
        self.assertEqual(ppi.c_roles()[3:6], ["INTR-A", "STB-A", "IBF-A"])
        self.assertTrue(ppi.strobe("A", 0x5A))
        self.assertEqual(ppi.read(C) & 0x38, 0x20)  # IBF = 1, INTE = 0, INTR = 0
        self.assertEqual(ppi.intr_a(), 0)
        ppi.write(CTRL, (4 << 1) | 1)  # INTE-A = 1 (BSR on PC4)
        self.assertEqual(ppi.read(C) & 0x38, 0x38)  # IBF, INTE, INTR
        self.assertEqual(ppi.intr_a(), 1)
        ppi.set_pins(A, 0xFF)  # data changes after the strobe: the latch keeps 5AH
        self.assertEqual(ppi.read(A), 0x5A)
        self.assertEqual(ppi.read(C) & 0x38, 0x10)  # RD cleared IBF and INTR, INTE stays
        self.assertEqual(ppi.intr_a(), 0)

    def test_port_b_strobed_output(self):
        ppi = PPI8255()
        ppi.write(CTRL, 0x84)  # B mode 1 output
        self.assertEqual(ppi.c_roles()[0:3], ["INTR-B", "OBF-B", "ACK-B"])
        ppi.write(CTRL, (2 << 1) | 1)  # INTE-B = 1 (PC2)
        self.assertEqual(ppi.intr_b(), 1)  # buffer empty and interrupt enabled
        ppi.write(B, 0xC3)
        self.assertEqual(ppi.read(C) & 0x07, 0x04)  # OBF pin low (bit 1 = 0), INTR 0, INTE 1
        self.assertEqual(ppi.port_pins(C)[0] & 0x02, 0)
        self.assertEqual(ppi.acknowledge("B"), 0xC3)
        self.assertEqual(ppi.read(C) & 0x07, 0x07)  # OBF high again, INTR = 1
        self.assertEqual(ppi.intr_b(), 1)

    def test_bsr_on_inte_bit_does_not_change_port_c_latch(self):
        ppi = PPI8255()
        ppi.write(CTRL, 0xA0)  # A mode 1 output, port C upper output
        ppi.write(CTRL, (6 << 1) | 1)  # PC6 = ACK-A position: sets INTE-A
        self.assertEqual(ppi.inte[0], 1)
        self.assertEqual(ppi.latch[2], 0)

    def test_handshake_refused_in_wrong_mode(self):
        ppi = PPI8255()
        self.assertFalse(ppi.strobe("A", 1))
        self.assertIsNone(ppi.acknowledge("B"))


class PPIMode2(unittest.TestCase):
    def test_bidirectional_port_a(self):
        ppi = PPI8255()
        ppi.write(CTRL, 0xC0)
        self.assertEqual(ppi.c_roles()[3:8], ["INTR-A", "STB-A", "IBF-A", "ACK-A", "OBF-A"])
        ppi.write(CTRL, (6 << 1) | 1)  # INTE1 (output)
        self.assertEqual(ppi.intr_a(), 1)  # output buffer empty
        ppi.write(A, 0x77)
        self.assertEqual(ppi.intr_a(), 0)
        self.assertEqual(ppi.port_pins(A)[1], 0x00)  # bus floats until ACK
        self.assertEqual(ppi.acknowledge("A"), 0x77)
        self.assertEqual(ppi.intr_a(), 1)
        ppi.write(CTRL, (6 << 1) | 0)
        ppi.write(CTRL, (4 << 1) | 1)  # INTE2 (input)
        ppi.strobe("A", 0x99)
        self.assertEqual(ppi.intr_a(), 1)
        self.assertEqual(ppi.read(C) & 0xF8, 0x80 | 0x20 | 0x10 | 0x08)  # OBF high, IBF, INTE2, INTR
        self.assertEqual(ppi.read(A), 0x99)
        self.assertEqual(ppi.intr_a(), 0)


# ======================================================================
# 8253
# ======================================================================


def counter(mode, count, rw=3, bcd=False):
    c = Counter8253(0)
    c.control_word((rw << 4) | (mode << 1) | int(bcd))
    if rw in (1, 3):
        c.write(count & 0xFF)
    if rw in (2, 3):
        c.write(count >> 8)
    return c


def outs(c, pulses):
    levels = []
    for _ in range(pulses):
        c.clock(1)
        levels.append(c.out)
    return "".join(map(str, levels))


class PITModes(unittest.TestCase):
    """OUT after each CLK pulse; the first pulse after writing the count loads it."""

    def test_mode0_interrupt_on_terminal_count(self):
        c = counter(0, 4)
        self.assertEqual(c.out, 0)
        self.assertEqual(outs(c, 7), "0000111")  # high N + 1 pulses after the count is written
        c = counter(0, 4)
        c.set_gate(0)
        self.assertEqual(outs(c, 4), "0000")  # loaded, but GATE low holds the count
        c.set_gate(1)
        self.assertEqual(outs(c, 4), "0001")

    def test_mode0_new_count_restarts(self):
        c = counter(0, 3)
        outs(c, 2)
        c.write(5)  # first byte stops counting, OUT low
        self.assertEqual(outs(c, 3), "000")
        c.write(0)
        self.assertEqual(outs(c, 7), "0000011")

    def test_mode1_retriggerable_one_shot(self):
        c = counter(1, 3)
        self.assertEqual(outs(c, 3), "111")  # waits for a GATE trigger
        c.set_gate(0)
        c.set_gate(1)
        self.assertEqual(outs(c, 6), "000111")  # low for N pulses after the trigger pulse
        c.set_gate(0)
        c.set_gate(1)
        self.assertEqual(outs(c, 2), "00")
        c.set_gate(0)
        c.set_gate(1)  # retrigger while running: starts again
        self.assertEqual(outs(c, 4), "0001")

    def test_mode2_rate_generator(self):
        c = counter(2, 3)
        self.assertEqual(outs(c, 10), "1101101101")  # low for one pulse every N
        c.set_gate(0)
        self.assertEqual(c.out, 1)  # GATE low forces OUT high
        self.assertEqual(outs(c, 3), "111")
        c.set_gate(1)  # reload on the next pulse
        self.assertEqual(outs(c, 4), "1101")

    def test_mode3_square_wave(self):
        self.assertEqual(outs(counter(3, 4), 9), "110011001")
        self.assertEqual(outs(counter(3, 5), 11), "11100111001")  # high (N+1)/2, low (N-1)/2

    def test_mode3_new_count_at_half_cycle(self):
        c = counter(3, 4)
        outs(c, 2)  # load + first pulse of the high half
        c.write(6)
        c.write(0)
        self.assertEqual(outs(c, 8), "00011100")  # the high half ends as before, then halves of 3

    def test_mode4_software_strobe(self):
        c = counter(4, 3)
        self.assertEqual(outs(c, 7), "1110111")  # low for one pulse N + 1 pulses after writing

    def test_mode5_hardware_strobe(self):
        c = counter(5, 2)
        self.assertEqual(outs(c, 3), "111")
        c.set_gate(0)
        c.set_gate(1)
        self.assertEqual(outs(c, 5), "11011")

    def test_count_zero_is_maximum(self):
        c = counter(2, 0)
        used, rising, falling = c.clock(1 + 65536 * 3)
        self.assertEqual((rising, falling), (3, 3))
        c = counter(2, 0, bcd=True)
        used, rising, falling = c.clock(1 + 10000 * 2)
        self.assertEqual((rising, falling), (2, 2))


class PITMode3ReadBack(unittest.TestCase):
    """
    Intel 8253 data sheet, mode 3: "If the count is odd and the output is high,
    the first clock pulse (after the count is loaded) decrements the count by 1.
    Subsequent clock pulses decrement the clock by 2. After timeout, the output
    goes low and the full count is reloaded. The first clock pulse (following
    the reload) decrements the counter by 3. Subsequent clock pulses decrement
    the count by 2 until timeout."
    """

    def sequence(self, count, pulses):
        c = counter(3, count)
        out = []
        for _ in range(pulses):
            c.clock(1)
            out.append((c.out, c.value()))
        return out

    def test_odd_count(self):
        self.assertEqual(self.sequence(7, 14), [
            (1, 7), (1, 6), (1, 4), (1, 2),  # load, -1, -2, -2
            (0, 7), (0, 4), (0, 2),  # timeout: low, reload; -3, -2
            (1, 7), (1, 6), (1, 4), (1, 2), (0, 7), (0, 4), (0, 2),
        ])

    def test_even_count(self):
        self.assertEqual(self.sequence(4, 8), [(1, 4), (1, 2), (0, 4), (0, 2)] * 2)

    def test_bcd(self):
        c = counter(3, 0x0009, bcd=True)
        values = []
        for _ in range(5):
            c.clock(1)
            values.append(c.value())
        self.assertEqual(values, [0x09, 0x08, 0x06, 0x04, 0x02])


class PITWarnings(unittest.TestCase):
    def test_count_of_one_in_mode_2_is_flagged(self):
        c = counter(2, 1)
        self.assertIn("illegal in mode 2", c.warning)
        self.assertIsNone(counter(2, 2).warning)
        self.assertIsNone(counter(3, 1).warning)


class PITReadWrite(unittest.TestCase):
    def test_read_lsb_msb_and_latch(self):
        c = counter(0, 0x1234)
        c.clock(1 + 0x34)  # load + 34H pulses
        self.assertEqual((c.read(), c.read()), (0x00, 0x12))
        c.control_word(0x00)  # counter latch command
        c.clock(5)
        self.assertEqual((c.read(), c.read()), (0x00, 0x12))  # latched value
        self.assertEqual((c.read(), c.read()), (0xFB, 0x11))  # live again

    def test_lsb_only_and_msb_only(self):
        c = counter(0, 0x40, rw=1)
        c.clock(1)
        self.assertEqual(c.ce, 0x40)
        self.assertEqual(c.read(), 0x40)
        c = counter(0, 0x0500, rw=2)
        c.clock(1)
        self.assertEqual(c.ce, 0x0500)
        self.assertEqual(c.read(), 0x05)

    def test_bcd(self):
        c = counter(0, 0x0100, bcd=True)  # 100 decimal
        c.clock(1 + 1)
        self.assertEqual((c.read(), c.read()), (0x99, 0x00))  # 99 in BCD
        c.clock(99)
        self.assertEqual(c.out, 1)

    def test_illegal_select_and_control_read(self):
        pit = PIT8253()
        pit.write(3, 0xF6)  # SC = 11: read-back exists only on the 8254
        self.assertTrue(all(c.mode is None for c in pit.counters))
        self.assertEqual(pit.read(3), 0xFF)

    def test_bulk_clocking_matches_pulse_by_pulse(self):
        rng = random.Random(8253)
        for _ in range(400):
            mode = rng.randrange(6)
            count = rng.choice([2, 3, 4, 5, 7, 10, 16, 33, 100, rng.randrange(2, 300)])
            fast = counter(mode, count, bcd=rng.random() < 0.2 and count < 10000)
            slow = copy.deepcopy(fast)
            for _ in range(rng.randrange(1, 6)):
                n = rng.randrange(0, 2000)
                _, r1, f1 = fast.clock(n)
                r2 = f2 = 0
                for _ in range(n):
                    before = slow.out
                    slow.clock(1)
                    r2 += int(slow.out and not before)
                    f2 += int(before and not slow.out)
                self.assertEqual((r1, f1), (r2, f2), (mode, count, n))
                self.assertEqual((fast.out, fast.value()), (slow.out, slow.value()), (mode, count, n))
                action = rng.random()
                if action < 0.2:
                    level = rng.randrange(2)
                    fast.set_gate(level)
                    slow.set_gate(level)
                elif action < 0.3:
                    new = rng.randrange(2, 200)
                    for c in (fast, slow):
                        c.write(new & 0xFF)
                        c.write(new >> 8)


# ======================================================================
# Connected to the 8085
# ======================================================================


def system(source, wiring=None):
    cpu = Processor8085()
    cpu.load_program(assemble(source))
    bus = PeripheralBus(ppi_base=0x40, pit_base=0x50)
    for name, pin in (wiring or {}).items():
        bus.wiring[name] = pin
    bus.attach(cpu)
    return cpu, bus


def run(cpu, steps=100000, idle=1000):
    for _ in range(steps):
        status = cpu.step()
        if status == "HALT":
            if not cpu.can_resume():
                return status
            cpu.idle(idle)
        elif status != "OK":
            return status
    return "OK"


class Connected(unittest.TestCase):
    def test_8255_through_in_and_out(self):
        cpu, bus = system("MVI A, 90H\nOUT 43H\nMVI A, 5AH\nOUT 41H\nIN 40H\nMOV B, A\nIN 43H\nHLT")
        bus.ppi.set_pins(A, 0xC3)
        run(cpu)
        self.assertEqual(bus.ppi.port_pins(B), (0x5A, 0xFF))  # B output mode 0
        self.assertEqual(cpu.registers["B"], 0xC3)  # A input
        self.assertEqual(cpu.registers["A"], 0xFF)  # control register is not readable
        self.assertEqual(cpu.output_ports[0x41], 0x5A)  # the port table still shows the write

    def test_bus_cycle_shows_the_byte_from_the_chip(self):
        cpu, bus = system("IN 40H\nHLT")
        cpu.trace_bus = True
        bus.ppi.set_pins(A, 0x81)
        cpu.step()
        self.assertEqual((cpu.bus_cycles[-1].kind, cpu.bus_cycles[-1].data), ("IOR", 0x81))

    def test_counter_read_back_is_exact_to_the_t_state(self):
        # MVI 7, OUT 10 (control); MVI 7, OUT 10 (LSB); MVI 7, OUT 10 (MSB at T = 41 + 7)
        source = "\n".join([
            "MVI A, 30H", "OUT 53H",  # counter 0, LSB then MSB, mode 0, binary
            "MVI A, 0E8H", "OUT 50H",
            "MVI A, 03H", "OUT 50H",  # count 1000 written in the I/O cycle of this OUT
            "NOP", "NOP",
            "MVI A, 00H", "OUT 53H",  # counter latch command
            "IN 50H", "MOV L, A", "IN 50H", "MOV H, A", "HLT",
        ])
        cpu, bus = system(source)
        run(cpu)
        t_write = 7 + 10 + 7 + 10 + 7 + 10  # trailing edge of WR (end of T3 of the I/O write cycle) of the MSB
        t_latch = 7 + 10 + 7 + 10 + 7 + 10 + 4 + 4 + 7 + 10
        pulses = t_latch - t_write
        expected = 1000 - (pulses - 1)  # the first pulse loads the count
        self.assertEqual((cpu.registers["H"] << 8) | cpu.registers["L"], expected)

    def test_timer_interrupt_rate(self):
        # Counter 0: mode 2, count 500 clocked by CLK OUT, OUT0 -> RST 7.5
        source = "\n".join([
            "ORG 003CH", "INR B", "EI", "RET",
            "ORG 2000H",
            "START: LXI SP, 3000H",
            "MVI A, 34H", "OUT 53H",  # counter 0, LSB/MSB, mode 2 (OUT0 goes high)
            "MVI A, 0F4H", "OUT 50H", "MVI A, 01H", "OUT 50H",  # 500
            "MVI A, 1BH", "SIM",  # clear the R7.5 latch and unmask RST 7.5
            "MVI B, 0", "EI",
            "WAIT: HLT", "JMP WAIT",
            "END START",
        ])
        cpu, bus = system(source, {"OUT0": "RST7.5"})
        times = []
        for _ in range(20000):
            status = cpu.step()
            if cpu.last_interrupt == "RST7.5":
                times.append(cpu.t_states)
            if status == "HALT":
                cpu.idle(100000)
            if len(times) == 6:
                break
        gaps = {b - a for a, b in zip(times, times[1:])}
        self.assertEqual(gaps, {500})  # one interrupt per 500 T-states, to the T-state
        self.assertEqual(cpu.registers["B"], 5)

    def test_halt_wakes_at_the_exact_t_state(self):
        source = "\n".join([
            "ORG 0034H", "HLT",
            "ORG 2000H", "START: LXI SP, 3000H", "MVI A, 09H", "SIM",  # unmask RST 6.5
            "MVI A, 10H", "OUT 53H", "MVI A, 0C8H", "OUT 50H",  # counter 0 mode 0, LSB only: 200
            "EI", "HLT", "END START",
        ])
        cpu, bus = system(source, {"OUT0": "RST6.5"})
        t_write = 10 + 7 + 4 + 7 + 10 + 7 + 10  # WR trailing edge of the OUT that writes the count
        while cpu.step() != "HALT":
            pass
        used = cpu.idle(1_000_000)
        # OUT goes high N + 1 pulses after the write; the halted CPU leaves THALT
        # two T-states after that (MCS-80/85 User's Manual, Figure 2-20)
        self.assertEqual(cpu.t_states, t_write + 201 + 2)
        self.assertLess(used, 1_000_000)
        cpu.step()
        self.assertEqual(cpu.last_interrupt, "RST6.5")

    def test_8255_intr_drives_rst55(self):
        source = "\n".join([
            "ORG 002CH", "IN 40H", "MOV C, A", "EI", "RET",
            "ORG 2000H", "START: LXI SP, 3000H", "MVI A, 0EH", "SIM",  # unmask RST 5.5
            "MVI A, 0B0H", "OUT 43H",  # A mode 1 input
            "MVI A, 09H", "OUT 43H",  # INTE-A = 1 (PC4)
            "EI", "WAIT: HLT", "JMP WAIT", "END START",
        ])
        cpu, bus = system(source, {"INTR-A": "RST5.5"})
        while cpu.step() != "HALT":
            pass
        self.assertEqual(cpu.pins["RST5.5"], 0)
        bus.ppi.strobe("A", 0x6D)
        bus._after_access()
        self.assertEqual(cpu.pins["RST5.5"], 1)
        for _ in range(10):
            cpu.step()
        self.assertEqual(cpu.registers["C"], 0x6D)
        self.assertEqual(cpu.pins["RST5.5"], 0)  # reading port A cleared IBF and INTR

    def test_pin_sources_are_ored(self):
        cpu, bus = system("HLT", {"OUT0": "RST6.5"})
        cpu.set_pin("RST6.5", 1)  # front panel
        cpu.set_pin("RST6.5", 0, source="OUT0")
        self.assertEqual(cpu.pins["RST6.5"], 1)
        cpu.set_pin("RST6.5", 0)
        self.assertEqual(cpu.pins["RST6.5"], 0)

    def test_reset_resets_8255_but_not_8253(self):
        cpu, bus = system("MVI A, 80H\nOUT 43H\nMVI A, 36H\nOUT 53H\nMVI A, 10\nOUT 50H\nMVI A, 0\nOUT 50H\nHLT")
        run(cpu)
        self.assertEqual(bus.ppi.control, 0x80)
        cpu.reset()
        self.assertEqual(bus.ppi.control, 0x9B)
        self.assertEqual(bus.pit.counters[0].mode, 3)
        self.assertEqual(bus.time, cpu.t_states)

    def test_disabled_chips_leave_the_ports_alone(self):
        cpu, bus = system("IN 40H\nHLT")
        bus.ppi_enabled = False
        cpu.input_ports[0x40] = 0x42
        cpu.step()
        self.assertEqual(cpu.registers["A"], 0x42)


if __name__ == "__main__":
    unittest.main()


class PPIPortCWritesInHandshakeModes(unittest.TestCase):
    """Intel 8255A data sheet, special mode combinations: upper port C outputs only via bit set/reset."""

    def test_upper_spare_outputs_need_bit_set_reset(self):
        ppi = PPI8255()
        ppi.write(CTRL, 0xB0)  # A mode 1 input: PC7, PC6 spare outputs; B mode 0: PC3-PC0... PC3 is INTR A
        ppi.write(C, 0xFF)
        self.assertEqual(ppi.latch[2] & 0xC0, 0x00)  # PC7/PC6 unchanged by a port C write
        self.assertEqual(ppi.latch[2] & 0x07, 0x07)  # PC2-PC0 written "as a threesome"
        ppi.write(CTRL, (7 << 1) | 1)  # bit set/reset works
        self.assertEqual(ppi.latch[2] & 0x80, 0x80)

    def test_mode0_port_c_writes_all_outputs(self):
        ppi = PPI8255()
        ppi.write(CTRL, 0x80)
        ppi.write(C, 0xA5)
        self.assertEqual(ppi.read(C), 0xA5)
