#!/usr/bin/env python3
"""Summarise the HLE calls in a PPSSPP log and flag the ones the sal063 runtime lacks.  -> T-0.5, F-047

    hlesummary.py <ppsspp log> [--out=research/ppsspp_boot_hle_60s.txt] [--title=TEXT]

Works on logs from the desktop build (--log=FILE -d) and from PPSSPPHeadless (-l). Function
names are mapped to NIDs with research/nid_names.tsv; a NID counts as handled when some
src/rt file in external/psp-recomp calls sr_hle_register() with it.
"""
import collections
import glob
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nidnames  # noqa: E402

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
CALL = re.compile(r"(?:^|[\s=])((?:sce|Sce)[A-Za-z0-9_]+)\(")


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    opts = dict((o[2:].split("=", 1) + [""])[:2] for o in argv[1:] if o.startswith("--"))
    if len(args) != 1:
        sys.stderr.write(__doc__)
        return 2
    names = nidnames.load()
    byname = {v: k for k, v in names.items()}
    impl = set()
    for p in glob.glob(os.path.join(ROOT, "external", "psp-recomp", "src", "rt", "**", "*.c"), recursive=True):
        with open(p, encoding="utf-8", errors="replace") as f:
            impl |= {int(n, 16) for n in re.findall(r"sr_hle_register\(\s*0x([0-9a-fA-F]{1,8})", f.read())}
    counts = collections.Counter()
    with open(args[0], encoding="utf-8", errors="replace") as f:
        for line in f:
            # Count each logged HLE call once per line: the function the log line reports on.
            if "HLE\\" not in line and not line.startswith(("D ", "I ", "W ", "E ", "N ", "V ")):
                continue
            m = CALL.search(line)
            if m and m.group(1) in byname:
                counts[m.group(1)] += 1
    rows = [(c, fn, byname[fn], byname[fn] in impl) for fn, c in counts.most_common()]
    missing = [r for r in rows if not r[3]]
    title = opts.get("title") or f"HLE calls in {os.path.basename(args[0])}"
    out = [f"# {title}", "# count  function                             NID       sal063",
           f"# {len(rows)} functions, {len(missing)} without a sal063 handler (MISSING).", ""]
    out += [f"{c:7d}  {fn:<36} {nid:08x}  {'ok' if ok else 'MISSING'}" for c, fn, nid, ok in rows]
    text = "\n".join(out) + "\n"
    if "out" in opts:
        with open(opts["out"], "w", encoding="ascii", newline="\n") as f:
            f.write(text)
        print(f"wrote {opts['out']}: {len(rows)} functions, {len(missing)} missing")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
