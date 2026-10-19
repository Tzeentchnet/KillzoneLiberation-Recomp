import struct, sys, os

SECTOR = 2048

def read_dir(f, lba, size, path, out):
    f.seek(lba * SECTOR)
    data = f.read(size)
    i = 0
    while i < len(data):
        ln = data[i]
        if ln == 0:
            i = ((i // SECTOR) + 1) * SECTOR
            continue
        rec = data[i:i + ln]
        elba = struct.unpack_from('<I', rec, 2)[0]
        esize = struct.unpack_from('<I', rec, 10)[0]
        flags = rec[25]
        nlen = rec[32]
        name = rec[33:33 + nlen]
        i += ln
        if name in (b'\x00', b'\x01'):
            continue
        name = name.decode('ascii', 'replace').split(';')[0]
        full = path + '/' + name
        if flags & 2:
            out.append((full + '/', elba, esize, True))
            read_dir(f, elba, esize, full, out)
        else:
            out.append((full, elba, esize, False))

def main(iso, dump_dir=None, wanted=()):
    with open(iso, 'rb') as f:
        f.seek(16 * SECTOR)
        pvd = f.read(SECTOR)
        print('VolumeID:', pvd[40:72].decode().strip(), 'SystemID:', pvd[8:40].decode().strip())
        root = pvd[156:156 + 34]
        rlba = struct.unpack_from('<I', root, 2)[0]
        rsize = struct.unpack_from('<I', root, 10)[0]
        out = []
        read_dir(f, rlba, rsize, '', out)
        for p, lba, sz, d in out:
            print(f'{"D" if d else "F"} {lba:8d} {sz:12d} {p}')
        if dump_dir:
            os.makedirs(dump_dir, exist_ok=True)
            for p, lba, sz, d in out:
                if not d and any(p.upper().endswith(w) for w in wanted):
                    f.seek(lba * SECTOR)
                    dst = os.path.join(dump_dir, p.strip('/').replace('/', '_'))
                    with open(dst, 'wb') as o:
                        o.write(f.read(sz))
                    print('dumped', dst)

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None, tuple(sys.argv[3:]))
