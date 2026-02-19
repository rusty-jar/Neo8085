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


class AssemblyOutput:
    """Container for the results of assembly process"""

    def __init__(self):
        self.memory = bytearray(0x10000)  # 64KB memory space
        self.parsed_program = []
        self.line_to_address_map = {}
        self.address_to_line_map = {}
        self.labels = {}
        self.symbols = {}  # Store EQU symbol definitions
        self.program_end_address = 0
        self.program_memory_range = set()  # Code addresses (protected)
        self.data_memory_range = set()  # DS addresses (writable)
        self.starting_address = 0x0000


class Assembler8085:
    """
    8085 microprocessor assembly code parser and machine code generator.
    Handles parsing assembly source code into executable machine code.
    """

    def __init__(self):
        # Instruction metadata
        self.valid_opcodes = [
            "MVI",
            "MOV",
            "LXI",
            "LDA",
            "STA",
            "ADD",
            "ADI",
            "SUB",
            "INR",
            "DCR",
            "JMP",
            "JZ",
            "JNZ",
            "JC",
            "JNC",
            "JP",
            "JM",
            "JPE",
            "JPO",
            "HLT",
            "INX",
            "PUSH",
            "POP",
            "CALL",
            "RET",
            "CPI",
            "DAD",
            "XCHG",
            "DS",
            "ORG",
            "END",
            "EQU",
            "LDAX",
            "STAX",
            "LHLD",
            "SHLD",
            "PCHL",
            "SPHL",
            "XTHL",
            "ANA",
            "ANI",
            "ORA",
            "ORI",
            "XRA",
            "XRI",
            "CMA",
            "CMC",
            "STC",
            "RLC",
            "RRC",
            "RAL",
            "RAR",
            "ADC",
            "ACI",
            "SBB",
            "SBI",
            "DAA",
            "DCX",
            "CC",
            "CNC",
            "CZ",
            "CNZ",
            "CP",
            "CM",
            "CPE",
            "CPO",
            "RC",
            "RNC",
            "RZ",
            "RNZ",
            "RP",
            "RM",
            "RPE",
            "RPO",
            "RST",
            "CMP",
            "NOP",
            "SUI",
            "IN",
            "OUT",
            "EI",
            "DI",
            "RIM",
            "SIM",
        ]
        self.valid_registers = ["B", "C", "D", "E", "H", "L", "M", "A"]
        self.valid_register_pairs = ["B", "D", "H", "SP"]

    def assemble(self, code):
        """
        Assembles the source code and returns the generated machine code
        along with metadata for debugging and execution.

        Args:
            code (list): List of assembly code lines, one per element
                Lines may contain labels, directives, instructions, and comments
                Comments start with ';' and extend to the end of the line
                Labels end with ':' and may be on the same line as an instruction

        Returns:
            AssemblyOutput: Object containing:
                - memory: Fully populated 64KB memory array with machine code
                - parsed_program: List of (address, tokens) tuples for each instruction
                - line_to_address_map: Maps source line numbers to memory addresses
                - address_to_line_map: Maps memory addresses to source line numbers
                - labels: Dictionary of label names to their addresses
                - symbols: Dictionary of EQU symbol names to their values
                - program_end_address: End address of the assembled program
                - program_memory_range: Set of addresses containing program code
                - data_memory_range: Set of addresses containing data
                - starting_address: Beginning address of the program

        Raises:
            SyntaxError: If there are syntax or semantic errors in the code
        """
        output = AssemblyOutput()

        # Convert program to uppercase for consistent parsing
        uppercase_code = []
        for line in code:
            uppercase_code.append(line.upper())

        code = uppercase_code

        # Special pre-pass: Process all EQU directives first
        self._preprocess_equ_directives(code, output)

        # First pass: Find labels and validate syntax
        self._first_pass(code, output)

        # Resolve any EQU directives that depend on labels from first pass
        self._resolve_pending_equs(code, output)

        # Second pass: Build program, resolve labels, and generate machine code
        self._second_pass(code, output)

        return output

    def _preprocess_equ_directives(self, code, output):
        """
        Pre-process to handle all EQU directives with support for nested definitions
        and arithmetic operations
        """
        # First, collect all EQU definitions
        equ_definitions = []
        for line_num, line in enumerate(code, 1):
            line = line.split(";", 1)[0].strip()  # Remove comments
            if not line:
                continue

            parts = line.split()
            if len(parts) >= 3 and "EQU" in parts:
                equ_idx = parts.index("EQU")
                if equ_idx > 0:  # Must have a symbol before EQU
                    symbol = parts[0]
                    if symbol.endswith(":"):  # Remove colon if present
                        symbol = symbol[:-1]
                    value_expr = " ".join(parts[equ_idx + 1 :])
                    equ_definitions.append((symbol, value_expr, line_num))

        # Process EQU definitions in order, resolving dependencies
        processed = set()
        while equ_definitions:
            progress = False
            remaining = []

            for symbol, value_expr, line_num in equ_definitions:
                # Try to evaluate the expression
                value = self._evaluate_expression(value_expr, output, line_num)

                if value is not None:  # Successfully evaluated
                    output.symbols[symbol] = value & 0xFFFF  # Ensure 16-bit value
                    processed.add(symbol)
                    progress = True
                else:
                    remaining.append((symbol, value_expr, line_num))

            if not progress and remaining:
                # Could not make progress in resolving symbols
                # Save unresolved EQUs for later resolution after first pass
                self._pending_equs = remaining
                return

            equ_definitions = remaining

        self._pending_equs = []

    def _resolve_pending_equs(self, code, output):
        """
        Resolve EQU directives that depend on labels discovered during the first pass.
        Called after _first_pass when all labels (from DS, code positions, etc.) are known.
        """
        if not hasattr(self, '_pending_equs') or not self._pending_equs:
            return

        equ_definitions = self._pending_equs

        while equ_definitions:
            progress = False
            remaining = []

            for symbol, value_expr, line_num in equ_definitions:
                # Try to evaluate — now labels from first pass are available in output.labels
                value = self._evaluate_expression(value_expr, output, line_num)

                if value is not None:
                    output.symbols[symbol] = value & 0xFFFF
                    progress = True
                else:
                    remaining.append((symbol, value_expr, line_num))

            if not progress and remaining:
                unresolved = [s for s, _, _ in remaining]
                raise SyntaxError(
                    f"Could not resolve EQU symbols: {', '.join(unresolved)}"
                )

            equ_definitions = remaining

        self._pending_equs = []

    def _evaluate_expression(self, expr, output, line_num):
        """
        Evaluate an arithmetic expression that may contain symbols and operators.
        Supports + - * / & | ^ << >> operators with left-to-right evaluation.

        Args:
            expr (str): The expression to evaluate (may contain operators and symbols)
            output (AssemblyOutput): Output container with symbol definitions
            line_num (int): Line number for error reporting

        Returns:
            int: The evaluated numeric result, or None if symbols can't be resolved yet

        Raises:
            SyntaxError: If the expression syntax is invalid
        """
        # Remove any comments that might be present in the expression
        if ";" in expr:
            expr = expr.split(";", 1)[0].strip()

        # Simple case: direct symbol or number with no operators
        if not any(
            op in expr for op in ["*", "/", "+", "-", "&", "|", "^", "<<", ">>"]
        ):
            return self._resolve_symbol_or_value(expr, output)

        # Tokenize the expression into operands and operators
        tokens = []
        current_token = ""
        operators = ["*", "/", "+", "-", "&", "|", "^"]  # Single-char operators
        multi_char_operators = ["<<", ">>"]

        # Parse the expression character by character, separating operands and operators
        i = 0
        while i < len(expr):
            # Skip whitespace between tokens
            if expr[i].isspace():
                if current_token:
                    tokens.append(current_token)
                    current_token = ""
                i += 1
                continue

            # Check for multi-character operators (<<, >>)
            if i < len(expr) - 1 and expr[i : i + 2] in multi_char_operators:
                if current_token:
                    tokens.append(current_token)
                    current_token = ""
                tokens.append(expr[i : i + 2])
                i += 2
                continue

            # Check for single-character operators (+, -, *, /, &, |, ^)
            if expr[i] in operators:
                if current_token:
                    tokens.append(current_token)
                    current_token = ""
                tokens.append(expr[i])
                i += 1
                continue

            # Add to current token (part of an operand)
            current_token += expr[i]
            i += 1

        # Add final token if any remains
        if current_token:
            tokens.append(current_token)

        # Simple validation - we need at least one operand
        if len(tokens) < 3:
            # Not a complete expression, might be missing operands
            if len(tokens) == 1:
                return self._resolve_symbol_or_value(tokens[0], output)
            return None

        # Evaluate the expression from left to right (no operator precedence)
        result = self._resolve_symbol_or_value(tokens[0], output)

        # If we can't resolve the first operand, can't evaluate the expression
        if result is None:
            return None

        # Apply each operator with left-to-right evaluation
        for i in range(1, len(tokens), 2):
            if i + 1 >= len(tokens):
                break  # No more operands

            operator = tokens[i]
            operand_str = tokens[i + 1]

            # Resolve the operand (could be a symbol or number)
            operand = self._resolve_symbol_or_value(operand_str, output)

            # If we can't resolve this operand, we can't evaluate further
            if operand is None:
                return None

            # Apply the operator to accumulate the result
            if operator == "+":
                result += operand
            elif operator == "-":
                result -= operand
            elif operator == "*":
                result *= operand
            elif operator == "/":
                result //= operand  # Integer division
            elif operator == "&":
                result &= operand  # Bitwise AND
            elif operator == "|":
                result |= operand  # Bitwise OR
            elif operator == "^":
                result ^= operand  # Bitwise XOR
            elif operator == "<<":
                result <<= operand  # Bit shift left
            elif operator == ">>":
                result >>= operand  # Bit shift right

        return result

    def _resolve_symbol_or_value(self, value_str, output):
        """
        Try to resolve a symbol or parse a value. Returns None if symbol not found.
        """
        value_str = value_str.strip()

        # Check if it's a symbol (EQU-defined)
        if value_str in output.symbols:
            return output.symbols[value_str]

        # Check if it's a label (from first pass)
        if value_str in output.labels:
            return output.labels[value_str]

        # Otherwise try to parse as a number
        try:
            return self._parse_number(value_str)
        except ValueError:
            return None

    def _first_pass(self, code, output):
        """
        First pass of assembly process - validates syntax and collects labels

        Args:
            code (list): Assembly code lines
            output (AssemblyOutput): Output container to store results

        Raises:
            SyntaxError: If there are syntax errors in the code
        """
        address = 0x0000
        first_org_seen = False

        for line_num, line in enumerate(code, 1):
            original_line = line
            line = line.split(";", 1)[0].strip()  # Remove comments
            if not line:
                continue

            # Check for labels
            parts = line.split()
            label = None

            if ":" in parts[0]:
                label_part = parts[0]
                if label_part.endswith(":"):
                    label = label_part[:-1]
                else:
                    # Label might be combined with instruction (LABEL:INSTR)
                    label_parts = label_part.split(":")
                    if len(label_parts) == 2:
                        label = label_parts[0]
                        # Reconstruct the line without the label
                        parts[0] = label_parts[1]
                        line = " ".join(parts)
                    else:
                        raise SyntaxError(
                            f"Line {line_num}: Invalid label format: {label_part}"
                        )

                if label:
                    if label in output.labels:
                        raise SyntaxError(f"Line {line_num}: Duplicate label: {label}")
                    output.labels[label] = address

            # Skip if line only contains a label
            if not parts or (len(parts) == 1 and parts[0].endswith(":")):
                continue

            # Get instruction/directive
            instruction = parts[0] if not parts[0].endswith(":") else parts[1]

            if instruction not in self.valid_opcodes:
                # Check if the instruction is combined with the label
                if ":" in instruction:
                    instr_parts = instruction.split(":")
                    if len(instr_parts) == 2 and instr_parts[1] in self.valid_opcodes:
                        instruction = instr_parts[1]
                    else:
                        raise SyntaxError(
                            f"Line {line_num}: Invalid instruction: {instruction}"
                        )
                else:
                    raise SyntaxError(
                        f"Line {line_num}: Unknown instruction: {instruction}"
                    )

            # Handle ORG directive
            if instruction == "ORG":
                if len(parts) < 2:
                    raise SyntaxError(f"Line {line_num}: ORG requires an address")

                try:
                    org_address = self._parse_number(parts[1])
                    address = org_address

                    if not first_org_seen:
                        output.starting_address = address
                        first_org_seen = True
                except ValueError:
                    raise SyntaxError(
                        f"Line {line_num}: Invalid ORG address: {parts[1]}"
                    )

                continue  # ORG doesn't generate code

            # Handle DS (Define Storage) directive
            if instruction == "DS":
                # Adjust for tokens layout based on label presence
                instruction_index = 0
                if parts[0].endswith(":"):
                    instruction_index = 1
                size_index = instruction_index + 1

                if len(parts) <= size_index:
                    raise SyntaxError(f"Line {line_num}: DS requires a size")

                try:
                    # Join remaining parts as potential expression
                    size_expr = " ".join(parts[size_index:])
                    # Remove any trailing comments (already stripped above, but be safe)
                    size_expr = size_expr.split(";")[0].strip()

                    # Try to resolve as symbol first
                    if size_expr in output.symbols:
                        size = output.symbols[size_expr]
                    else:
                        # Try evaluate as expression (handles "10 + 5", "CONST * 2", etc.)
                        result = self._evaluate_expression(size_expr, output, line_num)
                        if result is not None:
                            size = result
                        else:
                            size = self._parse_number(size_expr)

                    # Mark as data memory (writable), not program memory (protected)
                    for i in range(size):
                        output.data_memory_range.add(address + i)

                    address += size
                except ValueError as e:
                    raise SyntaxError(
                        f"Line {line_num}: Invalid DS size: {size_expr}"
                    )
                continue  # DS doesn't generate code

            # Handle END directive
            if instruction == "END":
                break  # End of assembly

            # Skip EQU directives in first pass (already processed)
            if instruction == "EQU":
                continue

            # Map the line to the current address
            output.line_to_address_map[line_num] = address
            output.address_to_line_map[address] = line_num

            # Calculate instruction size and advance address
            if (
                instruction == "MVI" or instruction == "ADI" or instruction == "CPI"
            ):  # 2 bytes
                address += 2
            elif (
                instruction == "LXI"
                or instruction == "LDA"
                or instruction == "STA"
                or instruction == "JMP"
                or instruction == "JZ"
                or instruction == "JNZ"
                or instruction == "JC"
                or instruction == "JNC"
                or instruction == "JP"
                or instruction == "JM"
                or instruction == "JPE"
                or instruction == "JPO"
                or instruction == "CALL"
            ):  # 3 bytes
                address += 3
            elif (
                instruction == "MOV"
                or instruction == "ADD"
                or instruction == "SUB"
                or instruction == "INR"
                or instruction == "DCR"
                or instruction == "HLT"
                or instruction == "INX"
                or instruction == "DAD"
                or instruction == "XCHG"
                or instruction == "PUSH"
                or instruction == "POP"
                or instruction == "RET"
            ):  # 1 byte
                address += 1
            elif (
                instruction == "LDAX"
                or instruction == "STAX"
                or instruction == "PCHL"
                or instruction == "SPHL"
                or instruction == "XTHL"
            ):  # 1 byte
                address += 1
            elif (
                instruction == "LHLD" or instruction == "SHLD"
            ):  # 3 bytes (opcode + address)
                address += 3
            elif instruction in ["ANA", "ORA", "XRA"]:  # 1 byte (with register operand)
                address += 1
            elif instruction in [
                "ANI",
                "ORI",
                "XRI",
            ]:  # 2 bytes (with immediate operand)
                address += 2
            elif instruction in [
                "CMA",
                "CMC",
                "STC",
                "RLC",
                "RRC",
                "RAL",
                "RAR",
            ]:  # 1 byte (no operands)
                address += 1
            elif instruction in ["ADC", "SBB"]:  # 1 byte (with register operand)
                address += 1
            elif instruction in ["ACI", "SBI"]:  # 2 bytes (with immediate operand)
                address += 2
            elif instruction in ["DAA"]:  # 1 byte (no operands)
                address += 1
            elif instruction == "DCX":  # 1 byte (with register pair operand)
                address += 1
            elif instruction in [
                "CC",
                "CNC",
                "CZ",
                "CNZ",
                "CP",
                "CM",
                "CPE",
                "CPO",
            ]:  # 3 bytes (conditional calls)
                address += 3
            elif instruction in [
                "RC",
                "RNC",
                "RZ",
                "RNZ",
                "RP",
                "RM",
                "RPE",
                "RPO",
            ]:  # 1 byte (conditional returns)
                address += 1
            elif instruction == "RST":  # 1 byte (restart)
                address += 1
            elif instruction == "CMP":  # 1 byte
                address += 1
            elif instruction == "NOP":  # 1 byte (no operands)
                address += 1
            elif instruction == "SUI":  # 2 bytes (opcode + immediate)
                address += 2
            elif instruction in ["IN", "OUT"]:  # 2 bytes (opcode + port)
                address += 2
            elif instruction in ["EI", "DI", "RIM", "SIM"]:  # 1 byte
                address += 1

    def _resolve_symbol_or_number(self, value_str, output):
        """
        Resolves a value that might be a symbol, label, expression, or numeric literal.
        Performs hierarchical lookup: first symbols, then labels, then expression, then number.

        Args:
            value_str (str): The value string to resolve
            output (AssemblyOutput): The output container with symbols and labels tables

        Returns:
            int: The resolved numeric value

        Raises:
            ValueError: If the value cannot be resolved to a number
        """
        value_str = value_str.strip()

        # Check if it's a symbol
        if value_str in output.symbols:
            return output.symbols[value_str]

        # If not a symbol, check if it's a label
        if value_str in output.labels:
            return output.labels[value_str]

        # Check if it contains an arithmetic expression
        if any(op in value_str for op in ["+", "-", "*", "/", "&", "|", "^", "<<", ">>"]):
            result = self._evaluate_expression(value_str, output, 0)
            if result is not None:
                return result

        # Otherwise try to parse as a number
        try:
            return self._parse_number(value_str)
        except ValueError:
            raise ValueError(f"Could not resolve value: {value_str}")

    def _join_expression_tokens(self, tokens):
        """
        Rejoin tokens that were split by whitespace but form a single expression.
        E.g., ["STA", "DATA_AREA", "+", "1"] -> ["STA", "DATA_AREA + 1"]
        E.g., ["LXI", "SP,", "STACK_AREA", "+", "64"] -> ["LXI", "SP,", "STACK_AREA + 64"]
        """
        if len(tokens) <= 2:
            return tokens

        operators = {"+", "-", "*", "/", "&", "|", "^", "<<", ">>"}

        # Find where the value operand starts
        # For 2-operand instructions like MVI A, 42H the register is tokens[1] (with
        # trailing comma) and value starts at tokens[2]
        # For 1-operand instructions like STA addr, value starts at tokens[1]
        value_start = 1
        if len(tokens) > 2 and tokens[1].endswith(","):
            value_start = 2

        # Check if any token after value_start is an operator
        has_expression = False
        for i in range(value_start + 1, len(tokens)):
            if tokens[i] in operators:
                has_expression = True
                break

        if has_expression:
            # Join everything from value_start onwards into one expression
            expr = " ".join(tokens[value_start:])
            return tokens[:value_start] + [expr]

        return tokens

    def _second_pass(self, code, output):
        """
        Second pass - generate machine code and build program structures
        """
        address = 0x0000
        for line_num, line in enumerate(code, 1):
            line = line.split(";", 1)[0].strip()  # Remove comments
            if not line:
                continue

            # Skip lines with only labels
            parts = line.split()
            if not parts:
                continue

            # Handle label-only lines
            if len(parts) == 1 and parts[0].endswith(":"):
                continue

            # Extract instruction, handling labels
            tokens = []
            if ":" in parts[0]:
                if parts[0].endswith(":"):  # Label is separate
                    if len(parts) == 1:
                        continue  # Label-only line
                    tokens = parts[1:]  # Skip the label
                else:  # Label is combined with instruction
                    label_parts = parts[0].split(":")
                    if len(label_parts) == 2:
                        tokens = [label_parts[1]] + parts[1:]
                    else:
                        continue  # Malformed line (error caught in first pass)
            else:
                tokens = parts

            opcode = tokens[0]

            # Join expression tokens split by whitespace
            # e.g., ["STA", "DATA_AREA", "+", "1"] -> ["STA", "DATA_AREA + 1"]
            tokens = self._join_expression_tokens(tokens)

            # Skip EQU directives
            if opcode == "EQU":
                continue

            # Handle ORG directive
            if opcode == "ORG":
                address = self._parse_number(tokens[1])
                continue

            # Handle DS directive
            if opcode == "DS":
                # Adjust for tokens layout based on label presence
                instruction_index = 0
                if parts[0].endswith(":"):
                    instruction_index = 1
                size_index = instruction_index + 1

                if len(parts) <= size_index:
                    raise SyntaxError(f"Line {line_num}: DS requires a size")

                try:
                    # Join remaining parts as potential expression
                    size_expr = " ".join(parts[size_index:])
                    # Remove any trailing comments (already stripped above, but be safe)
                    size_expr = size_expr.split(";")[0].strip()

                    # Try to resolve as symbol first
                    if size_expr in output.symbols:
                        size = output.symbols[size_expr]
                    else:
                        # Try evaluate as expression (handles "10 + 5", "CONST * 2", etc.)
                        result = self._evaluate_expression(size_expr, output, line_num)
                        if result is not None:
                            size = result
                        else:
                            size = self._parse_number(size_expr)

                    # Mark as data memory (writable), not program memory (protected)
                    for i in range(size):
                        output.data_memory_range.add(address + i)

                    address += size
                except ValueError as e:
                    raise SyntaxError(f"Line {line_num}: Invalid DS size: {size_expr}")
                continue

            # Handle END directive
            if opcode == "END":
                break

            # Store tokens for this instruction
            output.parsed_program.append((address, tokens))

            # Mark this memory address as part of program
            output.program_memory_range.add(address)

            # Generate machine code based on instruction type
            if opcode == "MVI":  # MVI r,data (2 bytes: opcode, immediate value)
                # MVI opcodes: base 0x06 + (reg_code * 8)
                # Register codes: B=0, C=1, D=2, E=3, H=4, L=5, M=6, A=7
                reg = tokens[1].strip(",")
                value_str = tokens[2].strip(",;")

                try:
                    value = self._resolve_symbol_or_number(value_str, output) & 0xFF
                    reg_code = self._get_reg_code(reg)
                    output.memory[address] = 0x06 + (reg_code * 8)
                    output.memory[address + 1] = value
                except ValueError as e:
                    raise SyntaxError(f"Line {line_num}: {str(e)}")

                output.program_memory_range.add(address + 1)
                address += 2

            elif opcode == "MOV":  # MOV r,r (1 byte)
                # MOV opcodes: 0x40 + (dest_reg * 8) + src_reg
                # Register codes: B=0, C=1, D=2, E=3, H=4, L=5, M=6, A=7
                dest_reg = tokens[1].strip(",")
                src_reg = tokens[2].strip(",;")

                # MOV M,M is invalid - opcode 0x76 is HLT
                if dest_reg == "M" and src_reg == "M":
                    raise SyntaxError(
                        f"Line {line_num}: MOV M,M is not a valid instruction (opcode 0x76 is HLT)"
                    )

                try:
                    dest_code = self._get_reg_code(dest_reg)
                    src_code = self._get_reg_code(src_reg)
                    output.memory[address] = 0x40 + (dest_code * 8) + src_code
                except ValueError as e:
                    raise SyntaxError(f"Line {line_num}: {str(e)}")

                address += 1

            elif (
                opcode == "LXI"
            ):  # LXI rp,data16 (3 bytes: opcode, low byte, high byte)
                # LXI opcodes: base 0x01 + (rp_code * 16)
                # Register pair codes: B=0, D=1, H=2, SP=3
                rp = tokens[1].strip(",")
                value_str = tokens[2].strip(",;")

                try:
                    value = self._resolve_symbol_or_number(value_str, output) & 0xFFFF
                    rp_code = self._get_rp_code(rp)
                    output.memory[address] = 0x01 + (rp_code * 16)
                    output.memory[address + 1] = value & 0xFF  # Low byte
                    output.memory[address + 2] = (value >> 8) & 0xFF  # High byte
                except ValueError as e:
                    raise SyntaxError(f"Line {line_num}: {str(e)}")

                output.program_memory_range.add(address + 1)
                output.program_memory_range.add(address + 2)
                address += 3

            elif (
                opcode == "LDA"
            ):  # LDA addr (3 bytes: opcode=0x3A, low byte, high byte)
                value_str = tokens[1].strip(",;")

                try:
                    value = self._resolve_symbol_or_number(value_str, output) & 0xFFFF
                    output.memory[address] = 0x3A
                    output.memory[address + 1] = value & 0xFF  # Low byte
                    output.memory[address + 2] = (value >> 8) & 0xFF  # High byte
                except ValueError as e:
                    raise SyntaxError(f"Line {line_num}: {str(e)}")

                output.program_memory_range.add(address + 1)
                output.program_memory_range.add(address + 2)
                address += 3

            elif (
                opcode == "STA"
            ):  # STA addr (3 bytes: opcode=0x32, low byte, high byte)
                value_str = tokens[1].strip(",;")

                try:
                    value = self._resolve_symbol_or_number(value_str, output) & 0xFFFF
                    output.memory[address] = 0x32
                    output.memory[address + 1] = value & 0xFF  # Low byte
                    output.memory[address + 2] = (value >> 8) & 0xFF  # High byte
                except ValueError as e:
                    raise SyntaxError(f"Line {line_num}: {str(e)}")

                output.program_memory_range.add(address + 1)
                output.program_memory_range.add(address + 2)
                address += 3

            elif opcode == "ADD":  # ADD r (1 byte)
                # ADD opcodes: 0x80 + reg_code
                reg = tokens[1].strip(",;")

                try:
                    reg_code = self._get_reg_code(reg)
                    output.memory[address] = 0x80 + reg_code
                except ValueError as e:
                    raise SyntaxError(f"Line {line_num}: {str(e)}")

                address += 1

            elif opcode == "ADI":  # ADI data (2 bytes: opcode=0xC6, immediate value)
                value_str = tokens[1].strip(",;")

                try:
                    value = self._resolve_symbol_or_number(value_str, output) & 0xFF
                    output.memory[address] = 0xC6
                    output.memory[address + 1] = value
                except ValueError as e:
                    raise SyntaxError(f"Line {line_num}: {str(e)}")

                output.program_memory_range.add(address + 1)
                address += 2

            elif opcode == "SUB":  # SUB r (1 byte)
                # SUB opcodes: 0x90 + reg_code
                reg = tokens[1].strip(",;")

                try:
                    reg_code = self._get_reg_code(reg)
                    output.memory[address] = 0x90 + reg_code
                except ValueError as e:
                    raise SyntaxError(f"Line {line_num}: {str(e)}")

                address += 1

            elif opcode == "INR":  # INR r (1 byte)
                # INR opcodes: 0x04 + (reg_code * 8)
                reg = tokens[1].strip(",;")

                try:
                    reg_code = self._get_reg_code(reg)
                    output.memory[address] = 0x04 + (reg_code * 8)
                except ValueError as e:
                    raise SyntaxError(f"Line {line_num}: {str(e)}")

                address += 1

            elif opcode == "DCR":  # DCR r (1 byte)
                # DCR opcodes: 0x05 + (reg_code * 8)
                reg = tokens[1].strip(",;")

                try:
                    reg_code = self._get_reg_code(reg)
                    output.memory[address] = 0x05 + (reg_code * 8)
                except ValueError as e:
                    raise SyntaxError(f"Line {line_num}: {str(e)}")

                address += 1

            elif opcode in [
                "JMP",
                "JZ",
                "JNZ",
                "JC",
                "JNC",
                "JP",
                "JM",
                "JPE",
                "JPO",
            ]:  # Jumps (3 bytes)
                # Jump opcodes: JMP=0xC3, JZ=0xCA, JNZ=0xC2, JC=0xDA, JNC=0xD2, JP=0xF2, JM=0xFA, JPE=0xEA, JPO=0xE2
                value_str = tokens[1].strip(",;")

                jump_opcodes = {
                    "JMP": 0xC3,
                    "JZ": 0xCA,
                    "JNZ": 0xC2,
                    "JC": 0xDA,
                    "JNC": 0xD2,
                    "JP": 0xF2,
                    "JM": 0xFA,
                    "JPE": 0xEA,
                    "JPO": 0xE2,
                }

                try:
                    value = self._resolve_symbol_or_number(value_str, output) & 0xFFFF
                    output.memory[address] = jump_opcodes[opcode]
                    output.memory[address + 1] = value & 0xFF  # Low byte
                    output.memory[address + 2] = (value >> 8) & 0xFF  # High byte
                except ValueError as e:
                    raise SyntaxError(f"Line {line_num}: {str(e)}")
                except KeyError:
                    raise SyntaxError(
                        f"Line {line_num}: Invalid jump instruction: {opcode}"
                    )

                output.program_memory_range.add(address + 1)
                output.program_memory_range.add(address + 2)
                address += 3

            elif opcode == "HLT":  # HLT (1 byte: opcode=0x76)
                output.memory[address] = 0x76
                address += 1

            elif opcode == "INX":  # INX rp (1 byte)
                # INX opcodes: 0x03 + (rp_code * 16)
                rp = tokens[1].strip(",;")

                try:
                    rp_code = self._get_rp_code(rp)
                    output.memory[address] = 0x03 + (rp_code * 16)
                except ValueError as e:
                    raise SyntaxError(f"Line {line_num}: {str(e)}")

                address += 1

            elif opcode == "PUSH":  # PUSH rp (1 byte)
                # PUSH opcodes: 0xC5 + (rp_code * 16)
                rp = tokens[1].strip(",;")

                # Special case: PUSH PSW (Program Status Word)
                if rp == "PSW":
                    output.memory[address] = 0xF5
                else:
                    try:
                        rp_code = self._get_rp_code(rp)
                        output.memory[address] = 0xC5 + (rp_code * 16)
                    except ValueError as e:
                        if rp != "PSW":  # PSW already handled
                            raise SyntaxError(f"Line {line_num}: {str(e)}")

                address += 1

            elif opcode == "POP":  # POP rp (1 byte)
                # POP opcodes: 0xC1 + (rp_code * 16)
                rp = tokens[1].strip(",;")

                # Special case: POP PSW (Program Status Word)
                if rp == "PSW":
                    output.memory[address] = 0xF1
                else:
                    try:
                        rp_code = self._get_rp_code(rp)
                        output.memory[address] = 0xC1 + (rp_code * 16)
                    except ValueError as e:
                        if rp != "PSW":  # PSW already handled
                            raise SyntaxError(f"Line {line_num}: {str(e)}")

                address += 1

            elif (
                opcode == "CALL"
            ):  # CALL addr (3 bytes: opcode=0xCD, low byte, high byte)
                value_str = tokens[1].strip(",;")

                try:
                    value = self._resolve_symbol_or_number(value_str, output) & 0xFFFF
                    output.memory[address] = 0xCD
                    output.memory[address + 1] = value & 0xFF  # Low byte
                    output.memory[address + 2] = (value >> 8) & 0xFF  # High byte
                except ValueError as e:
                    raise SyntaxError(f"Line {line_num}: {str(e)}")

                output.program_memory_range.add(address + 1)
                output.program_memory_range.add(address + 2)
                address += 3

            elif opcode == "RET":  # RET (1 byte: opcode=0xC9)
                output.memory[address] = 0xC9
                address += 1

            elif opcode == "CPI":  # CPI data (2 bytes: opcode=0xFE, immediate value)
                value_str = tokens[1].strip(",;")

                try:
                    value = self._resolve_symbol_or_number(value_str, output) & 0xFF
                    output.memory[address] = 0xFE
                    output.memory[address + 1] = value
                except ValueError as e:
                    raise SyntaxError(f"Line {line_num}: {str(e)}")

                output.program_memory_range.add(address + 1)
                address += 2

            elif opcode == "DAD":  # DAD rp (1 byte)
                # DAD opcodes: 0x09 + (rp_code * 16)
                rp = tokens[1].strip(",;")

                try:
                    rp_code = self._get_rp_code(rp)
                    output.memory[address] = 0x09 + (rp_code * 16)
                except ValueError as e:
                    raise SyntaxError(f"Line {line_num}: {str(e)}")

                address += 1

            elif opcode == "XCHG":  # XCHG (1 byte: opcode=0xEB)
                output.memory[address] = 0xEB
                address += 1

            elif opcode == "LDAX":  # LDAX rp (1 byte)
                # LDAX opcodes: B=0x0A, D=0x1A
                rp = tokens[1].strip(",;")

                if rp == "B":
                    output.memory[address] = 0x0A
                elif rp == "D":
                    output.memory[address] = 0x1A
                else:
                    raise SyntaxError(
                        f"Line {line_num}: LDAX only supports B or D register pairs"
                    )

                address += 1

            elif opcode == "STAX":  # STAX rp (1 byte)
                # STAX opcodes: B=0x02, D=0x12
                rp = tokens[1].strip(",;")

                if rp == "B":
                    output.memory[address] = 0x02
                elif rp == "D":
                    output.memory[address] = 0x12
                else:
                    raise SyntaxError(
                        f"Line {line_num}: STAX only supports B or D register pairs"
                    )

                address += 1

            elif (
                opcode == "LHLD"
            ):  # LHLD addr (3 bytes: opcode=0x2A, low byte, high byte)
                value_str = tokens[1].strip(",;")

                try:
                    value = self._resolve_symbol_or_number(value_str, output) & 0xFFFF
                    output.memory[address] = 0x2A
                    output.memory[address + 1] = value & 0xFF  # Low byte
                    output.memory[address + 2] = (value >> 8) & 0xFF  # High byte
                except ValueError as e:
                    raise SyntaxError(f"Line {line_num}: {str(e)}")

                output.program_memory_range.add(address + 1)
                output.program_memory_range.add(address + 2)
                address += 3

            elif (
                opcode == "SHLD"
            ):  # SHLD addr (3 bytes: opcode=0x22, low byte, high byte)
                value_str = tokens[1].strip(",;")

                try:
                    value = self._resolve_symbol_or_number(value_str, output) & 0xFFFF
                    output.memory[address] = 0x22
                    output.memory[address + 1] = value & 0xFF  # Low byte
                    output.memory[address + 2] = (value >> 8) & 0xFF  # High byte
                except ValueError as e:
                    raise SyntaxError(f"Line {line_num}: {str(e)}")

                output.program_memory_range.add(address + 1)
                output.program_memory_range.add(address + 2)
                address += 3

            elif opcode == "PCHL":  # PCHL (1 byte: opcode=0xE9)
                output.memory[address] = 0xE9
                address += 1

            elif opcode == "SPHL":  # SPHL (1 byte: opcode=0xF9)
                output.memory[address] = 0xF9
                address += 1

            elif opcode == "XTHL":  # XTHL (1 byte: opcode=0xE3)
                output.memory[address] = 0xE3
                address += 1

            elif opcode == "ANA":  # ANA r/M (1 byte): AND register/memory with A
                reg = tokens[1].strip(",;")
                if reg not in self.valid_registers:
                    raise SyntaxError(f"Line {line_num}: Invalid register '{reg}'")

                reg_code = self._get_reg_code(reg)
                output.memory[address] = 0xA0 | reg_code
                address += 1

            elif opcode == "ANI":  # ANI data (2 bytes): AND immediate with A
                value_str = tokens[1].strip(",;")
                try:
                    value = self._resolve_symbol_or_number(value_str, output) & 0xFF
                    output.memory[address] = 0xE6  # Opcode
                    output.memory[address + 1] = value  # Immediate data
                except ValueError as e:
                    raise SyntaxError(f"Line {line_num}: {str(e)}")

                output.program_memory_range.add(address + 1)
                address += 2

            elif opcode == "ORA":  # ORA r/M (1 byte): OR register/memory with A
                reg = tokens[1].strip(",;")
                if reg not in self.valid_registers:
                    raise SyntaxError(f"Line {line_num}: Invalid register '{reg}'")

                reg_code = self._get_reg_code(reg)
                output.memory[address] = 0xB0 | reg_code
                address += 1

            elif opcode == "ORI":  # ORI data (2 bytes): OR immediate with A
                value_str = tokens[1].strip(",;")
                try:
                    value = self._resolve_symbol_or_number(value_str, output) & 0xFF
                    output.memory[address] = 0xF6  # Opcode
                    output.memory[address + 1] = value  # Immediate data
                except ValueError as e:
                    raise SyntaxError(f"Line {line_num}: {str(e)}")

                output.program_memory_range.add(address + 1)
                address += 2

            elif opcode == "XRA":  # XRA r/M (1 byte): XOR register/memory with A
                reg = tokens[1].strip(",;")
                if reg not in self.valid_registers:
                    raise SyntaxError(f"Line {line_num}: Invalid register '{reg}'")

                reg_code = self._get_reg_code(reg)
                output.memory[address] = 0xA8 | reg_code
                address += 1

            elif opcode == "XRI":  # XRI data (2 bytes): XOR immediate with A
                value_str = tokens[1].strip(",;")
                try:
                    value = self._resolve_symbol_or_number(value_str, output) & 0xFF
                    output.memory[address] = 0xEE  # Opcode
                    output.memory[address + 1] = value  # Immediate data
                except ValueError as e:
                    raise SyntaxError(f"Line {line_num}: {str(e)}")

                output.program_memory_range.add(address + 1)
                address += 2

            elif opcode == "CMA":  # CMA (1 byte): Complement accumulator
                output.memory[address] = 0x2F
                address += 1

            elif opcode == "CMC":  # CMC (1 byte): Complement carry flag
                output.memory[address] = 0x3F
                address += 1

            elif opcode == "STC":  # STC (1 byte): Set carry flag
                output.memory[address] = 0x37
                address += 1

            elif opcode == "RLC":  # RLC (1 byte): Rotate accumulator left
                output.memory[address] = 0x07
                address += 1

            elif opcode == "RRC":  # RRC (1 byte): Rotate accumulator right
                output.memory[address] = 0x0F
                address += 1

            elif opcode == "RAL":  # RAL (1 byte): Rotate accumulator left through carry
                output.memory[address] = 0x17
                address += 1

            elif (
                opcode == "RAR"
            ):  # RAR (1 byte): Rotate accumulator right through carry
                output.memory[address] = 0x1F
                address += 1

            elif opcode == "ADC":  # ADC r/M (1 byte): Add with carry
                reg = tokens[1].strip(",;")
                if reg not in self.valid_registers:
                    raise SyntaxError(f"Line {line_num}: Invalid register '{reg}'")

                reg_code = self._get_reg_code(reg)
                output.memory[address] = 0x88 | reg_code
                address += 1

            elif opcode == "ACI":  # ACI data (2 bytes): Add immediate with carry
                value_str = tokens[1].strip(",;")
                try:
                    value = self._resolve_symbol_or_number(value_str, output) & 0xFF
                    output.memory[address] = 0xCE  # Opcode
                    output.memory[address + 1] = value  # Immediate data
                except ValueError as e:
                    raise SyntaxError(f"Line {line_num}: {str(e)}")

                output.program_memory_range.add(address + 1)
                address += 2

            elif opcode == "SBB":  # SBB r/M (1 byte): Subtract with borrow
                reg = tokens[1].strip(",;")
                if reg not in self.valid_registers:
                    raise SyntaxError(f"Line {line_num}: Invalid register '{reg}'")

                reg_code = self._get_reg_code(reg)
                output.memory[address] = 0x98 | reg_code
                address += 1

            elif opcode == "SBI":  # SBI data (2 bytes): Subtract immediate with borrow
                value_str = tokens[1].strip(",;")
                try:
                    value = self._resolve_symbol_or_number(value_str, output) & 0xFF
                    output.memory[address] = 0xDE  # Opcode
                    output.memory[address + 1] = value  # Immediate data
                except ValueError as e:
                    raise SyntaxError(f"Line {line_num}: {str(e)}")

                output.program_memory_range.add(address + 1)
                address += 2

            elif opcode == "DAA":  # DAA (1 byte): Decimal adjust accumulator
                output.memory[address] = 0x27
                address += 1

            elif opcode == "DCX":  # DCX rp (1 byte): Decrement register pair
                reg_pair = tokens[1].strip(",;")

                try:
                    rp_code = self._get_rp_code(reg_pair)
                    output.memory[address] = 0x0B + (rp_code * 16)
                except ValueError as e:
                    raise SyntaxError(f"Line {line_num}: {str(e)}")

                address += 1

            elif opcode in ["CC", "CNC", "CZ", "CNZ", "CP", "CM", "CPE", "CPO"]:
                # Conditional call opcodes mapping
                call_opcodes = {
                    "CC": 0xDC,  # Call if carry
                    "CNC": 0xD4,  # Call if no carry
                    "CZ": 0xCC,  # Call if zero
                    "CNZ": 0xC4,  # Call if not zero
                    "CP": 0xF4,  # Call if positive (S=0)
                    "CM": 0xFC,  # Call if minus (S=1)
                    "CPE": 0xEC,  # Call if parity even
                    "CPO": 0xE4,  # Call if parity odd
                }

                value_str = tokens[1].strip(",;")

                try:
                    value = self._resolve_symbol_or_number(value_str, output) & 0xFFFF
                    output.memory[address] = call_opcodes[opcode]
                    output.memory[address + 1] = value & 0xFF  # Low byte
                    output.memory[address + 2] = (value >> 8) & 0xFF  # High byte
                except ValueError as e:
                    raise SyntaxError(f"Line {line_num}: {str(e)}")

                output.program_memory_range.add(address + 1)
                output.program_memory_range.add(address + 2)
                address += 3

            elif opcode in ["RC", "RNC", "RZ", "RNZ", "RP", "RM", "RPE", "RPO"]:
                # Conditional return opcodes mapping
                ret_opcodes = {
                    "RC": 0xD8,  # Return if carry
                    "RNC": 0xD0,  # Return if no carry
                    "RZ": 0xC8,  # Return if zero
                    "RNZ": 0xC0,  # Return if not zero
                    "RP": 0xF0,  # Return if positive (S=0)
                    "RM": 0xF8,  # Return if minus (S=1)
                    "RPE": 0xE8,  # Return if parity even
                    "RPO": 0xE0,  # Return if parity odd
                }

                output.memory[address] = ret_opcodes[opcode]
                address += 1

            elif opcode == "RST":
                # RST n opcodes: 0xC7, 0xCF, 0xD7, 0xDF, 0xE7, 0xEF, 0xF7, 0xFF for RST 0-7
                # The number is 0-7 corresponding to 8 different restart addresses
                rst_num = self._parse_number(tokens[1].strip(",;"))

                if rst_num < 0 or rst_num > 7:
                    raise SyntaxError(
                        f"Line {line_num}: RST requires a number from 0-7"
                    )

                # Calculate opcode: RST n = 11NNN111 where NNN is the 3-bit value of n
                output.memory[address] = 0xC7 | (rst_num << 3)
                address += 1

            elif opcode == "CMP":  # CMP r/M (1 byte): Compare register/memory with A
                reg = tokens[1].strip(",;")
                if reg not in self.valid_registers:
                    raise SyntaxError(f"Line {line_num}: Invalid register '{reg}'")

                reg_code = self._get_reg_code(reg)
                output.memory[address] = 0xB8 | reg_code
                address += 1

            elif opcode == "NOP":  # NOP (1 byte: opcode=0x00)
                output.memory[address] = 0x00
                address += 1

            elif opcode == "SUI":  # SUI data (2 bytes: opcode=0xD6, immediate value)
                value_str = tokens[1].strip(",;")
                try:
                    value = self._resolve_symbol_or_number(value_str, output) & 0xFF
                    output.memory[address] = 0xD6
                    output.memory[address + 1] = value
                except ValueError as e:
                    raise SyntaxError(f"Line {line_num}: {str(e)}")
                output.program_memory_range.add(address + 1)
                address += 2

            elif opcode == "IN":  # IN port (2 bytes: opcode=0xDB, port address)
                value_str = tokens[1].strip(",;")
                try:
                    value = self._resolve_symbol_or_number(value_str, output) & 0xFF
                    output.memory[address] = 0xDB
                    output.memory[address + 1] = value
                except ValueError as e:
                    raise SyntaxError(f"Line {line_num}: {str(e)}")
                output.program_memory_range.add(address + 1)
                address += 2

            elif opcode == "OUT":  # OUT port (2 bytes: opcode=0xD3, port address)
                value_str = tokens[1].strip(",;")
                try:
                    value = self._resolve_symbol_or_number(value_str, output) & 0xFF
                    output.memory[address] = 0xD3
                    output.memory[address + 1] = value
                except ValueError as e:
                    raise SyntaxError(f"Line {line_num}: {str(e)}")
                output.program_memory_range.add(address + 1)
                address += 2

            elif opcode == "EI":  # EI (1 byte: opcode=0xFB)
                output.memory[address] = 0xFB
                address += 1

            elif opcode == "DI":  # DI (1 byte: opcode=0xF3)
                output.memory[address] = 0xF3
                address += 1

            elif opcode == "RIM":  # RIM (1 byte: opcode=0x20)
                output.memory[address] = 0x20
                address += 1

            elif opcode == "SIM":  # SIM (1 byte: opcode=0x30)
                output.memory[address] = 0x30
                address += 1

        # Update program metadata after assembly
        if output.parsed_program:
            output.program_end_address = address

    def _get_reg_code(self, reg):
        """Get numeric code for a register (B=0, C=1, D=2, E=3, H=4, L=5, M=6, A=7)"""
        if reg not in self.valid_registers:
            raise ValueError(f"Invalid register: {reg}")
        return self.valid_registers.index(reg)

    def _get_rp_code(self, reg_pair):
        """Get numeric code for a register pair (B=0, D=1, H=2, SP=3)"""
        if reg_pair not in self.valid_register_pairs:
            raise ValueError(f"Invalid register pair: {reg_pair}")
        return self.valid_register_pairs.index(reg_pair)

    def _parse_number(self, value_str):
        """
        Parse a numeric literal in either decimal or hexadecimal format.

        For hexadecimal, the format should be a number followed by 'H' (e.g., '3AH').
        For decimal, just the number is provided.

        Returns the parsed number as an integer.
        """
        value_str = value_str.strip()

        # Check for hexadecimal (suffix H)
        if value_str.upper().endswith("H"):
            hex_str = value_str[:-1]
            return int(hex_str, 16)

        # Otherwise, treat as decimal
        return int(value_str, 10)
