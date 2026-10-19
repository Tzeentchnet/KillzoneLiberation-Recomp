"""Static survey of a plaintext PSP PRX/ELF: sections, module info, imports, exports, opcode mix."""
import struct, sys, collections, re

d = open(sys.argv[1], 'rb').read()
e_shoff = struct.unpack_from('<I', d, 32)[0]
e_phoff = struct.unpack_from('<I', d, 28)[0]
phnum, = struct.unpack_from('<H', d, 44)
shentsize, shnum, shstrndx = struct.unpack_from('<HHH', d, 46)

secs = []
for i in range(shnum):
    s = struct.unpack_from('<IIIIIIIIII', d, e_shoff + i * 40)
    secs.append(dict(name=s[0], type=s[1], flags=s[2], addr=s[3], off=s[4], size=s[5], link=s[6], info=s[7], align=s[8], entsize=s[9]))
strtab = secs[shstrndx]
def cstr(buf, off):
    return buf[off:buf.index(b'\0', off)].decode('ascii', 'replace')
for s in secs:
    s['nm'] = cstr(d, strtab['off'] + s['name'])

print('== Program headers')
for i in range(phnum):
    p = struct.unpack_from('<IIIIIIII', d, e_phoff + i * 32)
    print(f'  type={p[0]:#x} off={p[1]:#x} vaddr={p[2]:#x} paddr={p[3]:#x} filesz={p[4]:#x} memsz={p[5]:#x} flags={p[6]:#x}')

print('== Sections')
for i, s in enumerate(secs):
    print(f'  [{i:2d}] {s["nm"]:<28} type={s["type"]:#010x} addr={s["addr"]:#010x} size={s["size"]:#9x} flags={s["flags"]:#x}')

byname = {s['nm']: s for s in secs}
def vread(addr, n):
    for s in secs:
        if s['type'] != 8 and s['addr'] <= addr < s['addr'] + s['size'] and s['flags'] & 2:
            o = s['off'] + addr - s['addr']
            return d[o:o + n]
    return None
def vstr(addr):
    b = vread(addr, 256)
    return b.split(b'\0')[0].decode('ascii', 'replace') if b else '?'

mi = byname.get('.rodata.sceModuleInfo')
if mi:
    attr, ver, = struct.unpack_from('<HH', d, mi['off'])
    name = d[mi['off'] + 4:mi['off'] + 32].split(b'\0')[0].decode()
    gp, ent_s, ent_e, stub_s, stub_e = struct.unpack_from('<IIIII', d, mi['off'] + 32)
    print(f'== ModuleInfo name="{name}" attr={attr:#x} ver={ver:#x} gp={gp:#x} exports={ent_s:#x}-{ent_e:#x} imports={stub_s:#x}-{stub_e:#x}')
    print('== Imports')
    a = stub_s
    total = 0
    while a < stub_e:
        ent = vread(a, 20)
        lname, ver, attr, ln, nvar, nfunc, nids, funcs = struct.unpack_from('<IHHBBHII', ent)
        print(f'  {vstr(lname):<28} funcs={nfunc:3d} vars={nvar}')
        total += nfunc
        a += ln * 4
    print('  total imported funcs:', total)
    print('== Exports')
    a = ent_s
    while a < ent_e:
        ent = vread(a, 16)
        lname, ver, attr, ln, nvar, nfunc = struct.unpack_from('<IHHBBH', ent)
        print(f'  {(vstr(lname) if lname else "<syslib>"):<28} funcs={nfunc} vars={nvar}')
        a += ln * 4

# Opcode survey over executable sections
cnt = collections.Counter()
ninsn = 0
for s in secs:
    if s['flags'] & 4 and s['type'] == 1:
        for (w,) in struct.iter_unpack('<I', d[s['off']:s['off'] + s['size'] & ~3]):
            ninsn += 1
            op = w >> 26
            if op == 0x11: cnt['FPU (COP1)'] += 1
            elif op == 0x12: cnt['VFPU COP2 (mfv/mtv/bvf)'] += 1
            elif op in (0x18, 0x19, 0x1B, 0x3C, 0x3D, 0x3F, 0x34, 0x37): cnt['VFPU ALU (vadd/vmul/vmmul/vfim/...)'] += 1
            elif op in (0x32, 0x36, 0x3A, 0x3E, 0x35): cnt['VFPU load/store (lv/sv)'] += 1
            elif op == 0x03: cnt['jal'] += 1
            elif op == 0x00 and (w & 0x3F) == 0x09: cnt['jalr'] += 1
            elif op == 0x00 and (w & 0x3F) == 0x08: cnt['jr'] += 1
            elif op == 0x00 and (w & 0x3F) == 0x0C: cnt['syscall'] += 1
print(f'== Code: {ninsn} instructions ({ninsn*4/1024/1024:.2f} MiB)')
for k, v in cnt.most_common():
    print(f'  {k:<40} {v:8d}  ({100*v/ninsn:.2f}%)')

# Interesting strings
blob = d
pats = [rb'[A-Za-z]:\\[\x20-\x7e]{4,120}', rb'[\x20-\x7e]{0,60}\.(?:cpp|c|h|hpp|inl)\b', rb'(?i)(?:snc|prodg|sn systems|gcc|psp-gcc|libgu|sceGu)[\x20-\x7e]{0,60}',
        rb'(?i)lua[\x20-\x7e]{0,40}', rb'(?i)(?:assert|error)[\x20-\x7e]{6,80}']
for p in pats:
    hits = collections.OrderedDict.fromkeys(m.group(0) for m in re.finditer(p, blob))
    hits = list(hits)
    print(f'== Strings /{p.decode(errors="replace")[:40]}/ : {len(hits)} unique')
    for h in hits[:25]:
        print('   ', h.decode('ascii', 'replace'))
