import struct, sys, os, glob

def sfo(path):
    d = open(path, 'rb').read()
    magic, ver, kt, dt, n = struct.unpack_from('<4sIIII', d, 0)
    res = {}
    for i in range(n):
        ko, fmt, ln, mx, do = struct.unpack_from('<HHIII', d, 20 + i * 16)
        k = d[kt + ko:d.index(b'\0', kt + ko)].decode()
        raw = d[dt + do:dt + do + ln]
        res[k] = struct.unpack('<I', raw)[0] if fmt == 0x0404 else raw.rstrip(b'\0').decode('utf-8', 'replace')
    return res

def psp_hdr(d):
    # ~PSP header: magic, attr, comp_attr, modver_lo, modver_hi, modname[28]
    attr, comp = struct.unpack_from('<HH', d, 4)
    name = d[10:38].split(b'\0')[0].decode('ascii', 'replace')
    elf_size, psp_size = struct.unpack_from('<II', d, 0x28)
    tag = struct.unpack_from('<I', d, 0xD0)[0]
    return f'~PSP attr={attr:#x} comp={comp:#x} mod="{name}" elf_size={elf_size} psp_size={psp_size} tag={tag:#010x}'

def elf_hdr(d):
    e_type, e_mach = struct.unpack_from('<HH', d, 16)
    e_entry, e_phoff, e_shoff, e_flags = struct.unpack_from('<IIII', d, 24)
    phnum = struct.unpack_from('<H', d, 44)[0]
    shnum = struct.unpack_from('<H', d, 48)[0]
    return f'ELF type={e_type:#x} mach={e_mach} entry={e_entry:#x} flags={e_flags:#x} phnum={phnum} shnum={shnum}'

def strings_hits(d, needles):
    return {n: d.count(n.encode()) for n in needles}

base = sys.argv[1]
for p in sorted(glob.glob(os.path.join(base, '*'))):
    d = open(p, 'rb').read()
    nm = os.path.basename(p)
    if nm.endswith('PARAM.SFO'):
        print(nm, sfo(p)); continue
    m = d[:4]
    if m == b'~PSP': info = psp_hdr(d)
    elif m == b'\x7fELF': info = elf_hdr(d)
    else: info = 'magic=' + d[:16].hex()
    print(f'{nm}: size={len(d)} {info}')

for extra in sys.argv[2:]:
    with open(extra, 'rb') as f:
        h = f.read(256)
    print(os.path.basename(extra), h[:64].hex(), h[:64])
