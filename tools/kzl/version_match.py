#!/usr/bin/env python3
"""Function-match KZL v1.20 and v1.00 Ghidra exports."""

import argparse
import collections
import csv
import os
import re
import sys

try:
    from cityhash import CityHash64
except ImportError:
    CityHash64 = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from knownfuncs import normalize_instruction  # noqa: E402


BASE = 0x08804000


def read_functions(path):
    with open(path, "r", encoding="ascii", newline="") as stream:
        return [
            {
                "address": int(row["address"], 16),
                "end": int(row["end"], 16),
                "name": row["name"],
            }
            for row in csv.DictReader(stream)
        ]


def build_index(image, functions):
    index = {}
    accepted = 0
    for function in functions:
        address = function["address"]
        size = function["end"] - address + 1
        offset = address - BASE
        if (
            size <= 0
            or size & 3
            or size > 0x10000
            or offset < 0
            or offset + size > len(image)
        ):
            continue
        normalized = bytearray(size)
        for position in range(0, size, 4):
            word = int.from_bytes(
                image[offset + position:offset + position + 4], "little"
            )
            normalized[position:position + 4] = normalize_instruction(
                word
            ).to_bytes(4, "little")
        key = (CityHash64(bytes(normalized)), size)
        index.setdefault(key, []).append(function)
        accepted += 1
    return index, accepted


def unique_matches(new_index, old_index):
    matches = []
    for (digest, size), new_functions in new_index.items():
        old_functions = old_index.get((digest, size), [])
        if len(new_functions) == 1 and len(old_functions) == 1:
            matches.append(
                {
                    "new": new_functions[0],
                    "old": old_functions[0],
                    "hash": digest,
                    "size": size,
                }
            )
    return sorted(matches, key=lambda match: match["new"]["address"])


def read_symbols(paths):
    symbols = {}
    for path in paths:
        with open(path, "r", encoding="ascii", newline="") as stream:
            for row in csv.DictReader(stream):
                if row["source"].startswith("vtable:"):
                    continue
                symbols[int(row["address"], 16)] = (
                    row["name"], row["source"]
                )
    return symbols


def write_symbols(path, matches, symbols):
    rows = []
    for match in matches:
        label = symbols.get(match["new"]["address"])
        if label:
            rows.append((match["old"]["address"], label[0], label[1]))
    with open(path, "w", encoding="ascii", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("address", "name", "source"))
        for address, name, source in sorted(rows):
            writer.writerow((
                f"0x{address:08x}", name, f"v1.20:{source}"
            ))
    return len(rows)


def write_report(
    path, matches, new_count, old_count, new_size, old_size, carried, symbols,
    new_module, old_module,
):
    deltas = collections.Counter(
        match["old"]["address"] - match["new"]["address"]
        for match in matches
    )
    same_address = sum(
        match["old"]["address"] == match["new"]["address"]
        for match in matches
    )
    matched_bytes = sum(match["size"] for match in matches)
    with open(path, "w", encoding="ascii", newline="\n") as stream:
        stream.write("# KZL v1.20 -> v1.00 normalized function match\n")
        stream.write(f"v120_relocated_image_bytes={new_size}\n")
        stream.write(f"v100_relocated_image_bytes={old_size}\n")
        stream.write(f"relocated_image_growth={new_size - old_size}\n")
        stream.write(f"v120_prx_bytes={len(new_module)}\n")
        stream.write(f"v100_prx_bytes={len(old_module)}\n")
        stream.write(f"prx_growth={len(new_module) - len(old_module)}\n")
        stream.write(f"v120_ghidra_functions={new_count}\n")
        stream.write(f"v100_ghidra_functions={old_count}\n")
        stream.write(f"unique_function_matches={len(matches)}\n")
        stream.write(f"matched_normalized_bytes={matched_bytes}\n")
        stream.write(f"same_address_matches={same_address}\n")
        stream.write(f"carried_labels={carried}\n")
        new_strings = {
            match.group().decode("latin1")
            for match in re.finditer(rb"[ -~]{8,}", new_module)
        }
        old_strings = {
            match.group().decode("latin1")
            for match in re.finditer(rb"[ -~]{8,}", old_module)
        }
        added_strings = new_strings - old_strings
        removed_strings = old_strings - new_strings
        stream.write(f"v120_ascii_strings={len(new_strings)}\n")
        stream.write(f"v100_ascii_strings={len(old_strings)}\n")
        stream.write(f"added_ascii_strings={len(added_strings)}\n")
        stream.write(f"removed_ascii_strings={len(removed_strings)}\n")
        markers = (
            "CHAPTER5.BIN",
            "HasChapter5",
            "SetHasChapter5",
            "StartBrowserDownloadPatch",
            "CalculateGameCompletionChapter5",
            "ReleaseVersion 3.01.200703171900",
            "dme version: 3.1.2",
            "medius client version: 3.1.1",
        )
        stream.write("v120_feature_markers=\n")
        for marker in markers:
            if marker in added_strings:
                stream.write(f"  {marker}\n")
        stream.write("top_address_deltas=\n")
        for delta, count in deltas.most_common(20):
            stream.write(f"  {delta:+d} ({delta:+#x}) count={count}\n")
        stream.write("labeled_matches=\n")
        for match in matches:
            label = symbols.get(match["new"]["address"])
            if label:
                stream.write(
                    f"  v120=0x{match['new']['address']:08x} "
                    f"v100=0x{match['old']['address']:08x} "
                    f"size={match['size']} name={label[0]}\n"
                )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v120-functions", required=True)
    parser.add_argument("--v100-functions", required=True)
    parser.add_argument("--v120-image", required=True)
    parser.add_argument("--v100-image", required=True)
    parser.add_argument("--v120-module", required=True)
    parser.add_argument("--v100-module", required=True)
    parser.add_argument("--symbols", action="append", default=[])
    parser.add_argument("--output-symbols", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args(argv)
    if CityHash64 is None:
        parser.exit(
            1, "version_match: install tools/requirements-analysis.txt\n"
        )
    try:
        new_functions = read_functions(args.v120_functions)
        old_functions = read_functions(args.v100_functions)
        with open(args.v120_image, "rb") as stream:
            new_image = stream.read()
        with open(args.v100_image, "rb") as stream:
            old_image = stream.read()
        with open(args.v120_module, "rb") as stream:
            new_module = stream.read()
        with open(args.v100_module, "rb") as stream:
            old_module = stream.read()
        new_index, new_count = build_index(new_image, new_functions)
        old_index, old_count = build_index(old_image, old_functions)
        matches = unique_matches(new_index, old_index)
        symbols = read_symbols(args.symbols)
        carried = write_symbols(args.output_symbols, matches, symbols)
        write_report(
            args.report, matches, new_count, old_count,
            len(new_image), len(old_image), carried, symbols,
            new_module, old_module,
        )
    except (OSError, KeyError, ValueError) as exc:
        parser.exit(1, f"version_match: {exc}\n")
    print(
        f"matched {len(matches)} unique functions; "
        f"carried {carried} labels; report: {args.report}"
    )


if __name__ == "__main__":
    main()
