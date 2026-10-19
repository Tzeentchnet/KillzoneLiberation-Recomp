#!/usr/bin/env python3
"""Recover switch jump tables behind computed `jr` sites in KZL.PRX.  -> T-2.6, F-017

    jumptab.py <KZL.PRX> [--base=0x08804000] [--toml=research/kzl_jumptables.toml] [-v]

ProDG/GCC emits every switch the same way (indices bounded by sltiu, table in .rodata):

    sltiu  rC, rI, N              ; N = case count (slti when signed)
    beq[l] rC, zero, default
    sll    rJ, rI, 2              ; may sit in a delay slot or be scheduled earlier
    lui    rB, %hi(table)         ; or a base kept in an s-register since the prologue
    addu   rT, rB, rJ             ; operand order varies
    lw     rX, %lo(table)(rT)
    jr     rX

Sparse switches are split into ranges: `slti rC, rS, HI; beq rC, zero, default;
addiu rI, rS, -LO` gives HI - LO cases, the lower bound being checked by earlier compares.

The pass follows the def chain back from each `jr rX` (rX != ra), folds lui/addiu/ori
constants, reads the table words and checks every target is in .text near the jr. Sites
that do not match are reported; they keep going through dispatch() unless overridden.

The PRX file is not relocated: lui immediates and table words are module offsets, so the
base is added here. The output TOML is the hint file the codegen uses to emit a C switch.
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mipsdis  # noqa: E402

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
SLICE = 24          # instructions searched back for each def in the lw/addu/sll chain
DEF_SEARCH = 2048   # how far back a constant base register may be set (prologue)
BOUND_SEARCH = 48   # instructions searched back from the sll for the bound check
MAX_SPAN = 0x10000  # case targets must lie this close to the jr
PRED_SEARCH = 0x4000  # bytes either side of a block searched for branches into it


def s16(x):
    return x - 0x10000 if x & 0x8000 else x


def dest_reg(w):
    """GPR written by an instruction (0 if none)."""
    op, fn = w >> 26, w & 63
    if op == 0:
        if fn in (8, 0x0C, 0x0D, 0x0F, 0x11, 0x13, 0x18, 0x19, 0x1A, 0x1B, 0x1C, 0x1D, 0x2E, 0x2F):
            return 0
        return (w >> 11) & 31
    if op in (8, 9, 0x0A, 0x0B, 0x0C, 0x0D, 0x0E, 0x0F, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26):
        return (w >> 16) & 31
    if op == 3:
        return 31
    if op == 0x1F:
        return (w >> 11) & 31 if w & 63 == 0x20 else (w >> 16) & 31
    if (op == 0x11 and (w >> 21) & 31 in (0, 2)) or (op == 0x12 and (w >> 21) & 31 == 3):
        return (w >> 16) & 31
    return 0


def is_uncond_end(w):
    """jr / j / b: the next-but-one instruction is not reached by fall-through."""
    if w is None:
        return False
    op, fn = w >> 26, w & 63
    return (op == 0 and fn == 8) or op == 2 or (op == 4 and (w >> 16) & 0x3FF == 0)


class Site:
    def __init__(self, elf, pc, text_lo):
        self.elf, self.pc, self.lo = elf, pc, text_lo

    def def_of(self, reg, before, limit=DEF_SEARCH):
        """Closest earlier instruction (in address order) that writes reg."""
        a = before - 4
        while a >= max(self.lo, before - 4 * limit):
            w = self.elf.u32(a)
            if dest_reg(w) == reg:
                return a, w
            a -= 4
        return None, None

    def reaching_defs(self, reg, before, depth=0):
        """Defs of reg that can reach `before`: [(addr, word, via_pred)]. Walks back linearly,
        and when it reaches the start of a block that cannot be entered by fall-through
        (the previous instruction pair is jr/j/b + delay slot), continues from every branch
        to that block instead."""
        a = before - 4
        while a >= max(self.lo, before - 4 * DEF_SEARCH):
            if is_uncond_end(self.elf.u32(a - 4)):
                # a is the delay slot of an unconditional jump, so a + 4 starts a block that is
                # only entered by branches: follow each of them (delay slot first).
                if depth >= 3:
                    return []
                out = []
                for b in self.branches_to(a + 4):
                    ds = self.elf.u32(b + 4)
                    if dest_reg(ds) == reg:
                        out.append((b + 4, ds, True))
                    else:
                        out += [(x, y, True) for x, y, _ in self.reaching_defs(reg, b, depth + 1)]
                return out
            w = self.elf.u32(a)
            if dest_reg(w) == reg:
                return [(a, w, depth > 0)]
            a -= 4
        return []

    def branches_to(self, target):
        out = []
        for b in range(max(self.lo, target - PRED_SEARCH), target + PRED_SEARCH, 4):
            w = self.elf.u32(b)
            if w is None:
                break
            op = w >> 26
            if op in (4, 5, 6, 7, 20, 21, 22, 23) or (op == 1 and (w >> 16) & 31 in (0, 1, 2, 3)):
                if (b + 4 + (s16(w & 0xFFFF) << 2)) & 0xFFFFFFFF == target:
                    out.append(b)
            elif op == 2 and ((b + 4) & 0xF0000000) | ((w & 0x3FFFFFF) << 2) == target:
                out.append(b)
        return out

    def const(self, reg, before, depth=0):
        """Fold lui / addiu / ori / move chains into a constant (None if not constant)."""
        if reg == 0:
            return 0
        a, w = self.def_of(reg, before)
        if a is None or depth > 6:
            return None
        op, rs = w >> 26, (w >> 21) & 31
        if op == 0x0F:
            return (w & 0xFFFF) << 16
        if op in (9, 0x0D):
            c = self.const(rs, a, depth + 1)
            if c is None:
                return None
            return (c + s16(w & 0xFFFF)) & 0xFFFFFFFF if op == 9 else c | (w & 0xFFFF)
        if op == 0 and w & 63 in (0x21, 0x25) and (w >> 16) & 31 == 0:  # move
            return self.const(rs, a, depth + 1)
        return None


def analyze_site(elf, pc, text_lo, text_hi):
    """Return (dict describing the jump table at jr `pc`, None) or (None, reason)."""
    st = Site(elf, pc, text_lo)
    rx = (elf.u32(pc) >> 21) & 31
    la, lw = st.def_of(rx, pc, SLICE)
    if la is None or lw >> 26 != 0x23:
        return None, "jr target not loaded by lw"
    off, rt = s16(lw & 0xFFFF), (lw >> 21) & 31
    aa, add = st.def_of(rt, la, SLICE)
    if aa is None or add >> 26 != 0 or add & 63 != 0x21:
        return None, "table address not formed by addu"
    found = None
    for base_r, idx_r in (((add >> 21) & 31, (add >> 16) & 31), ((add >> 16) & 31, (add >> 21) & 31)):
        sa, sll = st.def_of(idx_r, aa, SLICE)
        if sa is None or sll >> 26 != 0 or sll & 63 != 0 or (sll >> 6) & 31 != 2:
            continue
        hi = st.const(base_r, aa)
        if hi is not None:
            found = (hi, sa, (sll >> 16) & 31)
            break
    if not found:
        return None, "table base or scaled index not found"
    hi, sa, ri = found
    table = (hi + off + elf.base) & 0xFFFFFFFF  # unrelocated %hi/%lo -> add the load base
    # Index may be biased: ri = rs - lo (addiu ri, rs, -lo), bounded by slt[i]u rc, {ri|rs}, K.
    bias_src, bias, da = ri, 0, None
    idefs = st.reaching_defs(ri, sa)
    if len({w for _, w, _ in idefs}) == 1 and idefs[0][1] >> 26 == 9:  # index = src + c: bias = -c
        da, dw = idefs[0][0], idefs[0][1]
        bias_src, bias = (dw >> 21) & 31, -s16(dw & 0xFFFF)
    copies = {ri, bias_src}
    for r in (ri, bias_src):  # a bound on a copy of the index counts too (or a1, a0, zero)
        ca, cw = st.def_of(r, sa, SLICE)
        if ca is not None and cw >> 26 == 0 and cw & 63 in (0x21, 0x25) and (cw >> 16) & 31 == 0:
            copies.add((cw >> 21) & 31)
    n = default = None
    # The guard is the beq/beql rC, zero right before the index arithmetic.
    for g in range(sa - 4, max(text_lo, sa - 4 * 8), -4):
        gw = elf.u32(g)
        if gw >> 26 in (4, 20) and (gw >> 16) & 31 == 0 and (gw >> 21) & 31 != 0:
            rc = (gw >> 21) & 31
            default = (g + 4 + (s16(gw & 0xFFFF) << 2)) & 0xFFFFFFFF
            for a, w, via_pred in st.reaching_defs(rc, g):
                src = (w >> 21) & 31
                if w >> 26 not in (0x0A, 0x0B):
                    continue
                k = s16(w & 0xFFFF)
                biased_temp = False
                ma, mw = st.def_of(src, a, SLICE)
                if ma is not None and bias and mw >> 26 == 9 and (mw >> 21) & 31 == bias_src                         and -s16(mw & 0xFFFF) == bias:
                    biased_temp = True  # addiu a1, a0, -lo; sltiu a1, a1, n: already biased
                elif src not in copies:
                    if ma is None:
                        continue
                    if mw >> 26 == 0 and mw & 63 in (0x21, 0x25) and (mw >> 16) & 31 == 0                             and (mw >> 21) & 31 in copies:
                        pass  # compares a copy of the index (or a1, a0, zero)
                    elif mw >> 26 == 9 and (mw >> 21) & 31 == bias_src and -s16(mw & 0xFFFF) == bias:
                        biased_temp = True  # addiu a1, a0, -lo; sltiu a1, a1, n: already biased
                    else:
                        continue
                if biased_temp:
                    cnt = k
                    if n is None or cnt == n:
                        n = cnt
                    else:
                        n = -1
                    continue
                # A compare that runs before the biasing addiu sees the unbiased value.
                unbiased = bias and src != ri or (bias and da is not None and (via_pred or a < da or da > g))
                cnt = k - bias if unbiased else k
                if n is None or cnt == n:
                    n = cnt
                else:
                    n = -1  # predecessors disagree
            break
    if not n or n <= 0 or n > 4096:
        return None, "no slt[i]u upper bound on the index"
    raw = elf.read(table, 4 * n)
    if raw is None:
        return None, f"table {table:#x} outside the image"
    targets = [(t + elf.base) & 0xFFFFFFFF for t in struct.unpack(f"<{n}I", raw)]
    bad = [t for t in targets if not (text_lo <= t < text_hi) or t & 3 or abs(t - pc) > MAX_SPAN]
    if bad:
        return None, f"{len(bad)} table entries outside the function's neighbourhood (first {bad[0]:#x})"
    return {"jr": pc, "reg": rx, "index_reg": ri, "bias": bias, "table": table, "count": n,
            "default": default, "targets": targets}, None


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("-")]
    opts = dict((o.lstrip("-").split("=", 1) + [""])[:2] for o in argv[1:] if o.startswith("-"))
    if not args:
        sys.stderr.write(__doc__)
        return 2
    base = int(opts.get("base", "0x08804000"), 16)
    elf = mipsdis.Elf(args[0], base)
    lo, size, _ = elf.secs[".text"]
    hi = lo + size
    found, failed = [], []
    for pc in range(lo, hi, 4):
        w = elf.u32(pc)
        if w >> 26 == 0 and w & 63 == 8 and (w >> 21) & 31 != 31:
            t, why = analyze_site(elf, pc, lo, hi)
            (found.append(t) if t else failed.append((pc, why)))
    cases = sum(t["count"] for t in found)
    print(f"{len(found) + len(failed)} computed jr: {len(found)} jump tables ({cases} cases), "
          f"{len(failed)} other (computed tail calls / unrecognised)")
    for pc, why in failed:
        print(f"  {pc:#010x}: {why}")
    if "v" in opts:
        for t in found:
            print(f"  {t['jr']:#010x}: table {t['table']:#010x} x{t['count']} default {t['default'] or 0:#010x}")
    out = opts.get("toml", os.path.join(ROOT, "research", "kzl_jumptables.toml"))
    with open(out, "w", encoding="ascii", newline="\n") as f:
        f.write("# Switch jump tables in KZL.PRX v1.20 (tools/kzl/jumptab.py). Addresses at base "
                f"{base:#010x}.\n# Each entry: the jr site, its table, and the case targets in index order.\n")
        for t in found:
            f.write(f"\n[[jumptable]]\njr = {t['jr']:#010x}\nreg = {t['reg']}\ntable = {t['table']:#010x}\n"
                    f"count = {t['count']}\n")
            if t["default"] is not None:
                f.write(f"default = {t['default']:#010x}\n")
            f.write("targets = [" + ", ".join(f"{x:#010x}" for x in t["targets"]) + "]\n")
        if failed:
            f.write("\n# computed jr sites that are not jump tables (left to dispatch):\n")
            for pc, why in failed:
                f.write(f"# {pc:#010x}  {why}\n")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
