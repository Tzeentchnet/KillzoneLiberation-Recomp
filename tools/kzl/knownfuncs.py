#!/usr/bin/env python3
"""Match Ghidra-analyzed KZL functions against PPSSPP knownfuncs.ini."""

import argparse
import csv
import os
import re
import sys

try:
    from cityhash import CityHash64
except ImportError:
    CityHash64 = None


ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
BASE = 0x08804000


def read_known_functions(path):
    known = {}
    with open(path, "r", encoding="ascii") as stream:
        for line_number, raw_line in enumerate(stream, 1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            match = re.fullmatch(
                r"([0-9a-fA-F]{16}):(\d+)\s*=\s*(\S+)", line
            )
            if not match:
                raise ValueError(f"{path}:{line_number}: malformed known function")
            digest = int(match.group(1), 16)
            size = int(match.group(2), 10)
            known.setdefault((digest, size), []).append(match.group(3))
    return known


def read_functions(path):
    with open(path, "r", encoding="ascii", newline="") as stream:
        rows = list(csv.DictReader(stream))
    return [
        (int(row["address"], 16), int(row["end"], 16), row["name"])
        for row in rows
    ]


def normalize_instruction(word):
    opcode = word >> 26
    if opcode in (2, 3):
        return word & 0xFC000000
    if (
        opcode == 1
        or 4 <= opcode <= 15
        or 20 <= opcode <= 23
        or 32 <= opcode <= 63
    ):
        return word & 0xFFFF0000
    return word


def match_functions(image, functions, known):
    if CityHash64 is None:
        raise RuntimeError(
            "cityhash is missing; install tools/requirements-analysis.txt"
        )
    matches = []
    for address, end, old_name in functions:
        size = end - address + 1
        offset = address - BASE
        if size <= 0 or size & 3 or offset < 0 or offset + size > len(image):
            continue
        normalized = bytearray(size)
        for position in range(0, size, 4):
            word = int.from_bytes(
                image[offset + position:offset + position + 4], "little"
            )
            normalized[position:position + 4] = normalize_instruction(
                word
            ).to_bytes(4, "little")
        digest = CityHash64(bytes(normalized))
        names = known.get((digest, size))
        if names:
            matches.append((address, size, digest, names, old_name))
    return matches


def write_report(path, matches):
    with open(path, "w", encoding="ascii", newline="\n") as stream:
        stream.write("# KZL matches against PPSSPP knownfuncs.ini\n")
        stream.write(f"matches={len(matches)}\n")
        for address, size, digest, names, old_name in matches:
            stream.write(
                f"0x{address:08x} size={size} hash={digest:016x} "
                f"name={'|'.join(names)} old={old_name}\n"
            )


def write_symbols(path, matches):
    with open(path, "w", encoding="ascii", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("address", "name", "source"))
        for address, _, digest, names, _ in matches:
            writer.writerow((
                f"0x{address:08x}",
                names[0],
                f"knownfunc:{digest:016x}",
            ))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--functions", required=True)
    parser.add_argument(
        "--image",
        default=os.path.join(ROOT, "build", "kzl", "gen", "kzl_image.bin"),
    )
    parser.add_argument("--knownfuncs", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--symbols")
    args = parser.parse_args(argv)
    if CityHash64 is None:
        parser.exit(
            1, "knownfuncs: install tools/requirements-analysis.txt\n"
        )
    try:
        functions = read_functions(args.functions)
        known = read_known_functions(args.knownfuncs)
        with open(args.image, "rb") as stream:
            image = stream.read()
        matches = match_functions(image, functions, known)
        write_report(args.output, matches)
        if args.symbols:
            write_symbols(args.symbols, matches)
    except (OSError, KeyError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"knownfuncs: {exc}\n")
    print(f"known function matches: {len(matches)}; report: {args.output}")


if __name__ == "__main__":
    sys.exit(main())
