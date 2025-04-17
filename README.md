# Neo8085

<p align="center">
  <img src="8085-logo.jpeg" alt="Neo8085 Logo" width="200" />
</p>

<p align="center">
  <strong>A modern 8085 microprocessor simulator with an integrated development environment</strong>
</p>

<p align="center">
  <a href="#features">Features</a> •
  <a href="#installation">Installation</a> •
  <a href="#usage">Usage</a> •
  <a href="#documentation">Documentation</a> •
  <a href="#contributing">Contributing</a> •
  <a href="#license">License</a>
</p>

---

## Overview

**Neo8085** is a comprehensive 8085 microprocessor simulator designed for educational and development purposes. It provides a modern, feature-rich environment for writing, debugging, and executing 8085 assembly language programs with real-time visualization of processor state and memory.

---

## Features

### Integrated Development Environment
- Syntax highlighting for 8085 assembly language
- Line numbers and breakpoint management
- File operations (Open, Save, Save As)
- Modern UI with light theme

### Powerful Assembler
- Partial 8085 instruction set support
- Symbol and label resolution
- `EQU` directive with arithmetic expression support
- Comprehensive error reporting
- Support for `DS` directive for reserving memory bytes

### Execution and Debugging
- Step-by-step execution
- Continuous execution with breakpoints
- Real-time register and flag visualization
- Memory viewer and editor

### Advanced Tools
- Number format converter (Hex, Decimal, Binary, ASCII)
- Memory editor for direct manipulation
- Execution statistics tracking
- Detailed execution log

---

## Installation

### Prerequisites
- Python 3.13+
- PySide6 (Qt for Python)

### Installing from Source

1. **Clone the repository**:
   ```
   git clone https://github.com/rusty-jar/Neo8085.git
   cd Neo8085
   ```


2. **Install dependencies**:
   ```
   pip install -r requirements.txt
   ```

3. **Run the application**:
   ```
   python src/main.py
   ```

---

## Usage

### Writing Assembly Code
Use the built-in editor with syntax highlighting, line numbers, and breakpoint support.

### Assembling and Execution
- **Assemble**: Click "Assemble" or press `Ctrl+B`
- **Step Execution**: Click "Step" or press `F10`
- **Continuous Execution**: Click "Run" or press `F5`
- **Fast Execution**: Use "Run without Highlighting" or press `Ctrl+Shift+F5`
- **Debugging**: Set breakpoints by clicking line numbers or pressing `F9`

### Memory Manipulation
- Use the **Memory Editor** to write values directly
- View memory contents in the **Memory View** table
- Enable **Follow PC** to track the Program Counter automatically

---

## Documentation

### Supported Instructions

**Data Transfer**: 
- Register operations: `MOV`, `MVI`
- Memory operations: `LDA`, `STA`, `LDAX`, `STAX`, `LHLD`, `SHLD` 
- Register pair operations: `LXI`, `XCHG`, `XTHL`, `SPHL`, `PCHL`

**Arithmetic**:
- Basic operations: `ADD`, `ADI`, `SUB`, `INR`, `DCR`
- With carry: `ADC`, `ACI`, `SBB`, `SBI`
- Register pair operations: `INX`, `DCX`, `DAD`
- BCD operations: `DAA`

**Logical**:
- Bitwise operations: `ANA`, `ANI`, `ORA`, `ORI`, `XRA`, `XRI`, `CMA`
- Comparison: `CMP`, `CPI`
- Rotation: `RLC`, `RRC`, `RAL`, `RAR`
- Flag operations: `STC`, `CMC`

**Branching**:
- Unconditional: `JMP`, `CALL`, `RET`
- Conditional jumps: `JZ`, `JNZ`, `JC`, `JNC`, `JP`, `JM`, `JPE`, `JPO`
- Conditional calls: `CZ`, `CNZ`, `CC`, `CNC`, `CP`, `CM`, `CPE`, `CPO`
- Conditional returns: `RZ`, `RNZ`, `RC`, `RNC`, `RP`, `RM`, `RPE`, `RPO`
- Restart: `RST 0-7`

**Stack Operations**:
- `PUSH`, `POP`

**Machine Control**:
- `HLT`, `NOP`

**Not Implemented**:
- I/O operations: `IN`, `OUT`
- Interrupt control: `EI`, `DI`, `RIM`, `SIM`

### Assembler Directives
- `ORG`: Set starting address
- `EQU`: Define constants (supports arithmetic)
- `DS`: Reserve memory space
- `END`: Mark the end of the program (currently just a placeholder)

### Keyboard Shortcuts

| Shortcut            | Action                    |
|---------------------|---------------------------|
| Ctrl+N              | New File                  |
| Ctrl+O              | Open Program              |
| Ctrl+S              | Save                      |
| Ctrl+Shift+S        | Save As                   |
| Ctrl+B              | Assemble                  |
| F10                 | Step                      |
| F5                  | Run                       |
| Ctrl+Shift+F5       | Run without Highlighting  |
| F8                  | Stop                      |
| Ctrl+R              | Reset                     |
| F9                  | Add Breakpoint            |

---

## Screenshots

<p align="center">
  <img src="Neo8085-screenshot1.png" alt="Neo8085 Interface" width="800"/>
  <br/>
  <em>Neo8085 on startup</em>
</p>

<p align="center">
  <img src="Neo8085-screenshot2.png" alt="Neo8085 Interface" width="800"/>
  <br/>
  <em>Neo8085 Interface showing the simulator in action</em>
</p>

---

## Contributing

We welcome contributions to Neo8085!  
Here's how to get started:

1. Fork the repository
2. Create a new branch:
   ```bash
   git checkout -b feature-name
   ```
3. Make your changes and commit:
   ```bash
   git commit -m "Describe your changes"
   ```
4. Push to your fork:
   ```bash
   git push origin feature-name
   ```
5. Open a Pull Request

### Contribution Guidelines
- Follow existing code style and structure
- Write clear, descriptive commit messages
- Comment complex logic
- Update documentation and add tests for new features

---

## License

This project is licensed under the **GNU General Public License v3.0**.  
See the [LICENSE](LICENSE) file for details.

---

## Acknowledgements

- Inspired by the Intel 8085 instruction set
- Built using [PySide6 (Qt for Python)](https://wiki.qt.io/Qt_for_Python)

---

<p align="center">
  Made with ❤️ by Shahibur Rahaman <br/>
  &copy; 2025 Shahibur Rahaman
</p>

