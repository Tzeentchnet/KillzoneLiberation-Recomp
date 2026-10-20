#!/usr/bin/env python3
"""Generate a CSV of KZL function labels for the headless Ghidra scripts."""

import argparse
import csv
import os
import re
import tomllib


ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)


def read_nid_names(path):
    with open(path, "r", encoding="ascii") as stream:
        text = stream.read()
    return {
        int(nid, 16): name
        for nid, name in re.findall(
            r'\{0x([0-9a-fA-F]{8})u,\s*"([^"]+)"\}', text
        )
    }


def collect_symbols(root):
    imports_path = os.path.join(root, "research", "kzl_imports.toml")
    names_path = os.path.join(
        root, "external", "psp-recomp", "src", "rt", "nid_names.h"
    )
    with open(imports_path, "rb") as stream:
        imports = tomllib.load(stream)["import"]
    names = read_nid_names(names_path)
    symbols = [
        (0x08804000, "module_start", "export"),
        (0x088043D0, "module_stop", "export"),
    ]
    unknown = []
    for entry in imports:
        nid = entry["nid"]
        name = names.get(nid)
        if name is None:
            unknown.append((entry["lib"], nid))
            name = f"{entry['lib']}_{nid:08x}"
        symbols.append((entry["stub"], name, f"import:{entry['lib']}"))
    if unknown:
        details = ", ".join(
            f"{library}:0x{nid:08x}" for library, nid in unknown
        )
        raise ValueError(f"NID names are missing: {details}")
    symbols.sort()
    return symbols


def write_symbols(path, symbols):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="ascii", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("address", "name", "source"))
        for address, name, source in symbols:
            writer.writerow((f"0x{address:08x}", name, source))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=os.path.join(ROOT, "out", "ghidra", "kzl_symbols.csv"),
    )
    args = parser.parse_args(argv)
    try:
        symbols = collect_symbols(ROOT)
        write_symbols(args.output, symbols)
    except (OSError, KeyError, ValueError) as exc:
        parser.exit(1, f"ghidra_symbols: {exc}\n")
    print(f"wrote {args.output}: {len(symbols)} symbols")


if __name__ == "__main__":
    main()
