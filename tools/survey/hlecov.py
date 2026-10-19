"""Cross-reference a game's import NIDs against the reference runtime's NID names and HLE handlers."""
import re, sys, collections

imports_toml, nid_names_h, hle_dir = sys.argv[1:4]
imps = re.findall(r'lib = "([^"]+)"\s*\nnid = 0x([0-9a-fA-F]+)', open(imports_toml).read())
names = {int(n, 16): s for n, s in re.findall(r'\{0x([0-9a-f]+)u, "([^"]+)"\}', open(nid_names_h).read())}
impl = set()
import glob
for p in glob.glob(hle_dir + '/**/*.c', recursive=True):
    for n in re.findall(r'sr_hle_register\(\s*0x([0-9a-fA-F]{1,8})', open(p, encoding='utf-8', errors='replace').read()):
        impl.add(int(n, 16))

per = collections.OrderedDict()
for lib, nid in imps:
    per.setdefault(lib, []).append(int(nid, 16))
tot = tot_impl = 0
missing_all = []
for lib, nids in per.items():
    have = [n for n in nids if n in impl]
    miss = [n for n in nids if n not in impl]
    tot += len(nids); tot_impl += len(have)
    print(f'{lib:<22} {len(have):3d}/{len(nids):<3d} implemented')
    for n in miss:
        missing_all.append((lib, n, names.get(n, '?')))
print(f'TOTAL {tot_impl}/{tot} implemented')
print('--- missing')
for lib, n, nm in missing_all:
    print(f'{lib:<22} 0x{n:08x} {nm}')
