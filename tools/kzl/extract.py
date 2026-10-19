#!/usr/bin/env python3
"""Verify the user's Killzone: Liberation ISO and pull out the files the build needs.  -> T-1.1

    extract.py <ISO> [--out=build/kzl/disc] [--config=config/kzl.toml] [--no-verify]

Checks the ISO size and SHA-1 against config/kzl.toml (F-001), then writes every file listed
under [disc.files] to --out, flattened to its base name, and checks each file's SHA-1. Also
writes the PSP.DAT TOC (header, name pool and records) as PSP.DAT.toc for tools that need it
without the 522 MB archive. Nothing here is committed: build/ is ignored.
"""
import hashlib
import os
import struct
import sys
import tomllib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from iso9660 import Iso, sha1_file  # noqa: E402

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    opts = dict((o[2:].split("=", 1) + [""])[:2] for o in argv[1:] if o.startswith("--"))
    if len(args) != 1:
        sys.stderr.write(__doc__)
        return 2
    iso_path = args[0]
    out = opts.get("out") or os.path.join(ROOT, "build", "kzl", "disc")
    with open(opts.get("config") or os.path.join(ROOT, "config", "kzl.toml"), "rb") as f:
        cfg = tomllib.load(f)
    verify = "no-verify" not in opts
    failures = []

    size = os.path.getsize(iso_path)
    if verify:
        if size != cfg["disc"]["iso_size"]:
            failures.append(f"ISO size {size} != expected {cfg['disc']['iso_size']}")
        else:
            print(f"hashing {iso_path} ({size:,} bytes)...")
            got = sha1_file(iso_path)
            if got != cfg["disc"]["iso_sha1"]:
                failures.append(f"ISO SHA-1 {got} != expected {cfg['disc']['iso_sha1']}")
            else:
                print(f"ISO SHA-1 ok ({got})")
        if failures:
            for m in failures:
                print("ERROR:", m)
            print("This build only supports UCUS-98646 v1.20 (see FINDINGS F-001). Use --no-verify to override.")
            return 1

    os.makedirs(out, exist_ok=True)
    with Iso(iso_path) as iso:
        for path, want in cfg["disc"]["files"].items():
            data = iso.read(path)
            got = hashlib.sha1(data).hexdigest()
            dst = os.path.join(out, os.path.basename(path))
            with open(dst, "wb") as f:
                f.write(data)
            status = "ok" if got == want else f"MISMATCH (expected {want})"
            if got != want:
                failures.append(f"{path}: {got}")
            print(f"  {os.path.basename(path):<16} {len(data):>10,}  {got}  {status}")
        # PSP.DAT TOC: 0x18-byte header + toc_len bytes (see pspdat.py).
        dat = iso.lookup(cfg["pspdat"]["path"])
        toc_len = struct.unpack("<I", iso.read(dat, 0, 4))[0]
        with open(os.path.join(out, "PSP.DAT.toc"), "wb") as f:
            f.write(iso.read(dat, 0, 0x18 + toc_len))
        print(f"  {'PSP.DAT.toc':<16} {0x18 + toc_len:>10,}")
    print(f"wrote {out}")
    if failures and verify:
        for m in failures:
            print("ERROR:", m)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
