"""Every program in the Examples menu assembles and produces its documented result."""

import unittest

from helpers import Processor8085, assemble
from examples import EXAMPLES

BY_TITLE = {example.title: example for example in EXAMPLES}


def load(title):
    cpu = Processor8085()
    cpu.load_program(assemble(BY_TITLE[title].source))
    return cpu


def run(cpu, max_steps=200000):
    for _ in range(max_steps):
        status = cpu.step()
        if status != "OK":
            return status
    return "OK"


def word(cpu, address):
    return cpu.memory[address] | (cpu.memory[address + 1] << 8)


class Examples(unittest.TestCase):
    def test_all_assemble(self):
        self.assertGreaterEqual(len(EXAMPLES), 10)
        for example in EXAMPLES:
            with self.subTest(example.title):
                assemble(example.source)
                self.assertTrue(example.hint and example.category)

    def test_add_two_numbers(self):
        cpu = load("Add Two Numbers")
        self.assertEqual(run(cpu), "HALT")
        self.assertEqual((cpu.memory[0x2052], cpu.memory[0x2053]), (0x16, 0x01))

    def test_bcd_addition(self):
        cpu = load("BCD Addition (DAA)")
        self.assertEqual(run(cpu), "HALT")
        self.assertEqual(list(cpu.memory[0x2054:0x2057]), [0x63, 0x86, 0x00])

    def test_multiply(self):
        cpu = load("Multiply (Shift and Add)")
        self.assertEqual(run(cpu), "HALT")
        self.assertEqual(word(cpu, 0x2052), 200 * 45)

    def test_bubble_sort(self):
        cpu = load("Bubble Sort")
        original = list(cpu.memory[0x2050:0x205A])
        self.assertEqual(run(cpu), "HALT")
        self.assertEqual(list(cpu.memory[0x2050:0x205A]), sorted(original))

    def test_block_copy_and_checksum(self):
        cpu = load("Block Copy and Checksum (Subroutines)")
        self.assertEqual(run(cpu), "HALT")
        message = b"Neo8085 is fun!\x00"
        self.assertEqual(bytes(cpu.memory[0x2200:0x2210]), message)
        self.assertEqual(cpu.memory[0x2210], sum(message) & 0xFF)
        self.assertEqual(cpu.registers["SP"], 0x3000)

    def test_led_chaser_timing(self):
        cpu = load("LED Chaser (Real-Time Delay)")
        seen = []
        start = None
        while len(seen) < 10:
            self.assertEqual(cpu.step(), "OK")
            if cpu.last_io and cpu.last_io[0] == "OUT":
                if start is None:
                    start = cpu.t_states
                seen.append(cpu.last_io[2])
        self.assertEqual(seen, [1, 2, 4, 8, 16, 32, 64, 128, 1, 2])
        per_step = (cpu.t_states - start) / 9
        self.assertAlmostEqual(per_step / 3_072_000, 0.1, places=3)  # 0.1 s per LED

    def test_switches_to_leds(self):
        cpu = load("Switches to LEDs (IN / OUT)")
        for switches in (0x00, 0xA5, 0xFF, 0x80):
            cpu.input_ports[0] = switches
            for _ in range(200):
                cpu.step()
                if cpu.last_io == ("OUT", 2, bin(switches).count("1")):
                    break
            else:
                self.fail(f"no bit count for {switches:02X}H")
            self.assertEqual(cpu.output_ports[1], switches)

    def test_interrupts(self):
        cpu = load("Interrupts (TRAP, RST 7.5, INTR)")
        run(cpu)  # sleeps in HLT with interrupts enabled
        self.assertTrue(cpu.halted and cpu.interrupt_enable)
        self.assertEqual(cpu.interrupt_masks, 0b011)

        def interrupt(action):
            action()
            for _ in range(100):
                cpu.step()
                if cpu.halted:
                    return

        interrupt(cpu.pulse_rst75)
        interrupt(cpu.pulse_rst75)
        self.assertEqual(cpu.output_ports[1], 2)
        cpu.set_intr_instruction((0xFF,))  # RST 7
        interrupt(lambda: cpu.set_pin("INTR", 1, auto_release=True))
        self.assertEqual(cpu.output_ports[1], 12)
        interrupt(lambda: cpu.set_pin("RST6.5", 1))  # masked: ignored
        self.assertEqual(cpu.output_ports[1], 12)
        cpu.set_pin("RST6.5", 0)
        interrupt(lambda: cpu.set_pin("TRAP", 1, auto_release=True))
        self.assertEqual(cpu.output_ports[1], 0)
        self.assertEqual([entry[0] for entry in cpu.interrupt_log],
                         ["RST7.5", "RST7.5", "INTR", "TRAP"])
        self.assertEqual(cpu.registers["SP"], 0x3000)

    def test_serial_output(self):
        for sid in (0, 1):
            cpu = load("Serial Output on SOD (SIM / RIM)")
            cpu.sid = sid
            levels = []
            while True:
                status = cpu.step()
                if cpu.last_instruction == "SIM":
                    levels.append(cpu.sod)
                if status != "OK":
                    break
            data = [(0x41 >> bit) & 1 for bit in range(8)]
            self.assertEqual(levels, [0] + data + [1])
            self.assertEqual(cpu.memory[0x2050], 0x80 if sid else 0)

    def test_macros(self):
        cpu = load("Macros and Conditional Assembly")
        self.assertEqual(list(cpu.memory[0x2060:0x2070]), [n * n for n in range(16)])
        self.assertEqual(run(cpu), "HALT")
        self.assertEqual(cpu.memory[0x2053], 60)
        self.assertEqual(cpu.output_ports[1], 60)  # DEBUG = 1: OUT assembled
        source = BY_TITLE["Macros and Conditional Assembly"].source.replace("DEBUG   EQU 1", "DEBUG   EQU 0")
        cpu = Processor8085()
        cpu.load_program(assemble(source))
        run(cpu)
        self.assertEqual(cpu.output_ports[1], 0)

    def test_undocumented(self):
        cpu = load("Undocumented Instructions")
        self.assertEqual(run(cpu), "HALT")
        regs = cpu.registers
        self.assertEqual((regs["H"] << 8) | regs["L"], 0x075B)
        self.assertEqual(word(cpu, 0x076B), 0x075B)
        self.assertEqual((regs["D"] << 8) | regs["E"], 0x0002)
        self.assertEqual(regs["C"], 0xAA)  # RSTV went to 0040H
        self.assertEqual(regs["SP"], 0x3000)

    def board(self, title):
        from peripherals import PeripheralBus
        example = BY_TITLE[title]
        cpu = load(title)
        bus = PeripheralBus(ppi_base=0x40, pit_base=0x50)
        bus.wiring = dict(example.setup.get("wiring", {}))
        for index, source in example.setup.get("sources", {}).items():
            bus.pit.sources[index] = source
        bus.attach(cpu)
        return cpu, bus

    def test_8255_mode0(self):
        cpu, bus = self.board("8255 PPI: Mode 0 Ports and Bit Set/Reset")
        for pins, ones in ((0xA5, 4), (0x00, 0), (0xFF, 8)):
            bus.ppi.set_pins(0, pins)
            for _ in range(200):
                cpu.step()
            while cpu.registers["PC"] != 0x2004:  # back at LOOP: the pass has finished
                cpu.step()
            self.assertEqual(bus.ppi.port_pins(1), (pins, 0xFF))
            self.assertEqual(bus.ppi.port_pins(2)[0], ((ones << 4) & 0xF0) | (1 if ones else 0))

    def test_8253_real_time_clock(self):
        cpu, bus = self.board("8253 PIT: Real-Time Clock with Timer Interrupts")
        seconds = []
        out1 = []
        while len(seconds) < 3:
            status = cpu.step()
            if cpu.last_io and cpu.last_io[:2] == ("OUT", 0x01) and cpu.last_io[2]:
                seconds.append(cpu.t_states)
            if status == "HALT":
                cpu.idle(10_000_000)
            bus.sync(cpu.t_states)
            out1.append(bus.pit.counters[1].out)
        gaps = [b - a for a, b in zip(seconds, seconds[1:])]
        self.assertEqual(gaps, [100 * 30720, 100 * 30720])  # exactly one second at 3.072 MHz
        self.assertEqual(cpu.output_ports[1], 3)
        self.assertIn(0, out1)
        self.assertIn(1, out1)  # OUT1 square wave from the cascaded counter

    def test_8255_mode1_strobed_input(self):
        cpu, bus = self.board("8255 PPI: Mode 1 Strobed Input with Interrupt")
        while cpu.step() != "HALT":
            pass
        for value in (0x11, 0x22, 0x33):
            bus.ppi.strobe("A", value)
            bus._after_access()
            for _ in range(20):
                if cpu.step() == "HALT":
                    break
            self.assertEqual(bus.ppi.port_pins(1)[0], value)
            self.assertEqual(cpu.pins["RST5.5"], 0)
        self.assertEqual(cpu.registers["D"], 3)

    def test_machine_cycles_tour(self):
        cpu = load("Machine Cycles Tour")
        cpu.trace_bus = True
        sequences = []
        while True:
            status = cpu.step()
            sequences.append(" ".join(c.short_name for c in cpu.bus_cycles))
            if status != "OK":
                break
        self.assertEqual(status, "HALT")
        self.assertIn("OF BI BI", sequences)
        self.assertIn("OF MR IOR", sequences)
        self.assertIn("OF MR IOW", sequences)
        self.assertIn("OF MR MR MW MW", sequences)  # CALL and XTHL
        self.assertIn("OF MR", sequences)  # JNZ not taken
        self.assertEqual(sequences[-1], "OF HALT")


if __name__ == "__main__":
    unittest.main()
