#!/usr/bin/env python3
"""List (and optionally extract) Guerrilla's PSP.DAT archive from Killzone: Liberation.  -> T-1.7, F-020

Layout (reverse-engineered from UCUS-98646 v1.20, all little-endian u32):

    0x00  toc_len         TOC bytes after the first 0x18 (TOC ends at 0x18 + toc_len)
    0x04  file_count      file records, duplicates included (3987 on v1.20)
    0x08  exporter metadata (0xFA3E01 on v1.20; ignored by the game)
    0x0C  exporter metadata (0xFA3DB6 on v1.20; ignored by the game)
    0x10  0, 0
    0x18  pool_size       bytes of the name pool that follows
    0x1C  name pool       NUL-terminated names, shared between entries
    pool_end + 0          root: {end, child_count}           (no name word)
    pool_end + 8          records: {name_off | 0x80000000 if dir, a, b}

Record pointers are byte offsets from pool_end + 4, so pointer p names record (p - 4) / 12.
The root's first field points one past the last record. For a file record, a is the byte
offset in PSP.DAT and b is the size. For a directory, a points at its first child and b is
the child count. Children of one directory are contiguous, and the tree is stored
depth-first. The first file starts at 0x15000, right after the sector-padded TOC.

The same path can appear several times with identical size at different offsets (for
example /scripts/menu/unlockableabilities.lua x4): copies placed near the data that uses
them to cut UMD seeks. The game picks the extent nearest the underlying archive cursor;
the first extent in TOC order wins a distance tie.

Usage:
    pspdat.py <ISO or PSP.DAT> [--tree] [--csv=out.csv] [--extract=DIR [--match=SUBSTR]]
"""
import csv
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from iso9660 import Iso  # noqa: E402

DAT_PATH_IN_ISO = "PSP_GAME/USRDIR/PSP.DAT"
DIR_FLAG = 0x80000000
REC = 12


class Source:
    """Random access to PSP.DAT, either a loose file or inside the ISO."""

    def __init__(self, path):
        with open(path, "rb") as f:
            magic = f.read(0x8006)[0x8001:0x8006]
        if magic == b"CD001":
            self.iso = Iso(path)
            self.entry = self.iso.lookup(DAT_PATH_IN_ISO)
            self.size = self.entry.size
            self.read = lambda off, n: self.iso.read(self.entry, off, n)
        else:
            self.f = open(path, "rb")
            self.size = os.path.getsize(path)
            self.read = self._read_file

    def _read_file(self, off, n):
        self.f.seek(off)
        return self.f.read(n)


class Entry:
    __slots__ = ("index", "name", "is_dir", "a", "b", "path", "children")

    def __init__(self, index, name, is_dir, a, b):
        self.index, self.name, self.is_dir, self.a, self.b = index, name, is_dir, a, b
        self.path, self.children = None, []

    @property
    def offset(self):
        return self.a

    @property
    def size(self):
        return self.b


def nearest_copy(entries, cursor):
    """Match KZL's duplicate selector for one path's ordered candidate range."""
    if not 0 <= cursor < 1 << 64:
        raise ValueError("cursor must be an unsigned 64-bit value")
    if not entries:
        raise ValueError("at least one archive entry is required")
    return min(entries, key=lambda entry: abs(entry.offset - cursor))


class PspDat:
    def __init__(self, src):
        self.src = src
        hdr = src.read(0, 0x1C)
        self.toc_len, self.file_count, self.unk8, self.unkC, _, _, pool_size = struct.unpack("<7I", hdr)
        self.toc_end = 0x18 + self.toc_len
        toc = src.read(0, self.toc_end)
        self.pool = toc[0x1C:0x1C + pool_size]
        pool_end = 0x1C + pool_size
        root_end, root_b = struct.unpack_from("<2I", toc, pool_end)
        self.root = Entry(-1, "", True, 0, root_b)
        self.rec_base = pool_end + 8
        nrec = (root_end - 4) // REC
        self.problems = []
        if self.rec_base + nrec * REC != self.toc_end:
            self.problems.append(f"record table ends at {self.rec_base + nrec * REC:#x}, header says {self.toc_end:#x}")
        self.entries = []
        for i in range(nrec):
            c, a, b = struct.unpack_from("<3I", toc, self.rec_base + i * REC)
            self.entries.append(Entry(i, self._name(c & ~DIR_FLAG), bool(c & DIR_FLAG), a, b))
        nfiles = sum(1 for e in self.entries if not e.is_dir)
        if nfiles != self.file_count:
            self.problems.append(f"{nfiles} file records, header says {self.file_count}")
        self._link()

    def _name(self, off):
        if off >= len(self.pool):
            return f"<bad name {off:#x}>"
        return self.pool[off:self.pool.index(b"\0", off)].decode("ascii", "replace")

    def _link(self):
        # The root's children start at record 0.
        seen = [0] * len(self.entries)
        stack = [(self.root, 0, "")]
        while stack:
            parent, first, prefix = stack.pop()
            for k in range(parent.b):
                i = first + k
                if not 0 <= i < len(self.entries):
                    self.problems.append(f"{prefix or '/'}: child index {i} out of range")
                    break
                e = self.entries[i]
                seen[i] += 1
                e.path = f"{prefix}/{e.name}"
                parent.children.append(e)
                if e.is_dir:
                    if (e.a - 4) % REC:
                        self.problems.append(f"{e.path}: child pointer {e.a:#x} not on a record boundary")
                        continue
                    stack.append((e, (e.a - 4) // REC, e.path))
                elif e.a + e.b > self.src.size:
                    self.problems.append(f"{e.path}: extent {e.a:#x}+{e.b:#x} past end of archive")
        for i, n in enumerate(seen):
            if n != 1:
                self.problems.append(f"record {i} ({self.entries[i].name}) reached {n} times")

    def files(self):
        return [e for e in self.entries if not e.is_dir and e.path]

    def copies(self, path):
        return [e for e in self.files() if e.path == path]

    def select_copy(self, path, cursor=0):
        copies = self.copies(path)
        if not copies:
            raise KeyError(path)
        return nearest_copy(copies, cursor)


def print_tree(e, depth=0):
    for c in e.children:
        if c.is_dir:
            print(f"{'  ' * depth}{c.name}/  ({c.b} entries)")
            print_tree(c, depth + 1)
        else:
            print(f"{'  ' * depth}{c.name}  {c.b} @ {c.a:#x}")


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    opts = dict((o[2:].split("=", 1) + [""])[:2] for o in argv[1:] if o.startswith("--"))
    if not args:
        sys.stderr.write(__doc__)
        return 2
    dat = PspDat(Source(args[0]))
    files = dat.files()
    dirs = [e for e in dat.entries if e.is_dir]
    total = sum(e.b for e in files)
    uniq = {e.path: e.b for e in files}
    print(f"PSP.DAT: {dat.src.size:,} bytes, TOC ends {dat.toc_end:#x}, {len(dat.entries)} records = "
          f"{len(dirs)} dirs + {len(files)} files ({len(uniq)} unique paths)")
    print(f"file data {total:,} bytes ({sum(uniq.values()):,} without duplicate copies); "
          f"header unk8={dat.unk8:#x} unkC={dat.unkC:#x}")
    for p in dat.problems[:50]:
        print("PROBLEM:", p)
    if not dat.problems:
        print("tree check: every record reached exactly once, all extents inside the archive")
    if "tree" in opts:
        print_tree(dat.root)
    if "csv" in opts:
        with open(opts["csv"], "w", newline="") as f:
            wr = csv.writer(f)
            wr.writerow(["path", "offset", "size"])
            for e in sorted(files, key=lambda e: e.a):
                wr.writerow([e.path, f"{e.a:#x}", e.b])
        print("wrote", opts["csv"])
    if "extract" in opts:
        out, match = opts["extract"], opts.get("match", "")
        n = 0
        for e in files:
            if match and match.lower() not in e.path.lower():
                continue
            dst = os.path.join(out, *e.path.strip("/").split("/"))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "wb") as f:
                f.write(dat.src.read(e.a, e.b))
            n += 1
        print(f"extracted {n} files to {out}")
    return 1 if dat.problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
