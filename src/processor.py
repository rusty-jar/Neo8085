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


class Processor8085:
    """
    8085 microprocessor simulator with full instruction set support and memory management.
    Provides registers, flags, memory, and instruction execution capabilities.
    """

    def __init__(self):
        self.registers = {
            "A": 0,
            "B": 0,
            "C": 0,
            "D": 0,
            "E": 0,
            "H": 0,
            "L": 0,
            "SP": 0xFFFF,
            "PC": 0x0000,
            "Inc/Dec Latch": 0,
        }
        self.flags = {"S": 0, "Z": 0, "AC": 0, "P": 0, "C": 0}
        self.memory = bytearray(0x10000)  # 64KB memory space
        self.io_ports = bytearray(0x100)  # 256 I/O ports
        self.halted = False
        self.error = None
        self.last_instruction = None
        self.program_end_address = 0
        self.program_memory_range = set()
        self.data_memory_range = set()
        self.parsed_program = []
        self.line_to_address_map = {}
        self.address_to_line_map = {}
        self.labels = {}
        self.symbols = {}

    def load_program(self, assembly_output):
        """
        Loads assembled program into memory and initializes processor state.

        Args:
            assembly_output: Output from Assembler8085.assemble()
        """
        # Copy all needed data from assembly output
        self.memory = assembly_output.memory
        self.parsed_program = assembly_output.parsed_program
        self.line_to_address_map = assembly_output.line_to_address_map
        self.address_to_line_map = assembly_output.address_to_line_map
        self.labels = assembly_output.labels
        self.symbols = assembly_output.symbols
        self.program_end_address = assembly_output.program_end_address
        self.program_memory_range = assembly_output.program_memory_range
        self.data_memory_range = assembly_output.data_memory_range

        # Set processor state for execution
        self.registers["PC"] = assembly_output.starting_address
        self.halted = False
        self.error = None
        self.last_instruction = None

    def get_hl_addr(self):
        """Returns the 16-bit address formed by the H (high byte) and L (low byte) registers"""
        return (self.registers["H"] << 8) | self.registers["L"]

    def get_bc_addr(self):
        """Returns the 16-bit address formed by the B (high byte) and C (low byte) registers"""
        return (self.registers["B"] << 8) | self.registers["C"]

    def get_de_addr(self):
        """Returns the 16-bit address formed by the D (high byte) and E (low byte) registers"""
        return (self.registers["D"] << 8) | self.registers["E"]

    def get_psw(self):
        """
        Returns the Program Status Word (PSW) - 16-bit value combining A register and flags byte.
        """
        return (self.registers["A"] << 8) | self.get_flags_byte()

    def get_flags_byte(self):
        """
        Returns the flags byte.
        The flags byte has bits: S (7), Z (6), 0 (5), AC (4), 0 (3), P (2), 1 (1), C (0)
        """
        return (
            (self.flags["S"] << 7)
            | (self.flags["Z"] << 6)
            | (self.flags["AC"] << 4)
            | (self.flags["P"] << 2)
            | (1 << 1) # Bit 1 is always set in 8085
            | self.flags["C"]
        )

    def update_flags(
        self, result, check_carry=False, carry_value=None, check_ac=False, ac_value=None
    ):
        """
        Updates processor flags based on operation result

        Args:
            result: Result of the operation
            check_carry: Whether to update carry flag
            carry_value: Value to set carry flag if check_carry is True
            check_ac: Whether to update auxiliary carry flag
            ac_value: Value to set auxiliary carry flag if check_ac is True
        """
        # Sign flag (bit 7)
        self.flags["S"] = 1 if result & 0x80 else 0

        # Zero flag
        self.flags["Z"] = 1 if (result & 0xFF) == 0 else 0

        # Parity flag (1 if even number of 1 bits, 0 if odd)
        bit_count = bin(result & 0xFF).count("1")
        self.flags["P"] = 1 if bit_count % 2 == 0 else 0

        # Auxiliary Carry flag
        if check_ac:
            self.flags["AC"] = ac_value

        # Carry flag
        if check_carry:
            self.flags["C"] = carry_value

    def step(self):
        """
        Executes a single instruction at current PC.
        Returns execution status: "OK", "HALT", or "ERROR".
        """
        if self.halted:
            return "HALT"

        if self.error:
            return "ERROR"

        pc = self.registers["PC"]

        # Find instruction at current PC
        instruction = None
        for addr, tokens in self.parsed_program:
            if addr == pc:
                instruction = tokens
                break

        if not instruction:
            self.error = f"No instruction at address {pc:04X}"
            return "ERROR"

        self.last_instruction = " ".join(instruction)
        opcode = instruction[0].upper()

        try:
            # Process jump instructions with label support
            if opcode in ["JMP", "JZ", "JNZ", "JC", "JNC", "JP", "JM", "JPE", "JPO"]:
                jump_target = instruction[1].strip(",")

                # Resolve target address
                if jump_target in self.labels:
                    target_addr = self.labels[jump_target]
                else:
                    target_addr = self._parse_number(jump_target)

                # Evaluate jump conditions
                should_jump = False
                if opcode == "JMP":
                    should_jump = True
                elif opcode == "JZ" and self.flags["Z"] == 1:
                    should_jump = True
                elif opcode == "JNZ" and self.flags["Z"] == 0:
                    should_jump = True
                elif opcode == "JC" and self.flags["C"] == 1:
                    should_jump = True
                elif opcode == "JNC" and self.flags["C"] == 0:
                    should_jump = True
                elif opcode == "JP" and self.flags["S"] == 0:
                    should_jump = True
                elif opcode == "JM" and self.flags["S"] == 1:
                    should_jump = True
                elif opcode == "JPE" and self.flags["P"] == 1:
                    should_jump = True
                elif opcode == "JPO" and self.flags["P"] == 0:
                    should_jump = True

                if should_jump:
                    self.registers["PC"] = target_addr & 0xFFFF
                else:
                    self.registers["PC"] += 3

                return "OK"

            # Data transfer instructions
            elif opcode == "MVI":
                reg = instruction[1].strip(",")
                value = self._parse_number(instruction[2]) & 0xFF
                if reg == "M":
                    self.memory[self.get_hl_addr()] = value
                else:
                    self.registers[reg] = value
                self.registers["PC"] += 2

            elif opcode == "MOV":
                dest = instruction[1].strip(",")
                src = instruction[2]

                if dest == "M" and src in self.registers:
                    # Move register to memory
                    addr = self.get_hl_addr()
                    self.memory[addr] = self.registers[src]
                elif dest in self.registers and src == "M":
                    # Move memory to register
                    addr = self.get_hl_addr()
                    self.registers[dest] = self.memory[addr]
                elif dest in self.registers and src in self.registers:
                    # Move register to register
                    self.registers[dest] = self.registers[src]
                else:
                    self.error = f"Invalid register in MOV"
                    return "ERROR"
                self.registers["PC"] += 1

            elif opcode == "LXI":
                reg_pair = instruction[1].strip(",")
                value = self._parse_number(instruction[2])
                if reg_pair == "B":
                    self.registers["B"] = (value >> 8) & 0xFF
                    self.registers["C"] = value & 0xFF
                elif reg_pair == "D":
                    self.registers["D"] = (value >> 8) & 0xFF
                    self.registers["E"] = value & 0xFF
                elif reg_pair == "H":
                    self.registers["H"] = (value >> 8) & 0xFF
                    self.registers["L"] = value & 0xFF
                elif reg_pair == "SP":
                    self.registers["SP"] = value & 0xFFFF
                else:
                    self.error = f"Invalid register pair: {reg_pair}"
                    return "ERROR"
                self.registers["PC"] += 3

            elif opcode == "LDA":
                addr = self._parse_number(instruction[1])
                self.registers["A"] = self.memory[addr]
                self.registers["PC"] += 3

            elif opcode == "STA":
                addr = self._parse_number(instruction[1])
                self.memory[addr] = self.registers["A"]
                self.registers["PC"] += 3

            # Arithmetic instructions
            elif opcode == "ADD":
                reg = instruction[1].strip(",;")
                a_value = self.registers["A"]
                operand = self.memory[self.get_hl_addr()] if reg == "M" else self.registers[reg]

                # Calculate auxiliary carry (carry from bit 3 to bit 4)
                ac = 1 if ((a_value & 0x0F) + (operand & 0x0F)) > 0x0F else 0

                result = a_value + operand
                carry = 1 if result > 0xFF else 0

                self.registers["A"] = result & 0xFF
                self.update_flags(self.registers["A"], True, carry, True, ac)
                self.registers["PC"] += 1

            elif opcode == "ADI":
                value = self._parse_number(instruction[1].strip(",;")) & 0xFF
                a_value = self.registers["A"]

                # Calculate auxiliary carry
                ac = 1 if ((a_value & 0x0F) + (value & 0x0F)) > 0x0F else 0

                result = a_value + value
                carry = 1 if result > 0xFF else 0

                self.registers["A"] = result & 0xFF
                self.update_flags(self.registers["A"], True, carry, True, ac)
                self.registers["PC"] += 2

            elif opcode == "SUB":
                reg = instruction[1].strip(",;")
                a_value = self.registers["A"]
                operand = self.memory[self.get_hl_addr()] if reg == "M" else self.registers[reg]

                # Calculate auxiliary carry for subtraction
                ac = 1 if (a_value & 0x0F) < (operand & 0x0F) else 0

                result = a_value - operand
                carry = 1 if result < 0 else 0

                self.registers["A"] = result & 0xFF
                self.update_flags(self.registers["A"], True, carry, True, ac)
                self.registers["PC"] += 1

            elif opcode == "INR":
                reg = instruction[1]
                if reg == "M":
                    hl_addr = self.get_hl_addr()
                    old_val = self.memory[hl_addr]
                    # AC=1 when lower nibble overflows (0x0F + 1 carries into bit 4)
                    ac = 1 if (old_val & 0x0F) == 0x0F else 0
                    self.memory[hl_addr] = (old_val + 1) & 0xFF
                    self.update_flags(self.memory[hl_addr], False, None, True, ac)
                else:
                    old_val = self.registers[reg]
                    ac = 1 if (old_val & 0x0F) == 0x0F else 0
                    self.registers[reg] = (old_val + 1) & 0xFF
                    self.update_flags(self.registers[reg], False, None, True, ac)
                self.registers["PC"] += 1

            elif opcode == "DCR":
                reg = instruction[1]
                if reg == "M":
                    hl_addr = self.get_hl_addr()
                    old_val = self.memory[hl_addr]
                    self.memory[hl_addr] = (old_val - 1) & 0xFF
                    # AC=0 when lower nibble is 0x00 (borrow from bit 4 occurs)
                    # AC=1 when lower nibble is non-zero (no borrow)
                    ac = 0 if (old_val & 0x0F) == 0x00 else 1
                    self.update_flags(self.memory[hl_addr], False, None, True, ac)
                else:
                    old_val = self.registers[reg]
                    self.registers[reg] = (old_val - 1) & 0xFF
                    ac = 0 if (old_val & 0x0F) == 0x00 else 1
                    self.update_flags(self.registers[reg], False, None, True, ac)
                self.registers["PC"] += 1

            elif opcode == "HLT":
                self.halted = True
                return "HALT"

            # Register pair instructions
            elif opcode == "INX":
                reg_pair = instruction[1]
                if reg_pair == "B":
                    bc = self.get_bc_addr()
                    bc = (bc + 1) & 0xFFFF
                    self.registers["B"] = (bc >> 8) & 0xFF
                    self.registers["C"] = bc & 0xFF
                elif reg_pair == "D":
                    de = self.get_de_addr()
                    de = (de + 1) & 0xFFFF
                    self.registers["D"] = (de >> 8) & 0xFF
                    self.registers["E"] = de & 0xFF
                elif reg_pair == "H":
                    hl = self.get_hl_addr()
                    hl = (hl + 1) & 0xFFFF
                    self.registers["H"] = (hl >> 8) & 0xFF
                    self.registers["L"] = hl & 0xFF
                elif reg_pair == "SP":
                    self.registers["SP"] = (self.registers["SP"] + 1) & 0xFFFF
                else:
                    self.error = f"Invalid register pair: {reg_pair}"
                    return "ERROR"
                self.registers["PC"] += 1

            elif opcode == "PUSH":
                reg_pair = instruction[1].strip(",;")
                if reg_pair == "PSW":
                    # Push PSW (A register and flags)
                    psw_value = self.get_psw()
                    # Calculate addresses directly without intermediate SP updates
                    addr_high = (self.registers["SP"] - 1) & 0xFFFF
                    addr_low = (self.registers["SP"] - 2) & 0xFFFF
                    # Push high byte first (A register) to memory[SP-1]
                    self.memory[addr_high] = (psw_value >> 8) & 0xFF
                    # Push low byte (flags) to memory[SP-2]
                    self.memory[addr_low] = psw_value & 0xFF
                    # Update SP at once
                    self.registers["SP"] = addr_low
                elif reg_pair == "B":
                    # Calculate addresses
                    addr_high = (self.registers["SP"] - 1) & 0xFFFF
                    addr_low = (self.registers["SP"] - 2) & 0xFFFF
                    # Push BC pair
                    self.memory[addr_high] = self.registers["B"]
                    self.memory[addr_low] = self.registers["C"]
                    self.registers["SP"] = addr_low
                elif reg_pair == "D":
                    # Calculate addresses
                    addr_high = (self.registers["SP"] - 1) & 0xFFFF
                    addr_low = (self.registers["SP"] - 2) & 0xFFFF
                    # Push DE pair
                    self.memory[addr_high] = self.registers["D"]
                    self.memory[addr_low] = self.registers["E"]
                    self.registers["SP"] = addr_low
                elif reg_pair == "H":
                    # Calculate addresses
                    addr_high = (self.registers["SP"] - 1) & 0xFFFF
                    addr_low = (self.registers["SP"] - 2) & 0xFFFF
                    # Push HL pair
                    self.memory[addr_high] = self.registers["H"]
                    self.memory[addr_low] = self.registers["L"]
                    self.registers["SP"] = addr_low
                else:
                    self.error = f"Invalid register pair for PUSH: {reg_pair}"
                    return "ERROR"
                self.registers["PC"] += 1

            elif opcode == "POP":
                reg_pair = instruction[1].strip(",;")
                if reg_pair == "PSW":
                    # Pop PSW (A register and flags)
                    # Pop low byte first (flags)
                    flags_byte = self.memory[self.registers["SP"]]
                    self.registers["SP"] = (self.registers["SP"] + 1) & 0xFFFF
                    # Pop high byte (A register)
                    self.registers["A"] = self.memory[self.registers["SP"]]
                    self.registers["SP"] = (self.registers["SP"] + 1) & 0xFFFF

                    # Update individual flags
                    self.flags["S"] = 1 if (flags_byte & 0x80) else 0
                    self.flags["Z"] = 1 if (flags_byte & 0x40) else 0
                    self.flags["AC"] = 1 if (flags_byte & 0x10) else 0
                    self.flags["P"] = 1 if (flags_byte & 0x04) else 0
                    self.flags["C"] = 1 if (flags_byte & 0x01) else 0
                elif reg_pair == "B":
                    # Pop BC pair
                    self.registers["C"] = self.memory[self.registers["SP"]]
                    self.registers["SP"] = (self.registers["SP"] + 1) & 0xFFFF
                    self.registers["B"] = self.memory[self.registers["SP"]]
                    self.registers["SP"] = (self.registers["SP"] + 1) & 0xFFFF
                elif reg_pair == "D":
                    # Pop DE pair
                    self.registers["E"] = self.memory[self.registers["SP"]]
                    self.registers["SP"] = (self.registers["SP"] + 1) & 0xFFFF
                    self.registers["D"] = self.memory[self.registers["SP"]]
                    self.registers["SP"] = (self.registers["SP"] + 1) & 0xFFFF
                elif reg_pair == "H":
                    # Pop HL pair
                    self.registers["L"] = self.memory[self.registers["SP"]]
                    self.registers["SP"] = (self.registers["SP"] + 1) & 0xFFFF
                    self.registers["H"] = self.memory[self.registers["SP"]]
                    self.registers["SP"] = (self.registers["SP"] + 1) & 0xFFFF
                else:
                    self.error = f"Invalid register pair for POP: {reg_pair}"
                    return "ERROR"
                self.registers["PC"] += 1

            elif opcode == "CALL":
                # Get target address
                jump_target = instruction[1].strip(",;")

                # Resolve target address
                if jump_target in self.labels:
                    target_addr = self.labels[jump_target]
                else:
                    target_addr = self._parse_number(jump_target)

                # Compute return address (next instruction after CALL)
                return_addr = self.registers["PC"] + 3

                # Calculate addresses for pushing return address
                addr_high = (self.registers["SP"] - 1) & 0xFFFF
                addr_low = (self.registers["SP"] - 2) & 0xFFFF

                # Push return address to stack (high byte first, then low byte)
                self.memory[addr_high] = (return_addr >> 8) & 0xFF
                self.memory[addr_low] = return_addr & 0xFF

                # Update SP
                self.registers["SP"] = addr_low

                # Jump to target address
                self.registers["PC"] = target_addr & 0xFFFF

            elif opcode == "RET":
                # Pop return address from stack
                # Get low byte from SP
                return_addr_low = self.memory[self.registers["SP"]]
                self.registers["SP"] = (self.registers["SP"] + 1) & 0xFFFF

                # Get high byte from SP+1
                return_addr_high = self.memory[self.registers["SP"]]
                self.registers["SP"] = (self.registers["SP"] + 1) & 0xFFFF

                # Combine to form 16-bit address
                return_addr = (return_addr_high << 8) | return_addr_low

                # Jump to return address
                self.registers["PC"] = return_addr & 0xFFFF

            elif opcode == "CPI":
                value = self._parse_number(instruction[1].strip(",;")) & 0xFF
                a_value = self.registers["A"]

                # Calculate result (don't store it, just for flags)
                result = a_value - value

                # Set carry flag if A < value
                carry = 1 if result < 0 else 0

                # Set auxiliary carry flag
                ac = 1 if (a_value & 0x0F) < (value & 0x0F) else 0

                # Update flags but don't change A register
                self.update_flags(result & 0xFF, True, carry, True, ac)

                self.registers["PC"] += 2

            elif opcode == "DAD":
                reg_pair = instruction[1].strip(",;")

                # Get HL value
                hl = self.get_hl_addr()

                # Get operand based on register pair
                if reg_pair == "B":
                    operand = self.get_bc_addr()
                elif reg_pair == "D":
                    operand = self.get_de_addr()
                elif reg_pair == "H":
                    operand = hl  # Adding HL to itself
                elif reg_pair == "SP":
                    operand = self.registers["SP"]
                else:
                    self.error = f"Invalid register pair for DAD: {reg_pair}"
                    return "ERROR"

                # Add the values
                result = (hl + operand) & 0xFFFF

                # Set carry flag if needed (16-bit overflow)
                carry = 1 if (hl + operand) > 0xFFFF else 0

                # Update HL register pair
                self.registers["H"] = (result >> 8) & 0xFF
                self.registers["L"] = result & 0xFF

                # Update carry flag only
                self.flags["C"] = carry

                self.registers["PC"] += 1

            elif opcode == "XCHG":
                # Exchange DE and HL register pairs
                temp_d = self.registers["D"]
                temp_e = self.registers["E"]

                self.registers["D"] = self.registers["H"]
                self.registers["E"] = self.registers["L"]

                self.registers["H"] = temp_d
                self.registers["L"] = temp_e

                self.registers["PC"] += 1

            elif opcode == "LDAX":  # LDAX B/D (1 byte): Load A from address in BC/DE
                reg_pair = instruction[1].strip(",;")

                if reg_pair == "B":
                    # Load A from memory at BC address
                    bc_addr = self.get_bc_addr()
                    self.registers["A"] = self.memory[bc_addr]
                elif reg_pair == "D":
                    # Load A from memory at DE address
                    de_addr = self.get_de_addr()
                    self.registers["A"] = self.memory[de_addr]
                else:
                    self.error = f"Invalid register pair for LDAX: {reg_pair}"
                    return "ERROR"

                self.registers["PC"] += 1

            elif opcode == "STAX":  # STAX B/D (1 byte): Store A to address in BC/DE
                reg_pair = instruction[1].strip(",;")

                if reg_pair == "B":
                    # Store A to memory at BC address
                    bc_addr = self.get_bc_addr()
                    self.memory[bc_addr] = self.registers["A"]
                elif reg_pair == "D":
                    # Store A to memory at DE address
                    de_addr = self.get_de_addr()
                    self.memory[de_addr] = self.registers["A"]
                else:
                    self.error = f"Invalid register pair for STAX: {reg_pair}"
                    return "ERROR"

                self.registers["PC"] += 1

            elif opcode == "LHLD":  # LHLD addr (3 bytes): Load H-L from memory
                addr = self._parse_number(instruction[1]) & 0xFFFF
                addr_plus_1 = (addr + 1) & 0xFFFF
                self.registers["L"] = self.memory[addr]
                self.registers["H"] = self.memory[addr_plus_1]
                self.registers["PC"] += 3

            elif opcode == "SHLD":  # SHLD addr (3 bytes): Store H-L to memory
                addr = self._parse_number(instruction[1]) & 0xFFFF
                addr_plus_1 = (addr + 1) & 0xFFFF
                self.memory[addr] = self.registers["L"]
                self.memory[addr_plus_1] = self.registers["H"]
                self.registers["PC"] += 3

            elif opcode == "PCHL":  # PCHL (1 byte): Load PC from H-L
                # Move HL value to PC
                hl_addr = self.get_hl_addr()
                self.registers["PC"] = hl_addr

                # Note: No need to increment PC as it's been directly set

            elif opcode == "SPHL":  # SPHL (1 byte): Load SP from H-L
                # Move HL value to SP
                hl_addr = self.get_hl_addr()
                self.registers["SP"] = hl_addr

                self.registers["PC"] += 1

            elif opcode == "XTHL":  # XTHL (1 byte): Exchange top of stack with H-L
                sp_addr = self.registers["SP"]
                sp_plus_1 = (sp_addr + 1) & 0xFFFF

                # Save current values
                h_val = self.registers["H"]
                l_val = self.registers["L"]

                # Exchange: L <-> (SP), H <-> (SP+1)
                self.registers["L"] = self.memory[sp_addr]
                self.registers["H"] = self.memory[sp_plus_1]
                self.memory[sp_addr] = l_val
                self.memory[sp_plus_1] = h_val

                self.registers["PC"] += 1

            elif opcode == "ANA":  # ANA r/M (1 byte): AND register/memory with A
                reg = instruction[1].strip(",;")

                if reg == "M":
                    # Memory addressed by HL
                    value = self.memory[self.get_hl_addr()]
                else:
                    # Register
                    value = self.registers[reg]

                # Perform AND operation
                result = self.registers["A"] & value
                self.registers["A"] = result

                # Update flags: S, Z, P, CY=0, AC=1 (according to 8085 manual)
                self.update_flags(result)
                self.flags["C"] = 0
                self.flags["AC"] = 1  # AC is set per 8085 specification

                self.registers["PC"] += 1

            elif opcode == "ANI":  # ANI data (2 bytes): AND immediate with A
                value = self._parse_number(instruction[1]) & 0xFF

                # Perform AND operation
                result = self.registers["A"] & value
                self.registers["A"] = result

                # Update flags: S, Z, P affected; CY=0, AC=1
                # 8085 sets AC=1 for both ANA and ANI (unlike 8080 which clears AC for ANI)
                self.update_flags(result)
                self.flags["C"] = 0
                self.flags["AC"] = 1

                self.registers["PC"] += 2

            elif opcode == "ORA":  # ORA r/M (1 byte): OR register/memory with A
                reg = instruction[1].strip(",;")

                if reg == "M":
                    value = self.memory[self.get_hl_addr()]
                else:
                    value = self.registers[reg]

                result = self.registers["A"] | value
                self.registers["A"] = result

                # S, Z, P set normally; CY=0, AC=0
                self.update_flags(result)
                self.flags["C"] = 0
                self.flags["AC"] = 0
                # Do NOT invert parity — ORA sets parity normally (even parity = 1)

                self.registers["PC"] += 1

            elif opcode == "ORI":  # ORI data (2 bytes): OR immediate with A
                value = self._parse_number(instruction[1]) & 0xFF

                result = self.registers["A"] | value
                self.registers["A"] = result

                # S, Z, P set normally; CY=0, AC=0
                self.update_flags(result)
                self.flags["C"] = 0
                self.flags["AC"] = 0
                # Do NOT invert parity — ORI sets parity normally (even parity = 1)

                self.registers["PC"] += 2

            elif opcode == "XRA":  # XRA r/M (1 byte): XOR register/memory with A
                reg = instruction[1].strip(",;")

                if reg == "M":
                    value = self.memory[self.get_hl_addr()]
                else:
                    value = self.registers[reg]

                result = self.registers["A"] ^ value
                self.registers["A"] = result

                # Update flags: S, Z, P, CY=0, AC=0
                self.update_flags(result)
                self.flags["C"] = 0
                self.flags["AC"] = 0

                self.registers["PC"] += 1

            elif opcode == "XRI":  # XRI data (2 bytes): XOR immediate with A
                value = self._parse_number(instruction[1]) & 0xFF

                result = self.registers["A"] ^ value
                self.registers["A"] = result

                # Update flags: S, Z, P, CY=0, AC=0
                self.update_flags(result)
                self.flags["C"] = 0
                self.flags["AC"] = 0

                self.registers["PC"] += 2

            elif opcode == "CMA":  # CMA (1 byte): Complement accumulator
                # One's complement (bitwise NOT)
                self.registers["A"] = (~self.registers["A"]) & 0xFF

                # No flags affected
                self.registers["PC"] += 1

            elif opcode == "CMC":  # CMC (1 byte): Complement carry flag
                # Flip carry flag
                self.flags["C"] = 1 if self.flags["C"] == 0 else 0

                self.registers["PC"] += 1

            elif opcode == "STC":  # STC (1 byte): Set carry flag
                # Set carry flag to 1
                self.flags["C"] = 1

                self.registers["PC"] += 1

            elif opcode == "RLC":  # RLC (1 byte): Rotate accumulator left
                value = self.registers["A"]

                # Bit 7 goes to carry flag
                self.flags["C"] = (value >> 7) & 1

                # Rotate left, bit 7 wraps to bit 0
                self.registers["A"] = ((value << 1) | (value >> 7)) & 0xFF

                self.registers["PC"] += 1

            elif opcode == "RRC":  # RRC (1 byte): Rotate accumulator right
                value = self.registers["A"]

                # Bit 0 goes to carry flag
                self.flags["C"] = value & 1

                # Rotate right, bit 0 wraps to bit 7
                self.registers["A"] = ((value >> 1) | ((value & 1) << 7)) & 0xFF

                self.registers["PC"] += 1

            elif opcode == "RAL":  # RAL (1 byte): Rotate accumulator left through carry
                value = self.registers["A"]
                old_carry = self.flags["C"]

                # Bit 7 goes to carry flag
                self.flags["C"] = (value >> 7) & 1

                # Rotate left, old carry goes to bit 0
                self.registers["A"] = ((value << 1) | old_carry) & 0xFF

                self.registers["PC"] += 1

            elif (
                opcode == "RAR"
            ):  # RAR (1 byte): Rotate accumulator right through carry
                value = self.registers["A"]
                old_carry = self.flags["C"]

                # Bit 0 goes to carry flag
                self.flags["C"] = value & 1

                # Rotate right, old carry goes to bit 7
                self.registers["A"] = ((value >> 1) | (old_carry << 7)) & 0xFF

                self.registers["PC"] += 1

            elif opcode == "ADC":  # ADC r/M (1 byte): Add register/memory with carry
                reg = instruction[1].strip(",;")

                if reg == "M":
                    # Memory addressed by HL
                    value = self.memory[self.get_hl_addr()]
                else:
                    # Register
                    value = self.registers[reg]

                # Get current values
                a_value = self.registers["A"]
                carry = self.flags["C"]

                # Calculate auxiliary carry (from bit 3 to bit 4)
                ac = 1 if ((a_value & 0x0F) + (value & 0x0F) + carry) > 0x0F else 0

                # Perform addition with carry
                result = a_value + value + carry

                # Set the carry flag
                carry_out = 1 if result > 0xFF else 0

                # Update A and flags
                self.registers["A"] = result & 0xFF
                self.update_flags(self.registers["A"], True, carry_out, True, ac)

                self.registers["PC"] += 1

            elif opcode == "ACI":  # ACI data (2 bytes): Add immediate with carry
                value = self._parse_number(instruction[1]) & 0xFF

                # Get current values
                a_value = self.registers["A"]
                carry = self.flags["C"]

                # Calculate auxiliary carry
                ac = 1 if ((a_value & 0x0F) + (value & 0x0F) + carry) > 0x0F else 0

                # Perform addition with carry
                result = a_value + value + carry

                # Set the carry flag
                carry_out = 1 if result > 0xFF else 0

                # Update A and flags
                self.registers["A"] = result & 0xFF
                self.update_flags(self.registers["A"], True, carry_out, True, ac)

                self.registers["PC"] += 2

            elif (
                opcode == "SBB"
            ):  # SBB r/M (1 byte): Subtract register/memory with borrow
                reg = instruction[1].strip(",;")

                if reg == "M":
                    # Memory addressed by HL
                    value = self.memory[self.get_hl_addr()]
                else:
                    # Register
                    value = self.registers[reg]

                # Get current values
                a_value = self.registers["A"]
                borrow = self.flags[
                    "C"
                ]  # In 8085, carry flag acts as borrow flag for subtraction

                # Calculate auxiliary carry (borrow from bit 4 to bit 3)
                ac = 1 if (a_value & 0x0F) < ((value & 0x0F) + borrow) else 0

                # Perform subtraction with borrow
                result = a_value - value - borrow

                # Set the carry flag (borrow flag)
                carry_out = 1 if result < 0 else 0

                # Update A and flags
                self.registers["A"] = result & 0xFF
                self.update_flags(self.registers["A"], True, carry_out, True, ac)

                self.registers["PC"] += 1

            elif opcode == "SBI":  # SBI data (2 bytes): Subtract immediate with borrow
                value = self._parse_number(instruction[1]) & 0xFF

                # Get current values
                a_value = self.registers["A"]
                borrow = self.flags[
                    "C"
                ]  # In 8085, carry flag acts as borrow flag for subtraction

                # Calculate auxiliary carry (borrow from bit 4 to bit 3)
                ac = 1 if (a_value & 0x0F) < ((value & 0x0F) + borrow) else 0

                # Perform subtraction with borrow
                result = a_value - value - borrow

                # Set the carry flag (borrow flag)
                carry_out = 1 if result < 0 else 0

                # Update A and flags
                self.registers["A"] = result & 0xFF
                self.update_flags(self.registers["A"], True, carry_out, True, ac)

                self.registers["PC"] += 2

            elif opcode == "DAA":  # DAA (1 byte): Decimal adjust accumulator
                a_value = self.registers["A"]

                # Start with current flags
                carry = self.flags["C"]
                ac = self.flags["AC"]

                # Step 1: Adjust the lower nibble
                if (a_value & 0x0F) > 9 or ac == 1:
                    # Need to add 6 to lower nibble
                    old_lower = a_value & 0x0F
                    a_value += 6

                    # Check if adjustment caused a carry from bit 3 to bit 4
                    if old_lower > (a_value & 0x0F):
                        ac = 1
                    else:
                        ac = 0
                else:
                    ac = 0

                # Step 2: Adjust the upper nibble
                if (
                    ((a_value & 0xF0) >> 4) > 9
                    or carry == 1
                    or ((a_value & 0xF0) >= 0x90 and (a_value & 0x0F) > 9)
                ):
                    # Need to add 6 to upper nibble (60H)
                    a_value += 0x60
                    carry = 1
                else:
                    carry = 0

                # Update accumulator and flags
                self.registers["A"] = a_value & 0xFF
                self.update_flags(self.registers["A"], True, carry, True, ac)

                self.registers["PC"] += 1

            elif opcode == "DCX":  # DCX rp (1 byte): Decrement register pair
                reg_pair = instruction[1]

                if reg_pair == "B":
                    bc = self.get_bc_addr()
                    bc = (bc - 1) & 0xFFFF
                    self.registers["B"] = (bc >> 8) & 0xFF
                    self.registers["C"] = bc & 0xFF
                elif reg_pair == "D":
                    de = self.get_de_addr()
                    de = (de - 1) & 0xFFFF
                    self.registers["D"] = (de >> 8) & 0xFF
                    self.registers["E"] = de & 0xFF
                elif reg_pair == "H":
                    hl = self.get_hl_addr()
                    hl = (hl - 1) & 0xFFFF
                    self.registers["H"] = (hl >> 8) & 0xFF
                    self.registers["L"] = hl & 0xFF
                elif reg_pair == "SP":
                    self.registers["SP"] = (self.registers["SP"] - 1) & 0xFFFF
                else:
                    self.error = f"Invalid register pair: {reg_pair}"
                    return "ERROR"

                self.registers["PC"] += 1

            elif opcode in ["CC", "CNC", "CZ", "CNZ", "CP", "CM", "CPE", "CPO"]:
                # Get target address
                jump_target = instruction[1].strip(",;")

                # Resolve target address
                if jump_target in self.labels:
                    target_addr = self.labels[jump_target]
                else:
                    try:
                        target_addr = self._parse_number(jump_target)
                    except ValueError:
                        # Important fix: if the label isn't found, it could be a forward reference
                        # We should report the error instead of silently failing
                        self.error = f"Cannot resolve label: {jump_target}"
                        return "ERROR"

                # Check condition based on opcode
                should_call = False

                if opcode == "CC" and self.flags["C"] == 1:
                    should_call = True
                elif opcode == "CNC" and self.flags["C"] == 0:
                    should_call = True
                elif opcode == "CZ" and self.flags["Z"] == 1:
                    should_call = True
                elif opcode == "CNZ" and self.flags["Z"] == 0:
                    should_call = True
                elif opcode == "CP" and self.flags["S"] == 0:
                    should_call = True
                elif opcode == "CM" and self.flags["S"] == 1:
                    should_call = True
                elif opcode == "CPE" and self.flags["P"] == 1:
                    should_call = True
                elif opcode == "CPO" and self.flags["P"] == 0:
                    should_call = True

                if should_call:
                    # Compute return address (next instruction after CALL)
                    return_addr = self.registers["PC"] + 3

                    # Calculate addresses for pushing return address
                    addr_high = (self.registers["SP"] - 1) & 0xFFFF
                    addr_low = (self.registers["SP"] - 2) & 0xFFFF

                    # Push return address to stack (high byte first, then low byte)
                    self.memory[addr_high] = (return_addr >> 8) & 0xFF
                    self.memory[addr_low] = return_addr & 0xFF

                    # Update SP
                    self.registers["SP"] = addr_low

                    # Jump to target address
                    self.registers["PC"] = target_addr & 0xFFFF
                else:
                    # Skip the instruction if condition is not met
                    self.registers["PC"] += 3

            elif opcode in ["RC", "RNC", "RZ", "RNZ", "RP", "RM", "RPE", "RPO"]:
                # Check condition based on opcode
                should_return = False

                if opcode == "RC" and self.flags["C"] == 1:
                    should_return = True
                elif opcode == "RNC" and self.flags["C"] == 0:
                    should_return = True
                elif opcode == "RZ" and self.flags["Z"] == 1:
                    should_return = True
                elif opcode == "RNZ" and self.flags["Z"] == 0:
                    should_return = True
                elif opcode == "RP" and self.flags["S"] == 0:
                    should_return = True
                elif opcode == "RM" and self.flags["S"] == 1:
                    should_return = True
                elif opcode == "RPE" and self.flags["P"] == 1:
                    should_return = True
                elif opcode == "RPO" and self.flags["P"] == 0:
                    should_return = True

                if should_return:
                    # Pop return address from stack
                    # Get low byte from SP
                    return_addr_low = self.memory[self.registers["SP"]]
                    self.registers["SP"] = (self.registers["SP"] + 1) & 0xFFFF

                    # Get high byte from SP+1
                    return_addr_high = self.memory[self.registers["SP"]]
                    self.registers["SP"] = (self.registers["SP"] + 1) & 0xFFFF

                    # Combine to form 16-bit address
                    return_addr = (return_addr_high << 8) | return_addr_low

                    # Jump to return address
                    self.registers["PC"] = return_addr & 0xFFFF
                else:
                    # Skip the instruction if condition is not met
                    self.registers["PC"] += 1

            elif opcode == "RST":
                # RST n - Call to address 0000h + 8*n
                rst_num = int(instruction[1])

                if rst_num < 0 or rst_num > 7:
                    self.error = f"Invalid RST number: {rst_num}. Must be 0-7."
                    return "ERROR"

                # Calculate restart address
                restart_addr = 8 * rst_num

                # Compute return address (next instruction after RST)
                return_addr = self.registers["PC"] + 1

                # Calculate addresses for pushing return address
                addr_high = (self.registers["SP"] - 1) & 0xFFFF
                addr_low = (self.registers["SP"] - 2) & 0xFFFF

                # Push return address to stack (high byte first, then low byte)
                self.memory[addr_high] = (return_addr >> 8) & 0xFF
                self.memory[addr_low] = return_addr & 0xFF

                # Update SP
                self.registers["SP"] = addr_low

                # Jump to restart address
                self.registers["PC"] = restart_addr

            elif opcode == "CMP":  # CMP r/M (1 byte): Compare register/memory with A
                reg = instruction[1].strip(",;")

                if reg == "M":
                    # Memory addressed by HL
                    value = self.memory[self.get_hl_addr()]
                else:
                    # Register
                    value = self.registers[reg]

                # Get accumulator value
                a_value = self.registers["A"]

                # Calculate auxiliary carry for subtraction (borrow from bit 4 to bit 3)
                ac = 1 if (a_value & 0x0F) < (value & 0x0F) else 0

                # Perform subtraction (don't store result)
                result = a_value - value

                # Set the carry flag (borrow flag)
                carry_out = 1 if result < 0 else 0

                # Update flags only, don't change accumulator
                self.update_flags(result & 0xFF, True, carry_out, True, ac)

                self.registers["PC"] += 1

            elif opcode == "NOP":  # NOP (1 byte): No operation
                # No operation - just increment the program counter
                self.registers["PC"] += 1

            elif opcode == "SUI":  # SUI data (2 bytes): Subtract immediate from A
                value = self._parse_number(instruction[1].strip(",;")) & 0xFF
                a_value = self.registers["A"]

                # Calculate auxiliary carry for subtraction
                ac = 1 if (a_value & 0x0F) < (value & 0x0F) else 0

                result = a_value - value
                carry = 1 if result < 0 else 0

                self.registers["A"] = result & 0xFF
                self.update_flags(self.registers["A"], True, carry, True, ac)
                self.registers["PC"] += 2

            elif opcode == "IN":  # IN port (2 bytes): Input from port
                port = self._parse_number(instruction[1].strip(",;")) & 0xFF
                self.registers["A"] = self.io_ports[port]
                self.registers["PC"] += 2

            elif opcode == "OUT":  # OUT port (2 bytes): Output to port
                port = self._parse_number(instruction[1].strip(",;")) & 0xFF
                self.io_ports[port] = self.registers["A"]
                self.registers["PC"] += 2

            elif opcode == "EI":  # EI (1 byte): Enable interrupts
                # Simulator doesn't model interrupts, treat as NOP
                self.registers["PC"] += 1

            elif opcode == "DI":  # DI (1 byte): Disable interrupts
                # Simulator doesn't model interrupts, treat as NOP
                self.registers["PC"] += 1

            elif opcode == "RIM":  # RIM (1 byte): Read interrupt mask
                # Simulator doesn't model interrupt mask; loads 0 into A
                self.registers["A"] = 0x00
                self.registers["PC"] += 1

            elif opcode == "SIM":  # SIM (1 byte): Set interrupt mask
                # Simulator doesn't model interrupt mask; treat as NOP
                self.registers["PC"] += 1

            else:
                self.error = f"Unknown opcode: {opcode}"
                return "ERROR"

            return "OK"

        except Exception as e:
            self.error = f"Error executing {opcode}: {str(e)}"
            return "ERROR"

    def _get_reg_code(self, reg):
        """Returns the 3-bit register code used in opcode construction"""
        reg_codes = {"A": 7, "B": 0, "C": 1, "D": 2, "E": 3, "H": 4, "L": 5, "M": 6}
        return reg_codes.get(reg, 0)

    def _get_rp_code(self, reg_pair):
        """Returns the 2-bit register pair code used in opcode construction"""
        rp_codes = {
            "B": 0,  # BC pair
            "D": 1,  # DE pair
            "H": 2,  # HL pair
            "SP": 3,  # SP
        }
        return rp_codes.get(reg_pair, 0)

    def _parse_number(self, value_str):
        """
        Parses a number according to 8085 conventions:
        - Symbol lookup from defined symbols table
        - Label lookup from defined labels
        - Expression evaluation (e.g., LABEL + 5)
        - Hexadecimal if string ends with 'H'
        - Decimal otherwise
        """
        value_str = value_str.strip()

        # Check if it's a symbol first
        if hasattr(self, "symbols") and value_str in self.symbols:
            return self.symbols[value_str]

        # Then check if it's a label
        if hasattr(self, "labels") and value_str in self.labels:
            return self.labels[value_str]

        # Check if it contains an arithmetic expression
        if any(op in value_str for op in ["+", "-", "*", "/"]):
            result = self._evaluate_expression(value_str)
            if result is not None:
                return result

        # Otherwise, parse as number
        if value_str.upper().endswith("H"):
            return int(value_str[:-1], 16)
        else:
            return int(value_str, 10)

    def _evaluate_expression(self, expr):
        """Evaluate simple arithmetic expressions with symbols/labels."""
        operators = ["+", "-", "*", "/"]
        tokens = []
        current = ""
        for ch in expr:
            if ch == " ":
                if current:
                    tokens.append(current)
                    current = ""
            elif ch in operators:
                if current:
                    tokens.append(current)
                    current = ""
                tokens.append(ch)
            else:
                current += ch
        if current:
            tokens.append(current)

        if len(tokens) < 3:
            return None

        result = self._resolve_token(tokens[0])
        if result is None:
            return None

        for i in range(1, len(tokens), 2):
            if i + 1 >= len(tokens):
                break
            op = tokens[i]
            operand = self._resolve_token(tokens[i + 1])
            if operand is None:
                return None
            if op == "+":
                result += operand
            elif op == "-":
                result -= operand
            elif op == "*":
                result *= operand
            elif op == "/":
                result //= operand
        return result

    def _resolve_token(self, token):
        """Resolve a single token to a numeric value."""
        token = token.strip()
        if hasattr(self, "symbols") and token in self.symbols:
            return self.symbols[token]
        if hasattr(self, "labels") and token in self.labels:
            return self.labels[token]
        try:
            if token.upper().endswith("H"):
                return int(token[:-1], 16)
            return int(token, 10)
        except ValueError:
            return None

    def is_program_memory(self, address):
        """Returns True if the address contains program code (not data)"""
        return address in self.program_memory_range and address not in self.data_memory_range
