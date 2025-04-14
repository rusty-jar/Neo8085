# Neo8085 - 8085 Microprocessor Simulator
# Copyright (C) 2025 Shahibur Rahaman
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
            "A": 0, "B": 0, "C": 0, "D": 0, "E": 0, "H": 0, "L": 0,
            "SP": 0xFFFF, "PC": 0x0000, "Inc/Dec Latch": 0
        }
        self.flags = {"S": 0, "Z": 0, "AC": 0, "P": 0, "C": 0}
        self.memory = bytearray(0x10000)  # 64KB memory space
        self.halted = False
        self.error = None
        self.last_instruction = None
        self.program_end_address = 0
        self.program_memory_range = set()
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
        Returns the Program Status Word (PSW) - 16-bit value combining A register and flags.
        The flags byte has bits: S (7), Z (6), 0 (5), AC (4), 0 (3), P (2), 1 (1), C (0)
        """
        flags_byte = (
            (self.flags["S"] << 7) | 
            (self.flags["Z"] << 6) | 
            (self.flags["AC"] << 4) |
            (self.flags["P"] << 2) | 
            (1 << 1) |  # Bit 1 is always set in 8085
            self.flags["C"]
        )
        return (self.registers["A"] << 8) | flags_byte
    
    def update_flags(self, result, check_carry=False, carry_value=None, check_ac=False, ac_value=None):
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
        bit_count = bin(result & 0xFF).count('1')
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
                jump_target = instruction[1].strip(',')
                
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
                value = self._parse_number(instruction[2])
                if reg in self.registers:
                    self.registers[reg] = value & 0xFF
                else:
                    self.error = f"Invalid register: {reg}"
                    return "ERROR"
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
                if reg in self.registers:
                    a_value = self.registers["A"]
                    operand = self.registers[reg]
                    
                    # Calculate auxiliary carry (carry from bit 3 to bit 4)
                    ac = 1 if ((a_value & 0x0F) + (operand & 0x0F)) > 0x0F else 0
                    
                    result = a_value + operand
                    carry = 1 if result > 0xFF else 0
                    
                    self.registers["A"] = result & 0xFF
                    self.update_flags(self.registers["A"], True, carry, True, ac)
                else:
                    self.error = f"Invalid register: {reg}"
                    return "ERROR"
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
                if reg in self.registers:
                    a_value = self.registers["A"]
                    operand = self.registers[reg]
                    
                    # Calculate auxiliary carry for subtraction
                    ac = 1 if (a_value & 0x0F) < (operand & 0x0F) else 0
                    
                    result = a_value - operand
                    carry = 1 if result < 0 else 0
                    
                    self.registers["A"] = result & 0xFF
                    self.update_flags(self.registers["A"], True, carry, True, ac)
                else:
                    self.error = f"Invalid register: {reg}"
                    return "ERROR"
                self.registers["PC"] += 1
            
            elif opcode == "INR":
                reg = instruction[1]
                if reg in self.registers:
                    self.registers[reg] = (self.registers[reg] + 1) & 0xFF
                    self.update_flags(self.registers[reg])
                else:
                    self.error = f"Invalid register: {reg}"
                    return "ERROR"
                self.registers["PC"] += 1
            
            elif opcode == "DCR":
                reg = instruction[1]
                if reg in self.registers:
                    self.registers[reg] = (self.registers[reg] - 1) & 0xFF
                    self.update_flags(self.registers[reg])
                else:
                    self.error = f"Invalid register: {reg}"
                    return "ERROR"
                self.registers["PC"] += 1
            
            # Branching instructions
            elif opcode == "JMP":
                addr = self._parse_number(instruction[1])
                self.registers["PC"] = addr & 0xFFFF
            
            elif opcode == "JZ":
                addr = self._parse_number(instruction[1])
                if self.flags["Z"] == 1:
                    self.registers["PC"] = addr & 0xFFFF
                else:
                    self.registers["PC"] += 3
            
            elif opcode == "JNZ":
                addr = self._parse_number(instruction[1])
                if self.flags["Z"] == 0:
                    self.registers["PC"] = addr & 0xFFFF
                else:
                    self.registers["PC"] += 3
            
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
                jump_target = instruction[1].strip(',;')
                
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
            
            else:
                self.error = f"Unknown opcode: {opcode}"
                return "ERROR"
            
            return "OK"
            
        except Exception as e:
            self.error = f"Error executing {opcode}: {str(e)}"
            return "ERROR"

    def _get_reg_code(self, reg):
        """Returns the 3-bit register code used in opcode construction"""
        reg_codes = {
            "A": 7, "B": 0, "C": 1, "D": 2, 
            "E": 3, "H": 4, "L": 5, "M": 6
        }
        return reg_codes.get(reg, 0)

    def _get_rp_code(self, reg_pair):
        """Returns the 2-bit register pair code used in opcode construction"""
        rp_codes = {
            "B": 0,  # BC pair
            "D": 1,  # DE pair
            "H": 2,  # HL pair
            "SP": 3  # SP
        }
        return rp_codes.get(reg_pair, 0)

    def _parse_number(self, value_str):
        """
        Parses a number according to 8085 conventions:
        - Symbol lookup from defined symbols table
        - Label lookup from defined labels
        - Hexadecimal if string ends with 'H'
        - Decimal otherwise
        """
        value_str = value_str.strip()
        
        # Check if it's a symbol first
        if hasattr(self, 'symbols') and value_str in self.symbols:
            return self.symbols[value_str]
        
        # Then check if it's a label
        if hasattr(self, 'labels') and value_str in self.labels:
            return self.labels[value_str]
        
        # Otherwise, parse as number
        if value_str.upper().endswith('H'):
            return int(value_str[:-1], 16)
        else:
            return int(value_str, 10)

    def is_program_memory(self, address):
        """Returns True if the address contains program code"""
        return address in self.program_memory_range