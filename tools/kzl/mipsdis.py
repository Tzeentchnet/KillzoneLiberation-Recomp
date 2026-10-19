#!/usr/bin/env python3
"""Small Allegrex (PSP MIPS) disassembler for reading boot code and call sites.

    mipsdis.py <ELF> <start_hex> [<end_hex> | +count] [--base=HEX]
    mipsdis.py <ELF> --calls=<name or NID>      list every call to an import, with a0-a3 setup
    mipsdis.py <ELF> --xref=<string>            list code that builds the address of a string

Covers the integer ISA, Allegrex extras, COP0/COP1 and the VFPU load/stores. Other VFPU
encodings print as ".vfpu 0x...". Import stubs are named from the module's .lib.stub table and
research/nid_names.tsv. A lui/addiu/ori tracker annotates addresses that land on strings.
"""
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nidnames  # noqa: E402

REG = ["zero", "at", "v0", "v1", "a0", "a1", "a2", "a3", "t0", "t1", "t2", "t3", "t4", "t5", "t6", "t7",
       "s0", "s1", "s2", "s3", "s4", "s5", "s6", "s7", "t8", "t9", "k0", "k1", "gp", "sp", "fp", "ra"]


def s16(x):
    return x - 0x10000 if x & 0x8000 else x


class Elf:
    """Loads PT_LOAD segments of a PSP ELF/PRX at its link address (or --base for a PRX)."""

    def __init__(self, path, base=0):
        d = open(path, "rb").read()
        self.d = d
        self.type = struct.unpack_from("<H", d, 16)[0]
        phoff, shoff = struct.unpack_from("<II", d, 28)
        phnum, = struct.unpack_from("<H", d, 44)
        shnum, shstrndx = struct.unpack_from("<HH", d, 48)
        self.base = base if self.type == 0xFFA0 else 0
        self.segs = []
        for i in range(phnum):
            p = struct.unpack_from("<8I", d, phoff + i * 32)
            if p[0] == 1:
                self.segs.append((p[2] + self.base, p[1], p[4], p[5]))  # vaddr, off, filesz, memsz
        self.secs = {}
        if shnum:
            st = struct.unpack_from("<10I", d, shoff + shstrndx * 40)
            for i in range(shnum):
                s = struct.unpack_from("<10I", d, shoff + i * 40)
                nm = d[st[4] + s[0]:d.index(b"\0", st[4] + s[0])].decode("ascii", "replace")
                if nm:
                    self.secs[nm] = (s[3] + self.base, s[5], s[2])
        self.stubs = self._stubs()

    def read(self, addr, n):
        for va, off, fsz, msz in self.segs:
            if va <= addr and addr + n <= va + msz:
                o = addr - va
                b = self.d[off + o:off + min(o + n, fsz)] if o < fsz else b""
                return b + b"\0" * (n - len(b))
        return None

    def u32(self, addr):
        b = self.read(addr, 4)
        return struct.unpack("<I", b)[0] if b else None

    def cstr(self, addr, maxlen=200):
        b = self.read(addr, maxlen) if addr else None
        if not b or b"\0" not in b:
            return None
        s = b[:b.index(b"\0")]
        if len(s) < 2 or any(c < 0x20 and c not in (9, 10, 13) or c > 0x7E for c in s):
            return None
        return s.decode("ascii")

    def _stubs(self):
        names = nidnames.load()
        out = {}
        sec = self.secs.get(".lib.stub")
        if not sec:
            return out
        a, end = sec[0], sec[0] + sec[1]
        while a < end:
            lib_p, _ver, _attr, ln, nvar, nfunc, nids_p, funcs_p = struct.unpack("<IHHBBHII", self.read(a, 20))
            if self.base:  # PRX: pointers in the file are module-relative until relocated
                lib_p, nids_p, funcs_p = lib_p + self.base, nids_p + self.base, funcs_p + self.base
            lib = self.cstr(lib_p) or "?"
            for k in range(nfunc):
                nid = self.u32(nids_p + 4 * k)
                out[funcs_p + 8 * k] = names.get(nid, f"{lib}_{nid:08X}")
            a += max(ln, 5) * 4
        return out


def disasm(w, pc):
    """Return (mnemonic, operands, branch_target_or_None)."""
    op, rs, rt, rd, sa, fn = w >> 26, (w >> 21) & 31, (w >> 16) & 31, (w >> 11) & 31, (w >> 6) & 31, w & 63
    imm, R = w & 0xFFFF, REG
    bt = (pc + 4 + (s16(imm) << 2)) & 0xFFFFFFFF
    if w == 0:
        return "nop", "", None
    if op == 0:
        if fn == 0x21 and rt == 0:
            return "move", f"{R[rd]}, {R[rs]}", None
        if fn in (0, 2, 3):
            if fn == 2 and rs == 1:
                return "rotr", f"{R[rd]}, {R[rt]}, {sa}", None
            return ["sll", "", "srl", "sra"][fn], f"{R[rd]}, {R[rt]}, {sa}", None
        if fn in (4, 6, 7):
            if fn == 6 and sa == 1:
                return "rotrv", f"{R[rd]}, {R[rt]}, {R[rs]}", None
            return {4: "sllv", 6: "srlv", 7: "srav"}[fn], f"{R[rd]}, {R[rt]}, {R[rs]}", None
        if fn == 8:
            return "jr", R[rs], None
        if fn == 9:
            return "jalr", (R[rs] if rd == 31 else f"{R[rd]}, {R[rs]}"), None
        if fn in (0x0A, 0x0B):
            return ("movz", "movn")[fn - 0x0A], f"{R[rd]}, {R[rs]}, {R[rt]}", None
        if fn == 0x0C:
            return "syscall", f"{(w >> 6) & 0xFFFFF:#x}", None
        if fn == 0x0D:
            return "break", "", None
        if fn == 0x0F:
            return "sync", "", None
        if fn in (0x10, 0x12):
            return ("mfhi", "mflo")[fn == 0x12], R[rd], None
        if fn in (0x11, 0x13):
            return ("mthi", "mtlo")[fn == 0x13], R[rs], None
        if fn in (0x16, 0x17):
            return ("clz", "clo")[fn - 0x16], f"{R[rd]}, {R[rs]}", None
        names = {0x18: "mult", 0x19: "multu", 0x1A: "div", 0x1B: "divu", 0x1C: "madd", 0x1D: "maddu",
                 0x2E: "msub", 0x2F: "msubu"}
        if fn in names:
            return names[fn], f"{R[rs]}, {R[rt]}", None
        names = {0x20: "add", 0x21: "addu", 0x22: "sub", 0x23: "subu", 0x24: "and", 0x25: "or", 0x26: "xor",
                 0x27: "nor", 0x2A: "slt", 0x2B: "sltu", 0x2C: "max", 0x2D: "min"}
        if fn in names:
            return names[fn], f"{R[rd]}, {R[rs]}, {R[rt]}", None
    if op == 1:
        names = {0: "bltz", 1: "bgez", 2: "bltzl", 3: "bgezl", 0x10: "bltzal", 0x11: "bgezal",
                 0x12: "bltzall", 0x13: "bgezall"}
        if rt in names:
            return names[rt], f"{R[rs]}, {bt:#010x}", bt
    if op in (2, 3):
        t = ((pc + 4) & 0xF0000000) | ((w & 0x3FFFFFF) << 2)
        return ("j", "jal")[op - 2], f"{t:#010x}", t
    if op in (4, 5, 20, 21):
        m = {4: "beq", 5: "bne", 20: "beql", 21: "bnel"}[op]
        if op == 4 and rs == 0 and rt == 0:
            return "b", f"{bt:#010x}", bt
        return m, f"{R[rs]}, {R[rt]}, {bt:#010x}", bt
    if op in (6, 7, 22, 23):
        return {6: "blez", 7: "bgtz", 22: "blezl", 23: "bgtzl"}[op], f"{R[rs]}, {bt:#010x}", bt
    if op in (8, 9):
        if op == 9 and rs == 0:
            return "li", f"{R[rt]}, {s16(imm)}", None
        return ("addi", "addiu")[op - 8], f"{R[rt]}, {R[rs]}, {s16(imm)}", None
    if op in (0x0A, 0x0B):
        return ("slti", "sltiu")[op - 0x0A], f"{R[rt]}, {R[rs]}, {s16(imm)}", None
    if op in (0x0C, 0x0D, 0x0E):
        if op == 0x0D and rs == 0:
            return "li", f"{R[rt]}, {imm:#x}", None
        return ("andi", "ori", "xori")[op - 0x0C], f"{R[rt]}, {R[rs]}, {imm:#x}", None
    if op == 0x0F:
        return "lui", f"{R[rt]}, {imm:#x}", None
    if op == 0x10:
        return ("mfc0" if rs == 0 else "mtc0" if rs == 4 else "cop0"), f"{R[rt]}, ${rd}", None
    if op == 0x11:
        if rs == 0: return "mfc1", f"{R[rt]}, $f{rd}", None
        if rs == 2: return "cfc1", f"{R[rt]}, $fcr{rd}", None
        if rs == 4: return "mtc1", f"{R[rt]}, $f{rd}", None
        if rs == 6: return "ctc1", f"{R[rt]}, $fcr{rd}", None
        if rs == 8:
            return ["bc1f", "bc1t", "bc1fl", "bc1tl"][rt & 3], f"{bt:#010x}", bt
        ft, fs, fd = rt, rd, sa
        if rs == 0x10:
            two = {0: "add.s", 1: "sub.s", 2: "mul.s", 3: "div.s"}
            one = {4: "sqrt.s", 5: "abs.s", 6: "mov.s", 7: "neg.s", 0x0C: "round.w.s", 0x0D: "trunc.w.s",
                   0x0E: "ceil.w.s", 0x0F: "floor.w.s", 0x24: "cvt.w.s"}
            if fn in two:
                return two[fn], f"$f{fd}, $f{fs}, $f{ft}", None
            if fn in one:
                return one[fn], f"$f{fd}, $f{fs}", None
            if fn >= 0x30:
                c = ["f", "un", "eq", "ueq", "olt", "ult", "ole", "ule", "sf", "ngle", "seq", "ngl", "lt", "nge", "le", "ngt"]
                return f"c.{c[fn & 15]}.s", f"$f{fs}, $f{ft}", None
        if rs == 0x14 and fn == 0x20:
            return "cvt.s.w", f"$f{fd}, $f{fs}", None
    if op == 0x12:
        if rs == 8:
            return ["bvf", "bvt", "bvfl", "bvtl"][rt & 3], f"{(w >> 18) & 7}, {bt:#010x}", bt
        return f"cop2.{rs}", f"{R[rt]}, {w & 0xFF:#x}", None
    if op == 0x1F:
        if fn == 0:
            return "ext", f"{R[rt]}, {R[rs]}, {sa}, {rd + 1}", None
        if fn == 4:
            return "ins", f"{R[rt]}, {R[rs]}, {sa}, {rd - sa + 1}", None
        if fn == 0x20:
            m = {2: "wsbh", 3: "wsbw", 0x10: "seb", 0x14: "bitrev", 0x18: "seh"}.get(sa)
            if m:
                return m, f"{R[rd]}, {R[rt]}", None
    mem = {0x20: "lb", 0x21: "lh", 0x22: "lwl", 0x23: "lw", 0x24: "lbu", 0x25: "lhu", 0x26: "lwr",
           0x28: "sb", 0x29: "sh", 0x2A: "swl", 0x2B: "sw", 0x2E: "swr", 0x30: "ll", 0x38: "sc"}
    if op in mem:
        return mem[op], f"{R[rt]}, {s16(imm)}({R[rs]})", None
    if op in (0x31, 0x39):
        return ("lwc1", "swc1")[op == 0x39], f"$f{rt}, {s16(imm)}({R[rs]})", None
    if op == 0x2F:
        return "cache", f"{rt:#x}, {s16(imm)}({R[rs]})", None
    if op in (0x32, 0x3A, 0x36, 0x3E):
        m = {0x32: "lv.s", 0x3A: "sv.s", 0x36: "lv.q", 0x3E: "sv.q"}[op]
        return m, f"v{((w >> 16) & 31) | ((w & 3) << 5):#x}, {s16(imm & 0xFFFC)}({R[rs]})", None
    return ".vfpu" if op in (0x18, 0x19, 0x1B, 0x34, 0x37, 0x3C, 0x3D, 0x3F) else ".word", f"{w:#010x}", None


class Tracker:
    """Forward constant tracker over a straight-line window (enough for argument setup)."""

    def __init__(self):
        self.v = {0: 0}

    def step(self, w):
        op, rs, rt, rd, fn = w >> 26, (w >> 21) & 31, (w >> 16) & 31, (w >> 11) & 31, w & 63
        imm = w & 0xFFFF
        dst, val = None, None
        if op == 0x0F:
            dst, val = rt, imm << 16
        elif op in (8, 9):
            dst = rt
            val = (self.v[rs] + s16(imm)) & 0xFFFFFFFF if rs in self.v else None
        elif op == 0x0D:
            dst = rt
            val = self.v[rs] | imm if rs in self.v else None
        elif op == 0 and fn in (0x21, 0x25) and rt == 0:
            dst, val = rd, self.v.get(rs)
        elif op == 0 and fn == 0x21:
            dst = rd
            val = (self.v[rs] + self.v[rt]) & 0xFFFFFFFF if rs in self.v and rt in self.v else None
        elif op in (0x20, 0x21, 0x23, 0x24, 0x25, 0x22, 0x26):
            dst = rt
        elif op == 0 and fn not in (8, 0x0C, 0x0D, 0x11, 0x13, 0x18, 0x19, 0x1A, 0x1B, 0x1C, 0x1D, 0x2E, 0x2F):
            dst = rd
        elif op in (0x0A, 0x0B, 0x0C, 0x0E) or op == 0x1F:
            dst = rd if op == 0x1F and fn == 0x20 else rt
        elif op == 0x11 and rs in (0, 2):
            dst = rt
        elif op == 3 or (op == 0 and fn == 9):
            for r in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 24, 25, 31):
                self.v.pop(r, None)
            return None, None
        if dst:
            if val is None:
                self.v.pop(dst, None)
            else:
                self.v[dst] = val
        return dst, val


def annotate(elf, w, tr):
    dst, val = tr.step(w)
    if dst and val is not None:
        s = elf.cstr(val)
        if s is not None:
            return f'{REG[dst]} = {val:#010x} "{s[:80]}"'
        if (w >> 26) != 0x0F:
            return f"{REG[dst]} = {val:#x}"
    return ""


def listing(elf, start, end):
    tr = Tracker()
    pc = start
    while pc < end:
        w = elf.u32(pc)
        if w is None:
            break
        m, ops, t = disasm(w, pc)
        note = annotate(elf, w, tr)
        if t is not None and t in elf.stubs:
            note = f"-> {elf.stubs[t]}"
        print(f"{pc:08x}: {w:08x}  {m:<8} {ops:<34} {'; ' + note if note else ''}")
        pc += 4


def code_ranges(elf):
    return [(a, a + n) for nm, (a, n, fl) in elf.secs.items() if fl & 4 and not nm.startswith(".sceStub")]


def find_calls(elf, target_name, window=24):
    tgt = [a for a, n in elf.stubs.items() if n == target_name or n.endswith(target_name)]
    if not tgt:
        print(f"no import named {target_name}")
        return
    for lo, hi in code_ranges(elf):
        for pc in range(lo, hi, 4):
            w = elf.u32(pc)
            if w >> 26 == 3 and (((pc + 4) & 0xF0000000) | ((w & 0x3FFFFFF) << 2)) in tgt:
                print(f"--- call at {pc:08x} -> {elf.stubs[tgt[0]]}")
                listing(elf, max(lo, pc - 4 * window), pc + 8)


def find_xref(elf, needle):
    hits = []
    for lo, hi in code_ranges(elf):
        tr = Tracker()
        for pc in range(lo, hi, 4):
            w = elf.u32(pc)
            dst, val = tr.step(w)
            if dst and val is not None:
                s = elf.cstr(val)
                if s and needle in s:
                    hits.append((pc, s))
            if w >> 26 in (2,) or (w >> 26 == 0 and w & 63 == 8):
                tr = Tracker()
    for pc, s in hits:
        print(f"{pc:08x}: \"{s[:100]}\"")


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    opts = dict((o[2:].split("=", 1) + [""])[:2] for o in argv[1:] if o.startswith("--"))
    if not args:
        sys.stderr.write(__doc__)
        return 2
    elf = Elf(args[0], int(opts.get("base", "0"), 16))
    if "calls" in opts:
        find_calls(elf, opts["calls"])
    elif "xref" in opts:
        find_xref(elf, opts["xref"])
    else:
        start = int(args[1], 16)
        if len(args) > 2:
            end = start + 4 * int(args[2][1:]) if args[2].startswith("+") else int(args[2], 16)
        else:
            end = start + 4 * 64
        listing(elf, start, end)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
