#!/usr/bin/env python3
"""Generate the recompiled C for KZL.PRX with this project's hints.  -> T-2.8, T-2.13

    gen.py [--out=build/kzl/gen] [--single]

Runs external/psp-recomp/tools/codegen.py on build/kzl/disc/KZL.PRX (run extract.py first)
with the load base from config/kzl.toml, the recovered jump tables and the overrides, and
writes split translation units (kzl_recomp.h, hot/cold kzl_recomp TUs, and
kzl_recomp_register.c). --single writes one kzl_recomp.c instead. Fails if any function
had to become a trapping stub.
"""
import glob
import os
import subprocess
import sys
import tomllib

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def main(argv):
    opts = dict((o[2:].split("=", 1) + [""])[:2] for o in argv[1:] if o.startswith("--"))
    out = opts.get("out") or os.path.join(ROOT, "build", "kzl", "gen")
    with open(os.path.join(ROOT, "config", "kzl.toml"), "rb") as f:
        cfg = tomllib.load(f)
    prx = os.path.join(ROOT, "build", "kzl", "disc", "KZL.PRX")
    if not os.path.exists(prx):
        print("missing", prx, "- run tools/kzl/extract.py <ISO> first")
        return 1
    stubs = os.path.join(out, "stubs.txt")
    if os.path.exists(stubs):
        os.remove(stubs)
    cmd = [sys.executable, os.path.join(ROOT, "external", "psp-recomp", "tools", "codegen.py"), prx,
           os.path.join(out, "kzl_recomp.c"), f"--base={cfg['module']['base']:#x}",
           f"--jumptables={os.path.join(ROOT, 'research', 'kzl_jumptables.toml')}",
           f"--overrides={os.path.join(ROOT, 'config', 'kzl_overrides.toml')}",
           f"--hot-functions={os.path.join(ROOT, 'research', 'kzl_calltargets.txt')}"]
    if "single" not in opts:
        cmd.append("--split")
    os.makedirs(out, exist_ok=True)
    for pattern in (
        "kzl_recomp_[0-9][0-9][0-9].c",
        "kzl_recomp_hot_[0-9][0-9][0-9].c",
        "kzl_recomp_cold_[0-9][0-9][0-9].c",
    ):
        for path in glob.glob(os.path.join(out, pattern)):
            os.remove(path)
    with open(os.path.join(out, "codegen.log"), "w") as log:
        r = subprocess.run(cmd, stderr=log)
    if r.returncode:
        return r.returncode
    if os.path.exists(stubs):
        print(f"ERROR: trapping stubs were emitted, see {stubs}")
        return 1
    # The relocated memory image the runtime loads at the base (code, data, zeroed BSS).
    image = os.path.join(out, "kzl_image.bin")
    r = subprocess.run([sys.executable, os.path.join(ROOT, "external", "psp-recomp", "tools", "prxload.py"),
                        prx, f"{cfg['module']['base']:#x}", f"--out={image}"], capture_output=True, text=True)
    if r.returncode:
        print(r.stdout, r.stderr)
        return r.returncode
    print(f"wrote {image} ({os.path.getsize(image):,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
