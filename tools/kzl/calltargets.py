#!/usr/bin/env python3
"""Audit PPSSPP-executed jal/jalr targets against KZL's function inventory. -> T-2.7

    calltargets.py <call-trace> [--prx=build/kzl/disc/KZL.PRX] [--base=08804000]
                   [--overrides=config/kzl_overrides.toml]
                   [--report=research/kzl_calltargets.txt]

The input is produced by ppsspp_calls.py and the PSPRECOMP_CALLTRACE hook. The command exits
nonzero when an executed target inside a KZL executable section is absent from analyze.py's
function inventory.
"""

import hashlib
import os
import re
import sys


ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
ANALYZE_DIR = os.path.join(ROOT, "external", "psp-recomp", "tools")
HEADER = "# psp-recomp call trace v1 "
EDGE_RE = re.compile(r"0x([0-9a-fA-F]{8}) (jal|jalr) 0x([0-9a-fA-F]{8})\Z")


class TraceFormatError(ValueError):
    pass


def parse_call_trace(path):
    edges = set()
    found_header = False
    with open(path, "r", encoding="ascii", newline="\n") as stream:
        for lineno, raw in enumerate(stream, start=1):
            line = raw.rstrip("\n")
            if not line:
                continue
            if line.startswith("#"):
                if line.startswith(HEADER):
                    found_header = True
                continue
            match = EDGE_RE.fullmatch(line)
            if not match:
                raise TraceFormatError(f"{path}:{lineno}: malformed call edge: {line!r}")
            source, kind, target = match.groups()
            edges.add((int(source, 16), kind, int(target, 16)))
    if not found_header:
        raise TraceFormatError(f"{path}: missing '{HEADER.strip()}' header")
    return edges


def in_ranges(addr, ranges):
    return any(lo <= addr < hi for lo, hi in ranges)


def audit_targets(edges, known, ranges, nonfunctions=None):
    nonfunctions = set(nonfunctions or ())
    in_module = {}
    external = {}
    for source, kind, target in edges:
        group = in_module if in_ranges(target, ranges) else external
        entry = group.setdefault(target, {"kinds": set(), "sources": set()})
        entry["kinds"].add(kind)
        entry["sources"].add(source)
    return {
        "in_module": in_module,
        "external": external,
        "overridden_nonfunctions": {target: in_module[target] for target in sorted(set(in_module) & nonfunctions)},
        "missing": sorted(set(in_module) - set(known) - nonfunctions),
    }


def load_override_nonfunctions(path):
    import tomllib
    with open(path, "rb") as stream:
        config = tomllib.load(stream)
    return {entry["at"] + 8 for entry in config.get("jal_next", [])}


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def format_targets(entries):
    lines = []
    for target, details in sorted(entries.items()):
        kinds = ",".join(sorted(details["kinds"]))
        lines.append(f"0x{target:08x} {kinds} sources={len(details['sources'])}")
    return lines


def write_report(path, trace, prx, edges, analyzed, effective, audit):
    targets = {target for _, _, target in edges}
    lines = [
        "# KZL executed call-target audit",
        f"trace = {os.path.basename(trace)}",
        f"trace_sha256 = {file_sha256(trace)}",
        f"prx_sha256 = {file_sha256(prx)}",
        f"analyzer_functions = {len(analyzed)}",
        f"effective_functions = {len(effective)}",
        f"unique_edges = {len(edges)}",
        f"unique_targets = {len(targets)}",
        f"in_module_targets = {len(audit['in_module'])}",
        f"external_targets = {len(audit['external'])}",
        f"overridden_nonfunctions = {len(audit['overridden_nonfunctions'])}",
        f"missing_targets = {len(audit['missing'])}",
        "",
        "[missing]",
    ]
    lines.extend(f"0x{target:08x}" for target in audit["missing"])
    lines.extend(["", "[overridden_nonfunctions]", *format_targets(audit["overridden_nonfunctions"]),
                  "", "[in_module]", *format_targets(audit["in_module"]),
                  "", "[external]", *format_targets(audit["external"]), ""])
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="ascii", newline="\n") as stream:
        stream.write("\n".join(lines))


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    opts = dict((o[2:].split("=", 1) + [""])[:2] for o in argv[1:] if o.startswith("--"))
    if len(args) != 1:
        sys.stderr.write(__doc__)
        return 2

    trace = os.path.abspath(args[0])
    prx = os.path.abspath(opts.get("prx") or os.path.join(ROOT, "build", "kzl", "disc", "KZL.PRX"))
    base = int(opts.get("base", "08804000"), 16)
    overrides = os.path.abspath(opts.get("overrides") or os.path.join(ROOT, "config", "kzl_overrides.toml"))
    report = os.path.abspath(opts.get("report") or os.path.join(ROOT, "research", "kzl_calltargets.txt"))
    if not os.path.exists(prx):
        print(f"missing {prx}; run tools/kzl/extract.py first")
        return 1
    if not os.path.exists(overrides):
        print(f"missing overrides file: {overrides}")
        return 1

    if ANALYZE_DIR not in sys.path:
        sys.path.insert(0, ANALYZE_DIR)
    from analyze import Elf, analyze

    try:
        edges = parse_call_trace(trace)
    except (OSError, TraceFormatError) as error:
        print(error)
        return 2
    elf = Elf(prx, base=base)
    analyzed, ranges = analyze(elf)
    nonfunctions = load_override_nonfunctions(overrides)
    effective = analyzed - nonfunctions
    audit = audit_targets(edges, effective, ranges, nonfunctions)
    write_report(report, trace, prx, edges, analyzed, effective, audit)

    print(f"{len(edges):,} edges, {len(audit['in_module']):,} in-module targets, "
          f"{len(audit['missing']):,} missing; report {report}")
    if audit["missing"]:
        print("missing: " + " ".join(f"0x{target:08x}" for target in audit["missing"]))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
