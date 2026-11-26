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
Example programs shown in the Examples menu. Each one demonstrates a part of
the simulator; every example is assembled and run by the test suite.
"""


class Example:
    def __init__(self, title, category, hint, source, setup=None):
        self.title = title
        self.category = category
        self.hint = hint  # how to run it, shown in the log when it is loaded
        self.source = source.strip("\n") + "\n"
        # Board set-up the example needs: {"wiring": {output: pin}, "sources": {counter: source}}
        self.setup = setup or {}


EXAMPLES = [
    Example(
        "Add Two Numbers",
        "Basics",
        "Step (F10) or Run (F5). The sum is stored at 2052H and the carry at 2053H.",
        """
; ==================================================================
;  ADD TWO 8-BIT NUMBERS
;  Adds the bytes at 2050H and 2051H.
;  Result: sum at 2052H, carry (0 or 1) at 2053H.
;  9AH + 7CH = 116H  ->  SUM = 16H, CARRY = 01H
; ==================================================================

        ORG 2000H
START:  LXI H, NUM1     ; HL points to the first number
        MOV A, M        ; A = first number
        INX H           ; HL points to the second number
        ADD M           ; A = A + second number, CY = carry out
        STA SUM         ; store the low 8 bits of the sum
        MVI A, 0
        ACI 0           ; A = 0 + 0 + CY  -> the carry as 0 or 1
        STA CARRY
        HLT

        ORG 2050H
NUM1:   DB 9AH
NUM2:   DB 7CH
SUM:    DS 1
CARRY:  DS 1
        END START
""",
    ),
    Example(
        "BCD Addition (DAA)",
        "Basics",
        "Step through and watch A, CY and AC before and after each DAA. Result at 2054H-2056H.",
        """
; ==================================================================
;  4-DIGIT BCD ADDITION WITH DAA
;  4795 + 3868 = 8663   (numbers stored low byte first)
;  DAA turns the binary sum of two BCD bytes back into BCD,
;  using the AC (half carry) and CY flags.
; ==================================================================

        ORG 2000H
START:  LDA NUM1        ; low byte: 95H
        MOV B, A
        LDA NUM2        ; low byte: 68H
        ADD B           ; 95H + 68H = FDH (binary)
        DAA             ; -> 63H, CY = 1 (decimal 95 + 68 = 163)
        STA RESULT
        LDA NUM1+1      ; high byte: 47H
        MOV B, A
        LDA NUM2+1      ; high byte: 38H
        ADC B           ; 47H + 38H + CY = 80H, AC = 1
        DAA             ; -> 86H (decimal 47 + 38 + 1 = 86)
        STA RESULT+1
        MVI A, 0
        RAL             ; A = carry out of the 4-digit sum
        STA RESULT+2
        HLT

        ORG 2050H
NUM1:   DB 95H, 47H     ; 4795
NUM2:   DB 68H, 38H     ; 3868
RESULT: DS 3            ; 63H, 86H, 00H  = 8663
        END START
""",
    ),
    Example(
        "Multiply (Shift and Add)",
        "Basics",
        "Run (F5) or step through. The 16-bit product 2328H is stored at 2052H (low) and 2053H (high).",
        """
; ==================================================================
;  8-BIT x 8-BIT UNSIGNED MULTIPLICATION (SHIFT AND ADD)
;  200 x 45 = 9000 = 2328H
;  The multiplier is examined MSB first: for each bit the product is
;  doubled (DAD H) and, if the bit is 1, the multiplicand is added.
; ==================================================================

        ORG 2000H
START:  LDA MULTIPLIER
        MOV C, A        ; C = multiplier (bits are shifted out of it)
        LDA MULTIPLICAND
        MOV E, A
        MVI D, 0        ; DE = multiplicand as a 16-bit number
        LXI H, 0        ; HL = product
        MVI B, 8        ; 8 multiplier bits
NEXT:   DAD H           ; product = product x 2 (clears CY here)
        MOV A, C
        RAL             ; next multiplier bit into CY
        MOV C, A
        JNC SKIP
        DAD D           ; bit was 1: product = product + multiplicand
SKIP:   DCR B
        JNZ NEXT
        SHLD PRODUCT    ; store the product, low byte first
        HLT

        ORG 2050H
MULTIPLICAND:   DB 200
MULTIPLIER:     DB 45
PRODUCT:        DS 2
        END START
""",
    ),
    Example(
        "Bubble Sort",
        "Basics",
        "Open the memory view at 2050H and Run (F5) or use Fast run to watch the list being sorted.",
        """
; ==================================================================
;  BUBBLE SORT
;  Sorts the 10 bytes at LIST (2050H) into ascending order.
;  Each pass swaps neighbours that are out of order; the sort stops
;  early when a pass makes no swaps.
; ==================================================================

COUNT   EQU 10

        ORG 2000H
START:  MVI B, COUNT-1      ; at most COUNT-1 passes
PASS:   LXI H, LIST
        MVI C, COUNT-1      ; comparisons per pass
        MVI D, 0            ; D = 1 when this pass swapped something
COMPARE:
        MOV A, M            ; A = current element
        INX H
        CMP M               ; compare with the next element
        JC NOSWAP           ; A < next: already in order
        JZ NOSWAP           ; equal: nothing to do
        MOV E, M            ; swap the two elements
        MOV M, A
        DCX H
        MOV M, E
        INX H
        MVI D, 1
NOSWAP: DCR C
        JNZ COMPARE
        MOV A, D
        ORA A               ; no swaps in this pass: the list is sorted
        JZ DONE
        DCR B
        JNZ PASS
DONE:   HLT

        ORG 2050H
LIST:   DB 39H, 0F2H, 05H, 7AH, 0C1H, 18H, 64H, 0AH, 9DH, 2EH
        END START
""",
    ),
    Example(
        "Block Copy and Checksum (Subroutines)",
        "Basics",
        "Step (F10) through the CALLs and watch SP and the STACK panel. The checksum is stored at 2210H.",
        """
; ==================================================================
;  BLOCK COPY AND CHECKSUM WITH SUBROUTINES
;  COPY copies a 16-byte message, CHKSUM adds up the copy.
;  Watch the STACK panel: CALL pushes the return address, PUSH/POP
;  save registers, RET pops the return address.
; ==================================================================

LEN     EQU 16

        ORG 2000H
START:  LXI SP, 3000H       ; set up the stack
        LXI H, MESSAGE      ; source
        LXI D, COPYBUF      ; destination
        MVI C, LEN
        CALL COPY
        LXI H, COPYBUF
        MVI C, LEN
        CALL CHKSUM
        STA CHECKSUM
        HLT

; COPY: copies C bytes from (HL) to (DE)
COPY:   MOV A, M
        STAX D
        INX H
        INX D
        DCR C
        JNZ COPY
        RET

; CHKSUM: returns in A the 8-bit sum of C bytes at (HL); keeps BC
CHKSUM: PUSH B
        XRA A
ADDNEXT:
        ADD M
        INX H
        DCR C
        JNZ ADDNEXT
        POP B
        RET

        ORG 2100H
MESSAGE:  DB 'Neo8085 is fun!', 0

        ORG 2200H
COPYBUF:  DS LEN
CHECKSUM: DS 1
        END START
""",
    ),
    Example(
        "LED Chaser (Real-Time Delay)",
        "I/O and Real Time",
        "Open the I/O tab and press Real-Time (Ctrl+F5) at 3.072 MHz: the LED moves every 0.1 s. Stop with F8.",
        """
; ==================================================================
;  LED CHASER
;  One LED walks across the 8 LEDs on output port 01H.
;  Run it with Real-Time (Ctrl+F5) on the 3.072 MHz clock: the delay
;  loop takes 12800 x 24 T = 307,200 T = exactly 0.1 s per step.
;  Try other CPU clocks to see the timing change.
; ==================================================================

LEDS    EQU 01H             ; LED output port (I/O tab)

        ORG 2000H
START:  LXI SP, 3000H
        MVI A, 00000001B    ; first LED on
LOOP:   OUT LEDS
        CALL DELAY
        RLC                 ; move to the next LED
        JMP LOOP

; DELAY: 0.1 s at 3.072 MHz, keeps A and the flags
DELAY:  PUSH PSW
        LXI B, 12800
DLOOP:  DCX B               ;  6 T
        MOV A, C            ;  4 T
        ORA B               ;  4 T  (Z = 1 when BC = 0)
        JNZ DLOOP           ; 10 T  -> 24 T per loop
        POP PSW
        RET
        END START
""",
    ),
    Example(
        "Switches to LEDs (IN / OUT)",
        "I/O and Real Time",
        "Press Real-Time (Ctrl+F5), then click the switches in the I/O tab. Port 02H shows how many are on.",
        """
; ==================================================================
;  SWITCHES TO LEDS
;  Reads the 8 switches (input port 00H), shows them on the LEDs
;  (output port 01H) and writes the number of switches that are on
;  to output port 02H (see the port table in the I/O tab).
; ==================================================================

SWITCHES EQU 00H
LEDS     EQU 01H
ONCOUNT  EQU 02H

        ORG 2000H
START:  IN SWITCHES         ; read the switches
        OUT LEDS            ; copy them to the LEDs
        MVI B, 0            ; B = number of 1 bits
        MVI C, 8
COUNTBIT:
        RLC                 ; next bit into CY (after 8 RLCs A is unchanged)
        JNC ZEROBIT
        INR B
ZEROBIT:
        DCR C
        JNZ COUNTBIT
        MOV A, B
        OUT ONCOUNT
        JMP START
        END START
""",
    ),
    Example(
        "Interrupts (TRAP, RST 7.5, INTR)",
        "Interrupts",
        "Press Real-Time (Ctrl+F5), then in the Interrupts tab press RST 7.5 (count up), "
        "INTR with RST 7 (add 10) and TRAP (clear). The count is shown on the LEDs.",
        """
; ==================================================================
;  INTERRUPT-DRIVEN COUNTER
;  The CPU sleeps in HLT; each interrupt wakes it up:
;    RST 7.5 (vector 003CH)  count + 1   (edge triggered, unmasked by SIM)
;    INTR    (RST 7 = 0038H) count + 10  (select "RST 7" next to INTR)
;    TRAP    (vector 0024H)  count = 0   (non-maskable)
;  RST 6.5 and RST 5.5 stay masked by SIM, so they are ignored.
;  The count (register B) is shown on the LEDs (port 01H).
; ==================================================================

LEDS    EQU 01H

        ORG 0024H           ; TRAP vector
        JMP TRAPISR
        ORG 0038H           ; RST 7 (supplied by the INTR device)
        JMP INTRISR
        ORG 003CH           ; RST 7.5 vector
        JMP R75ISR

        ORG 2000H
START:  LXI SP, 3000H
        MVI A, 00011011B    ; SIM: R7.5 reset, MSE = 1, M7.5 = 0, M6.5 = 1, M5.5 = 1
        SIM
        MVI B, 0
        CALL SHOW
        EI                  ; enable interrupts
WAIT:   HLT                 ; sleep until an interrupt arrives
        JMP WAIT

R75ISR: PUSH PSW            ; RST 7.5: count up
        INR B
        CALL SHOW
        POP PSW
        EI                  ; acknowledging cleared INTE: enable again
        RET

INTRISR:
        PUSH PSW            ; INTR: add 10
        MOV A, B
        ADI 10
        MOV B, A
        CALL SHOW
        POP PSW
        EI
        RET

TRAPISR:
        PUSH PSW            ; TRAP: clear the count
        MVI B, 0
        CALL SHOW
        POP PSW
        EI
        RET

SHOW:   MOV A, B            ; show the count on the LEDs
        OUT LEDS
        RET
        END START
""",
    ),
    Example(
        "Serial Output on SOD (SIM / RIM)",
        "I/O and Real Time",
        "Run (F5) and watch the SOD indicator in the I/O tab send 'A' bit by bit. "
        "Set SID first to see RIM read it (stored at 2050H).",
        """
; ==================================================================
;  SERIAL OUTPUT ON THE SOD PIN
;  Sends the character 'A' (41H) like a UART: start bit (0), 8 data
;  bits LSB first, stop bit (1). SIM with SDE = 1 copies A bit 7 to SOD.
;  Finally RIM reads the SID pin (A bit 7) and stores it at 2050H.
; ==================================================================

        ORG 2000H
START:  MVI C, 'A'          ; character to send
        MVI A, 01000000B    ; SDE = 1, SOD = 0: start bit
        SIM
        MVI B, 8            ; 8 data bits
SENDBIT:
        MOV A, C
        RRC                 ; next bit (LSB first) into A bit 7
        MOV C, A
        ANI 10000000B       ; keep only that bit as SOD
        ORI 01000000B       ; SDE = 1
        SIM                 ; SOD = bit
        DCR B
        JNZ SENDBIT
        MVI A, 11000000B    ; SDE = 1, SOD = 1: stop bit (line idle)
        SIM
        RIM                 ; A bit 7 = SID pin
        ANI 80H
        STA SIDBIT
        HLT

        ORG 2050H
SIDBIT: DS 1
        END START
""",
    ),
    Example(
        "Macros and Conditional Assembly",
        "Advanced",
        "Assemble and step: the macros expand into normal instructions. A table of squares is built at 2060H.",
        """
; ==================================================================
;  MACROS, REPT AND CONDITIONAL ASSEMBLY (Intel syntax)
;  ADDMEM and WAITN are macros, IRP repeats a block for a list,
;  REPT with SET builds a table at assembly time, IF/ENDIF includes
;  code only when DEBUG is non-zero.
; ==================================================================

DEBUG   EQU 1               ; set to 0 and assemble again: the OUT disappears

ADDMEM  MACRO ADDR          ; A = A + byte at ADDR
        LXI H, ADDR
        ADD M
        ENDM

WAITN   MACRO COUNT         ; short delay loop with a LOCAL label
        LOCAL AGAIN
        MVI D, COUNT
AGAIN:  DCR D
        JNZ AGAIN
        ENDM

        ORG 2000H
START:  XRA A
        IRP V, <VAL1, VAL2, VAL3>
        ADDMEM V            ; expands once for each value
        ENDM
        STA TOTAL           ; 10 + 20 + 30 = 60 = 3CH
        WAITN 3
        WAITN 2             ; each expansion gets its own AGAIN label
        IF DEBUG
        OUT 01H             ; only assembled when DEBUG is non-zero
        ENDIF
        HLT

        ORG 2050H
VAL1:   DB 10
VAL2:   DB 20
VAL3:   DB 30
TOTAL:  DS 1

        ORG 2060H           ; squares of 0..15, computed by the assembler
N       SET 0
SQUARES:
        REPT 16
        DB N * N
N       SET N + 1
        ENDM
        END START
""",
    ),
    Example(
        "Undocumented Instructions",
        "Advanced",
        "Step (F10) and watch HL, DE, the V and K flags, and the STACK panel.",
        """
; ==================================================================
;  THE UNDOCUMENTED 8085 INSTRUCTIONS
;  DSUB  HL = HL - BC          ARHL  HL = HL >> 1 (arithmetic)
;  LDHI  DE = HL + byte        LDSI  DE = SP + byte
;  SHLX  (DE) = HL             LHLX  HL = (DE)
;  RDEL  rotate DE left through CY
;  JK / JNK  jump if K = 1 / 0 (K = V xor S: signed "less than")
;  RSTV  RST to 0040H if V (overflow) = 1
; ==================================================================

        ORG 0040H           ; RSTV vector
        MVI C, 0AAH         ; reached only through RSTV
        RET

        ORG 2000H
START:  LXI SP, 3000H
        LXI H, 5000         ; HL = 5000
        LXI B, 1234         ; BC = 1234
        DSUB                ; HL = 3766 = 0EB6H
        ARHL                ; HL = 1883 = 075BH
        LDHI 10H            ; DE = HL + 10H = 076BH
        SHLX                ; store HL at 076BH
        LXI H, 0
        LHLX                ; HL = 075BH again, loaded from 076BH
        LDSI 0              ; DE = SP = 3000H
        LXI D, 8001H
        ORA A               ; CY = 0
        RDEL                ; DE = 0002H, CY = 1
        MVI A, -5           ; 0FBH
        CPI 3               ; signed: -5 < 3  ->  K = 1
        JK LESS
        MVI E, 0            ; (not reached)
        HLT
LESS:   MVI A, 7FH
        ADI 1               ; 7FH + 1 = 80H: signed overflow, V = 1
        RSTV                ; V = 1: calls 0040H, which sets C = 0AAH
        HLT
        END START
""",
    ),
    Example(
        "Machine Cycles Tour",
        "Advanced",
        "Open the Bus Cycles tab (and Ctrl+T for the timing diagram), then Step (F10) one instruction at a time.",
        """
; ==================================================================
;  MACHINE CYCLES TOUR
;  Step (F10) with the Bus Cycles tab open, or press Ctrl+T for the
;  timing diagram. Each instruction uses a different mix of machine
;  cycles: OF = opcode fetch, MR/MW = memory read/write,
;  IOR/IOW = I/O read/write, BI = bus idle.
; ==================================================================

        ORG 2000H
START:  MOV A, B            ; OF                        4 T
        MVI A, 42H          ; OF MR                     7 T
        LXI H, DATA         ; OF MR MR                 10 T
        MOV M, A            ; OF MW                     7 T
        INR M               ; OF MR MW (read-modify-write) 10 T
        LDA DATA            ; OF MR MR MR              13 T
        STA DATA+1          ; OF MR MR MW              13 T
        LXI SP, 3000H       ; OF MR MR                 10 T
        PUSH H              ; OF(6 T) MW MW            12 T
        POP D               ; OF MR MR                 10 T
        CALL SUBR           ; OF(6 T) MR MR MW MW      18 T
        DAD D               ; OF BI BI (no ALE)        10 T
        IN 00H              ; OF MR IOR                10 T
        OUT 01H             ; OF MR IOW                10 T
        XRA A
        JNZ START           ; not taken: OF MR          7 T
        HLT                 ; OF + HALT state           5 T

SUBR:   XTHL                ; OF MR MR MW MW           16 T
        XTHL
        RET                 ; OF MR MR                 10 T

        ORG 2050H
DATA:   DS 2
        END START
""",
    ),
    Example(
        "8255 PPI: Mode 0 Ports and Bit Set/Reset",
        "Peripherals (8255 / 8253)",
        "Open the 8255 tab and press Real-Time (Ctrl+F5). Click the port A pins: port B copies them, "
        "PC7-PC4 show how many are 1, and PC0 (set with bit set/reset) lights when any is 1.",
        """
; ==================================================================
;  8255 PPI IN MODE 0 (ports 40H-43H)
;  Control word 90H = 1001 0000B:
;    D7 = 1 mode set, group A mode 0, port A input,
;    PC7-PC4 output, group B mode 0, port B output, PC3-PC0 output
;  Port B shows the port A pins, PC7-PC4 the number of 1 bits.
;  PC0 is then set with a bit set/reset command (D7 = 0) when any
;  port A pin is 1: BSR changes one port C bit without touching
;  the others.
; ==================================================================

PORTA   EQU 40H
PORTB   EQU 41H
PORTC   EQU 42H
CWR     EQU 43H

        ORG 2000H
START:  MVI A, 90H          ; configure the 8255
        OUT CWR
LOOP:   IN PORTA            ; read the input pins
        OUT PORTB           ; and show them on port B
        MVI B, 0            ; count the 1 bits
        MVI C, 8
NEXTBIT:
        RLC                 ; after 8 RLCs A is unchanged
        JNC ZERO
        INR B
ZERO:   DCR C
        JNZ NEXTBIT
        MOV A, B
        RLC                 ; count to PC7-PC4 (PC3-PC0 = 0)
        RLC
        RLC
        RLC
        OUT PORTC
        MOV A, B
        ORA A
        JZ LOOP             ; no 1 bits: PC0 stays 0
        MVI A, 00000001B    ; bit set/reset: bit 0 (D3-D1 = 000), set (D0 = 1)
        OUT CWR
        JMP LOOP
        END START
""",
    ),
    Example(
        "8253 PIT: Real-Time Clock with Timer Interrupts",
        "Peripherals (8255 / 8253)",
        "Press Real-Time (Ctrl+F5) at 3.072 MHz and open the 8253 tab: counter 0 interrupts every "
        "10 ms on RST 7.5, the LEDs count seconds and OUT1 blinks at 1 Hz.",
        """
; ==================================================================
;  REAL-TIME CLOCK WITH THE 8253 (ports 50H-53H)
;  Counter 0: mode 2 (rate generator), count 30720, clocked by the
;    CPU's CLK OUT: one pulse every 30720 T = 10 ms at 3.072 MHz.
;    OUT0 is wired to RST 7.5 (set up when this example is loaded).
;  Counter 1: mode 3 (square wave), count 100, clocked by OUT0:
;    a 1 Hz square wave on OUT1.
;  The RST 7.5 routine counts 100 ticks per second and shows the
;  seconds on the LEDs (port 01H).
; ==================================================================

CNT0    EQU 50H
CNT1    EQU 51H
PITCW   EQU 53H
LEDS    EQU 01H

        ORG 003CH           ; RST 7.5 vector
        JMP TICK

        ORG 2000H
START:  LXI SP, 3000H
        MVI A, 00110100B    ; counter 0, LSB then MSB, mode 2, binary
        OUT PITCW
        MVI A, LOW 30720
        OUT CNT0
        MVI A, HIGH 30720
        OUT CNT0
        MVI A, 01110110B    ; counter 1, LSB then MSB, mode 3, binary
        OUT PITCW
        MVI A, 100
        OUT CNT1
        MVI A, 0
        OUT CNT1
        MVI A, 00011011B    ; SIM: reset R7.5, unmask RST 7.5 only
        SIM
        MVI B, 0            ; seconds
        MVI C, 100          ; ticks left in this second
        MOV A, B
        OUT LEDS
        EI
WAIT:   HLT                 ; sleep until the next timer interrupt
        JMP WAIT

TICK:   PUSH PSW            ; 10 ms timer interrupt
        DCR C
        JNZ DONE
        MVI C, 100          ; one second has passed
        INR B
        MOV A, B
        OUT LEDS
DONE:   POP PSW
        EI
        RET
        END START
""",
        setup={"wiring": {"OUT0": "RST7.5"}, "sources": {1: "OUT of previous counter"}},
    ),
    Example(
        "8255 PPI: Mode 1 Strobed Input with Interrupt",
        "Peripherals (8255 / 8253)",
        "Press Real-Time (Ctrl+F5), open the 8255 tab, set port A pins and press STB A: "
        "INTR A (wired to RST 5.5) interrupts the CPU, which copies the byte to port B.",
        """
; ==================================================================
;  8255 MODE 1: STROBED INPUT WITH INTERRUPT (ports 40H-43H)
;  Control word 0B0H = 1011 0000B: group A mode 1, port A input,
;    PC7-PC6 output, group B mode 0, port B output, PC3-PC0 output.
;  Port C then carries the handshake: PC4 = STB A (input),
;    PC5 = IBF A, PC3 = INTR A. INTE A is set with a bit set/reset
;    command on PC4. INTR A is wired to RST 5.5 (set up on loading).
;  Each strobe interrupts the CPU; the routine reads port A (which
;    clears IBF and INTR) and copies the byte to port B.
; ==================================================================

PORTA   EQU 40H
PORTB   EQU 41H
CWR     EQU 43H

        ORG 002CH           ; RST 5.5 vector
        JMP STROBED

        ORG 2000H
START:  LXI SP, 3000H
        MVI A, 0B0H         ; group A mode 1 input, port B mode 0 output
        OUT CWR
        MVI A, 00001001B    ; bit set/reset: PC4 = 1 -> INTE A = 1
        OUT CWR
        MVI A, 00001110B    ; SIM: unmask RST 5.5 only
        SIM
        MVI D, 0            ; number of bytes received
        EI
WAIT:   HLT
        JMP WAIT

STROBED:
        PUSH PSW
        IN PORTA            ; the strobed byte; clears IBF A and INTR A
        OUT PORTB
        INR D
        POP PSW
        EI
        RET
        END START
""",
        setup={"wiring": {"INTR-A": "RST5.5"}},
    ),
]
