"""Minimal read-only ISO9660 reader for PSP UMD images.

Only what the KZL tools need: walk the directory tree from the primary volume descriptor,
look up a file by path, and read byte ranges of a file without extracting it.
"""
import hashlib
import struct

SECTOR = 2048


class IsoFile:
    __slots__ = ("path", "lba", "size", "is_dir")

    def __init__(self, path, lba, size, is_dir):
        self.path, self.lba, self.size, self.is_dir = path, lba, size, is_dir

    @property
    def offset(self):
        return self.lba * SECTOR


class Iso:
    def __init__(self, path):
        self.path = path
        self.f = open(path, "rb")
        self.f.seek(16 * SECTOR)
        pvd = self.f.read(SECTOR)
        if pvd[1:6] != b"CD001":
            raise ValueError(f"{path}: no ISO9660 primary volume descriptor")
        self.volume_id = pvd[40:72].decode("ascii", "replace").strip()
        root = pvd[156:156 + 34]
        self.entries = {}
        self._walk(struct.unpack_from("<I", root, 2)[0], struct.unpack_from("<I", root, 10)[0], "")

    def _walk(self, lba, size, prefix):
        self.f.seek(lba * SECTOR)
        data = self.f.read(size)
        i = 0
        while i < len(data):
            ln = data[i]
            if ln == 0:  # records never straddle a sector; skip the padding
                i = (i // SECTOR + 1) * SECTOR
                continue
            rec = data[i:i + ln]
            i += ln
            name = rec[33:33 + rec[32]]
            if name in (b"\x00", b"\x01"):
                continue
            name = name.decode("ascii", "replace").split(";")[0]
            elba, esize, is_dir = struct.unpack_from("<I", rec, 2)[0], struct.unpack_from("<I", rec, 10)[0], bool(rec[25] & 2)
            full = f"{prefix}/{name}"
            self.entries[full.upper()] = IsoFile(full, elba, esize, is_dir)
            if is_dir:
                self._walk(elba, esize, full)

    def files(self):
        return [e for e in self.entries.values() if not e.is_dir]

    def lookup(self, path):
        e = self.entries.get(("/" + path.strip("/")).upper())
        if e is None:
            raise FileNotFoundError(f"{path} not found in {self.path}")
        return e

    def read(self, path_or_entry, offset=0, size=None):
        e = path_or_entry if isinstance(path_or_entry, IsoFile) else self.lookup(path_or_entry)
        if size is None:
            size = e.size - offset
        size = max(0, min(size, e.size - offset))
        self.f.seek(e.offset + offset)
        return self.f.read(size)

    def close(self):
        self.f.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def sha1_file(path, chunk=1 << 22):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                return h.hexdigest()
            h.update(b)
