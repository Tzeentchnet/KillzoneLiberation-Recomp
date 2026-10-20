#!/usr/bin/env python3
"""Recover evidence-backed KZL function and SN vtable labels."""

import argparse
import base64
import bisect
import csv
import os
import re
import struct
from pathlib import Path


ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
BASE = 0x08804000
DATA_RANGES = (
    (0x08D8FDF0, 0x08DD53FC, "rodata"),
    (0x08DD5400, 0x08E7FA08, "data"),
    (0x08E823E8, 0x08E8B540, "linkonce"),
)
METHOD_PATTERN = re.compile(
    r"([A-Za-z_][A-Za-z0-9_]*::[A-Za-z_~][A-Za-z0-9_]*)"
)


def read_function_inventory(path):
    with open(path, "r", encoding="ascii", newline="") as stream:
        rows = list(csv.DictReader(stream))
    functions = sorted(
        (int(row["address"], 16), int(row["end"], 16), row["name"])
        for row in rows
    )
    return functions


def read_codegen_functions(path):
    with open(path, "r", encoding="ascii") as stream:
        return {
            int(value, 16)
            for value in re.findall(r"void f_([0-9a-f]{8})", stream.read())
        }


def read_string_xrefs(path):
    rows = []
    with open(path, "r", encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream, delimiter="\t"):
            rows.append(
                {
                    "function": int(row["function_address"], 16),
                    "reference": int(row["reference_address"], 16),
                    "text": base64.b64decode(row["value_base64"]).decode(
                        "utf-8", "replace"
                    ),
                }
            )
    return rows


def scan_vtables(image, code_functions):
    tables = {}
    for low, high, section in DATA_RANGES:
        address = (low + 7) & ~7
        while address + 24 <= high:
            cursor = address
            entries = []
            nonzero = 0
            while cursor + 8 <= high:
                delta, function = struct.unpack_from(
                    "<II", image, cursor - BASE
                )
                signed_delta = (
                    delta if delta < 0x80000000 else delta - 0x100000000
                )
                if abs(signed_delta) > 0x10000:
                    break
                if function == 0:
                    if entries:
                        break
                elif function in code_functions:
                    nonzero += 1
                else:
                    break
                entries.append((signed_delta, function))
                cursor += 8
            if nonzero >= 3:
                tables[address] = (section, entries)
                address = cursor
            else:
                address += 8
    return tables


def function_pointer_constants(image, start, end, table_addresses):
    words = [
        struct.unpack_from("<I", image, address - BASE)[0]
        for address in range(start, end + 1, 4)
        if 0 <= address - BASE <= len(image) - 4
    ]
    found = []
    for index, word in enumerate(words):
        if word >> 26 != 15:
            continue
        register = (word >> 16) & 31
        high = (word & 0xFFFF) << 16
        for second in words[index + 1:index + 6]:
            opcode = second >> 26
            if (
                (second >> 21) & 31 == register
                and (second >> 16) & 31 == register
                and opcode in (9, 13)
            ):
                immediate = second & 0xFFFF
                if opcode == 9 and immediate & 0x8000:
                    immediate -= 0x10000
                value = (high + immediate) & 0xFFFFFFFF
                if value in table_addresses:
                    found.append(value)
                break
    return found


def sanitize(name):
    return re.sub(r"[^A-Za-z0-9_]", "_", name.replace("::", "_"))


def recover(image, functions, code_functions, string_xrefs):
    tables = scan_vtables(image, code_functions)
    starts = [function[0] for function in functions]
    symbols = {}

    exact_strings = {
        "Lua 4.0": "lua_strlib_open",
        "value for `lua_getinfo' is not a function": "lua_getinfo",
        "** Havok libs built with version [": "hkWorld_constructor",
        "terminate() called by the exception handling mechanism":
            "sn_runtime_terminate_handler",
        "libc:%s: should be called from main thread\n":
            "sn_libc_main_thread_guard",
        "SceGuSignal": "libgu_signal_event_setup",
    }
    for row in string_xrefs:
        label = exact_strings.get(row["text"])
        match = METHOD_PATTERN.search(row["text"])
        if match:
            label = sanitize(match.group(1))
        if label:
            symbols.setdefault(
                row["function"], (label, "string-evidence")
            )

    markers = sorted(
        {
            (
                row["function"],
                Path(row["text"]).stem,
            )
            for row in string_xrefs
            if row["text"].endswith("TagModule.cpp")
        }
    )
    seen_tables = set()
    recovered_classes = []
    for marker_index, (anchor, class_name) in enumerate(markers):
        end = (
            markers[marker_index + 1][0]
            if marker_index + 1 < len(markers)
            else anchor + 0x1000
        )
        function_index = bisect.bisect_right(starts, anchor)
        candidates = []
        for start, function_end, _ in functions[function_index:]:
            if start >= end:
                break
            for table in function_pointer_constants(
                image, start, function_end, tables
            ):
                if table not in [value for _, value in candidates]:
                    candidates.append((start, table))
        new_candidates = [
            candidate for candidate in candidates
            if candidate[1] not in seen_tables
        ]
        for _, table in candidates:
            seen_tables.add(table)
        if not new_candidates:
            continue
        chosen_index = 1 if marker_index == 0 and len(new_candidates) > 1 else 0
        initializer, table = new_candidates[chosen_index]
        symbols.setdefault(
            anchor,
            (
                f"{class_name}_source_anchor_{anchor:08x}",
                f"class-source:{class_name}",
            ),
        )
        symbols.setdefault(
            initializer,
            (f"{class_name}_vtable_init", f"class-init:{class_name}"),
        )
        symbols[table] = (
            f"vtable_{class_name}",
            f"vtable:{class_name}",
        )
        recovered_classes.append(
            (class_name, anchor, initializer, table, len(tables[table][1]))
        )
    return symbols, tables, recovered_classes


def write_symbols(path, symbols):
    with open(path, "w", encoding="ascii", newline="") as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(("address", "name", "source"))
        for address, (name, source) in sorted(symbols.items()):
            writer.writerow((f"0x{address:08x}", name, source))


def write_report(path, symbols, tables, classes):
    with open(path, "w", encoding="ascii", newline="\n") as stream:
        stream.write("# KZL SN C++ class recovery\n")
        stream.write("vtable_layout={signed_this_delta,u32_function}\n")
        stream.write(f"vtable_candidates={len(tables)}\n")
        stream.write(f"recovered_tag_classes={len(classes)}\n")
        stream.write(f"evidence_backed_symbols={len(symbols)}\n")
        for class_name, anchor, initializer, table, entries in classes:
            stream.write(
                f"class={class_name} source_anchor=0x{anchor:08x} "
                f"vtable_init=0x{initializer:08x} "
                f"vtable=0x{table:08x} entries={entries}\n"
            )
        for address, (name, source) in sorted(symbols.items()):
            if source == "string-evidence":
                stream.write(
                    f"string_function=0x{address:08x} {name}\n"
                )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--functions", required=True)
    parser.add_argument("--string-xrefs", required=True)
    parser.add_argument(
        "--image",
        default=os.path.join(ROOT, "build", "kzl", "gen", "kzl_image.bin"),
    )
    parser.add_argument(
        "--codegen-header",
        default=os.path.join(ROOT, "build", "kzl", "gen", "kzl_recomp.h"),
    )
    parser.add_argument("--symbols", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args(argv)
    try:
        with open(args.image, "rb") as stream:
            image = stream.read()
        functions = read_function_inventory(args.functions)
        code_functions = read_codegen_functions(args.codegen_header)
        xrefs = read_string_xrefs(args.string_xrefs)
        symbols, tables, classes = recover(
            image, functions, code_functions, xrefs
        )
        write_symbols(args.symbols, symbols)
        write_report(args.report, symbols, tables, classes)
    except (OSError, KeyError, ValueError) as exc:
        parser.exit(1, f"class_recovery: {exc}\n")
    print(
        f"recovered {len(classes)} classes, {len(tables)} vtable candidates, "
        f"{len(symbols)} symbols"
    )


if __name__ == "__main__":
    main()
