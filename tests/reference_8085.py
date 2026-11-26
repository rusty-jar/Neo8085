"""
An independent reference model of the 8085 instruction set, used only by the
differential tests. It is written from Intel's instruction descriptions,
shares no code or tables with src/processor.py, and favours the plainest
possible arithmetic over speed:

  * results and flags are computed with ordinary integer arithmetic
    (e.g. a borrow is "a < b + borrow", overflow is the sign rule of two's
    complement), not with the simulator's adder;
  * the instruction decoder is a separate table of (mask, pattern) entries;
  * T-states come from a separate table of the 8085 timings.

Undocumented behaviour follows the published analyses of the silicon:
  V (bit 1) = two's complement overflow of the 8-bit ALU result;
  K (bit 5) = V xor S after ALU operations, the 16-bit carry/borrow of INX/DCX;
  RLC and RAL set V like A + A; RRC, RAR and logic operations clear V.
"""

PARITY = [1 - bin(i).count("1") % 2 for i in range(256)]


class Ref8085:
    def __init__(self, memory, regs, flags_byte, input_ports):
        self.m = bytearray(memory)
        self.r = dict(regs)  # A B C D E H L SP PC
        self.load_flags(flags_byte)
        self.inp = bytearray(input_ports)
        self.out = bytearray(256)
        self.halted = False
        self.inte = 0
        self.masks = 7
        self.sod = 0
        self.r75 = 0
        self.t = 0

    # flags ------------------------------------------------------------
    def load_flags(self, f):
        self.S, self.Z, self.K, self.AC = (f >> 7) & 1, (f >> 6) & 1, (f >> 5) & 1, (f >> 4) & 1
        self.P, self.V, self.CY = (f >> 2) & 1, (f >> 1) & 1, f & 1

    def flags_byte(self):
        return (self.S << 7) | (self.Z << 6) | (self.K << 5) | (self.AC << 4) | (self.P << 2) | (self.V << 1) | self.CY

    def szp(self, r):
        self.S = r >> 7
        self.Z = int(r == 0)
        self.P = PARITY[r]

    # memory and registers ---------------------------------------------
    def rd(self, a):
        return self.m[a & 0xFFFF]

    def wr(self, a, v):
        self.m[a & 0xFFFF] = v & 0xFF

    def hl(self):
        return (self.r["H"] << 8) | self.r["L"]

    def get8(self, code):
        name = "BCDEHLMA"[code]
        return self.rd(self.hl()) if name == "M" else self.r[name]

    def set8(self, code, v):
        name = "BCDEHLMA"[code]
        if name == "M":
            self.wr(self.hl(), v)
        else:
            self.r[name] = v & 0xFF

    def get16(self, code):
        if code == 3:
            return self.r["SP"]
        hi, lo = ("BC", "DE", "HL")[code]
        return (self.r[hi] << 8) | self.r[lo]

    def set16(self, code, v):
        v &= 0xFFFF
        if code == 3:
            self.r["SP"] = v
            return
        hi, lo = ("BC", "DE", "HL")[code]
        self.r[hi], self.r[lo] = v >> 8, v & 0xFF

    def push(self, v):
        self.r["SP"] = (self.r["SP"] - 1) & 0xFFFF
        self.wr(self.r["SP"], v >> 8)
        self.r["SP"] = (self.r["SP"] - 1) & 0xFFFF
        self.wr(self.r["SP"], v & 0xFF)

    def pop(self):
        lo = self.rd(self.r["SP"])
        hi = self.rd(self.r["SP"] + 1)
        self.r["SP"] = (self.r["SP"] + 2) & 0xFFFF
        return (hi << 8) | lo

    def cond(self, cc):
        return [self.Z == 0, self.Z == 1, self.CY == 0, self.CY == 1,
                self.P == 0, self.P == 1, self.S == 0, self.S == 1][cc]

    # arithmetic -------------------------------------------------------
    def add(self, a, b, c):
        total = a + b + c
        r = total & 0xFF
        self.szp(r)
        self.CY = int(total > 0xFF)
        self.AC = int((a & 0xF) + (b & 0xF) + c > 0xF)
        self.V = int(((a ^ r) & (b ^ r) & 0x80) != 0)
        self.K = self.V ^ self.S
        return r

    def sub(self, a, b, borrow):
        r = (a - b - borrow) & 0xFF
        self.szp(r)
        self.CY = int(a < b + borrow)
        # the 8085 subtracts by adding the complement: AC is that addition's carry from bit 3
        self.AC = int((a & 0xF) + ((~b) & 0xF) + (1 - borrow) > 0xF)
        self.V = int(((a ^ b) & (a ^ r) & 0x80) != 0)
        self.K = self.V ^ self.S
        return r

    def logic(self, r, ac):
        self.szp(r)
        self.CY, self.AC, self.V = 0, ac, 0
        self.K = self.S
        return r

    def alu(self, op, v):
        a = self.r["A"]
        if op == 0:
            self.r["A"] = self.add(a, v, 0)
        elif op == 1:
            self.r["A"] = self.add(a, v, self.CY)
        elif op == 2:
            self.r["A"] = self.sub(a, v, 0)
        elif op == 3:
            self.r["A"] = self.sub(a, v, self.CY)
        elif op == 4:
            self.r["A"] = self.logic(a & v, 1)  # 8085: ANA sets AC
        elif op == 5:
            self.r["A"] = self.logic(a ^ v, 0)
        elif op == 6:
            self.r["A"] = self.logic(a | v, 0)
        else:
            self.sub(a, v, 0)  # CMP

    # one instruction ---------------------------------------------------
    def step(self):
        if self.halted:
            return
        pc = self.r["PC"]
        op = self.rd(pc)
        b1 = self.rd(pc + 1)
        w = (self.rd(pc + 2) << 8) | b1
        length = LENGTH[op]
        self.r["PC"] = (pc + length) & 0xFFFF
        self.t += self.execute(op, b1, w)

    def execute(self, op, b1, w):
        r = self.r
        ddd, sss, rp = (op >> 3) & 7, op & 7, (op >> 4) & 3
        if op == 0x76:
            self.halted = True
            return 5
        if 0x40 <= op <= 0x7F:
            self.set8(ddd, self.get8(sss))
            return 7 if 6 in (ddd, sss) else 4
        if 0x80 <= op <= 0xBF:
            self.alu(ddd, self.get8(sss))
            return 7 if sss == 6 else 4
        if op & 0xC7 == 0xC6:
            self.alu(ddd, b1)
            return 7
        if op & 0xC7 == 0x06:
            self.set8(ddd, b1)
            return 10 if ddd == 6 else 7
        if op & 0xC7 == 0x04:  # INR (CY unchanged)
            cy = self.CY
            self.set8(ddd, self.add(self.get8(ddd), 1, 0))
            self.CY = cy
            return 10 if ddd == 6 else 4
        if op & 0xC7 == 0x05:  # DCR: ALU adds FFH, CY unchanged
            cy = self.CY
            v = self.get8(ddd)
            self.set8(ddd, self.add(v, 0xFF, 0))
            self.CY = cy
            return 10 if ddd == 6 else 4
        if op & 0xCF == 0x01:
            self.set16(rp, w)
            return 10
        if op & 0xCF == 0x09:  # DAD
            a, b = self.hl(), self.get16(rp)
            total = a + b
            res = total & 0xFFFF
            self.CY = int(total > 0xFFFF)
            self.V = int(((a ^ res) & (b ^ res) & 0x8000) != 0)
            self.set16(2, res)
            return 10
        if op & 0xCF == 0x03:  # INX
            v = self.get16(rp)
            self.K = int(v == 0xFFFF)
            self.set16(rp, v + 1)
            return 6
        if op & 0xCF == 0x0B:  # DCX
            v = self.get16(rp)
            self.K = int(v == 0)
            self.set16(rp, v - 1)
            return 6
        if op in (0x02, 0x12):
            self.wr(self.get16(rp), r["A"])
            return 7
        if op in (0x0A, 0x1A):
            r["A"] = self.rd(self.get16(rp))
            return 7
        if op == 0x22:
            self.wr(w, r["L"]); self.wr(w + 1, r["H"])
            return 16
        if op == 0x2A:
            r["L"], r["H"] = self.rd(w), self.rd(w + 1)
            return 16
        if op == 0x32:
            self.wr(w, r["A"])
            return 13
        if op == 0x3A:
            r["A"] = self.rd(w)
            return 13
        a = r["A"]
        if op == 0x07:
            self.CY = a >> 7; self.V = (a >> 7) ^ ((a >> 6) & 1)
            r["A"] = ((a << 1) | (a >> 7)) & 0xFF
            return 4
        if op == 0x0F:
            self.CY = a & 1; self.V = 0
            r["A"] = (a >> 1) | ((a & 1) << 7)
            return 4
        if op == 0x17:
            c = self.CY
            self.CY = a >> 7; self.V = (a >> 7) ^ ((a >> 6) & 1)
            r["A"] = ((a << 1) | c) & 0xFF
            return 4
        if op == 0x1F:
            c = self.CY
            self.CY = a & 1; self.V = 0
            r["A"] = (a >> 1) | (c << 7)
            return 4
        if op == 0x27:  # DAA
            low, cy = 0, self.CY
            if (a & 0xF) > 9 or self.AC:
                low = 6
            high = 0
            if a > 0x99 or cy:
                high, cy = 0x60, 1
            r["A"] = self.add(a, low | high, 0)
            self.CY = cy
            return 4
        if op == 0x2F:
            r["A"] = (~a) & 0xFF
            return 4
        if op == 0x37:
            self.CY = 1
            return 4
        if op == 0x3F:
            self.CY ^= 1
            return 4
        if op == 0x00:
            return 4
        if op == 0x20:  # RIM (no pending interrupts, SID = 0)
            r["A"] = (self.r75 << 6) | (self.inte << 3) | self.masks
            return 4
        if op == 0x30:  # SIM
            if a & 0x08:
                self.masks = a & 7
            if a & 0x10:
                self.r75 = 0
            if a & 0x40:
                self.sod = a >> 7
            return 4
        if op == 0x08:  # DSUB: HL - BC
            l = self.sub(r["L"], r["C"], 0)
            h = self.sub(r["H"], r["B"], self.CY)
            r["H"], r["L"] = h, l
            self.Z = int(h == 0 and l == 0)
            return 10
        if op == 0x10:  # ARHL
            v = self.hl()
            self.CY = v & 1
            self.V = 0
            self.set16(2, (v >> 1) | (v & 0x8000))
            return 7
        if op == 0x18:  # RDEL
            v = self.get16(1)
            c = self.CY
            self.CY = v >> 15
            self.V = (v >> 15) ^ ((v >> 14) & 1)
            self.set16(1, (v << 1) | c)
            return 10
        if op == 0x28:
            self.set16(1, self.hl() + b1)
            return 10
        if op == 0x38:
            self.set16(1, r["SP"] + b1)
            return 10
        # C0-FF
        cc = ddd
        if op & 0xC7 == 0xC0:
            if self.cond(cc):
                r["PC"] = self.pop()
                return 12
            return 6
        if op & 0xC7 == 0xC2:
            if self.cond(cc):
                r["PC"] = w
                return 10
            return 7
        if op & 0xC7 == 0xC4:
            if self.cond(cc):
                self.push(r["PC"]); r["PC"] = w
                return 18
            return 9
        if op & 0xC7 == 0xC7:
            self.push(r["PC"]); r["PC"] = cc * 8
            return 12
        if op & 0xCF == 0xC1:
            v = self.pop()
            if rp == 3:
                r["A"] = v >> 8; self.load_flags(v & 0xFF)
            else:
                self.set16(rp, v)
            return 10
        if op & 0xCF == 0xC5:
            self.push((r["A"] << 8) | self.flags_byte() if rp == 3 else self.get16(rp))
            return 12
        if op == 0xC3:
            r["PC"] = w
            return 10
        if op == 0xC9:
            r["PC"] = self.pop()
            return 10
        if op == 0xCD:
            self.push(r["PC"]); r["PC"] = w
            return 18
        if op == 0xCB:  # RSTV
            if self.V:
                self.push(r["PC"]); r["PC"] = 0x40
                return 12
            return 6
        if op == 0xD3:
            self.out[b1] = a
            return 10
        if op == 0xDB:
            r["A"] = self.inp[b1]
            return 10
        if op == 0xD9:  # SHLX
            de = self.get16(1)
            self.wr(de, r["L"]); self.wr(de + 1, r["H"])
            return 10
        if op == 0xDD or op == 0xFD:  # JNK / JK
            if self.K == (1 if op == 0xFD else 0):
                r["PC"] = w
                return 10
            return 7
        if op == 0xE3:  # XTHL
            sp = r["SP"]
            l, h = self.rd(sp), self.rd(sp + 1)
            self.wr(sp, r["L"]); self.wr(sp + 1, r["H"])
            r["L"], r["H"] = l, h
            return 16
        if op == 0xE9:
            r["PC"] = self.hl()
            return 6
        if op == 0xEB:
            r["D"], r["H"] = r["H"], r["D"]
            r["E"], r["L"] = r["L"], r["E"]
            return 4
        if op == 0xED:  # LHLX
            de = self.get16(1)
            r["L"], r["H"] = self.rd(de), self.rd(de + 1)
            return 10
        if op == 0xF3:
            self.inte = 0
            return 4
        if op == 0xF9:
            r["SP"] = self.hl()
            return 6
        if op == 0xFB:
            self.inte = 1
            return 4
        raise AssertionError(f"reference model has no opcode {op:02X}H")


def _lengths():
    two = {0xC6, 0xCE, 0xD6, 0xDE, 0xE6, 0xEE, 0xF6, 0xFE, 0xD3, 0xDB, 0x28, 0x38}
    two |= {0x06 | (r << 3) for r in range(8)}
    three = {0x22, 0x2A, 0x32, 0x3A, 0xC3, 0xCD, 0xDD, 0xFD}
    three |= {0x01 | (p << 4) for p in range(4)}
    three |= {0xC2 | (c << 3) for c in range(8)} | {0xC4 | (c << 3) for c in range(8)}
    return [3 if op in three else 2 if op in two else 1 for op in range(256)]


LENGTH = _lengths()
