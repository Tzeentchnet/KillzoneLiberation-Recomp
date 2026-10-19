#!/usr/bin/env python3
"""Side-by-side diff of the HLE call sequence: PPSSPP debug log vs our runtime.

    hleseq.py <ppsspp.log> <nidseq_mine.txt> [--from NAME] [--skip N] [--count N] [--threads a,b]

<ppsspp.log>       PPSSPP desktop log at debug level (-d), as in build/kzl/ref/ppsspp_boot_debug.log.
<nidseq_mine.txt>  written by kzl.exe with SR_NIDLOG=1: one "0x<nid> <thread uid>" line per call.

Both sides are reduced to function names, runs of the same call are collapsed ("name x5"), and the
two lists are aligned with difflib. --from starts both sides at the first call of NAME (after
--skip earlier ones); --threads keeps only those PPSSPP thread names (default: every thread except
the bootloader's, idle and SceIoAsync). PPSSPP does not log every call at debug level (verbose
ones such as sceRtcGetCurrentTick and sceKernelGetSystemTimeLow are missing), so calls only on
our side are expected; calls only on PPSSPP's side are the interesting ones.
"""
import argparse
import difflib
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NID_NAMES = os.path.join(HERE, "..", "..", "external", "psp-recomp", "src", "rt", "nid_names.h")

# "<time> <thread name padded to 12> <level>[<cat>]: <file>:<line> <message>"
LOG_RE = re.compile(r"^\d\d:\d\d:\d\d\d (.{12}) [DIWEN]\[[^\]]+\]: \S+ (.*)$")
# The call a line logs: "<ret>=<name>(...)" or "<name>(...)" at the start of the message.
CALL_RE = re.compile(r"^(?:\S*=)?((?:__)?sce[A-Za-z0-9_]+)\(")
SKIP_THREADS = {"root", "idle0", "idle1", "SceIoAsync", "ExecLoader"}


def nid_names():
    names = {}
    with open(NID_NAMES, encoding="utf-8") as f:
        for line in f:
            m = re.search(r"0x([0-9a-fA-F]{8})u?\s*,\s*\"([^\"]+)\"", line)
            if m:
                names[int(m.group(1), 16)] = m.group(2)
    return names


def ppsspp_calls(path, threads):
    out = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = LOG_RE.match(line.rstrip("\n"))
            if not m:
                continue
            thread, msg = m.group(1).strip(), m.group(2)
            if threads is not None and thread not in threads:
                continue
            if threads is None and thread in SKIP_THREADS:
                continue
            if msg.startswith("Importing ") or "Context switch" in msg:
                continue
            c = CALL_RE.match(msg)
            if c:
                out.append(c.group(1))
    return out


def mine_calls(path, names):
    out = []
    with open(path) as f:
        for line in f:
            parts = line.split()
            if parts:
                nid = int(parts[0], 16)
                out.append(names.get(nid, "0x%08x" % nid))
    return out


def collapse(seq):
    out = []
    for s in seq:
        if out and out[-1][0] == s:
            out[-1][1] += 1
        else:
            out.append([s, 1])
    return ["%s x%d" % (s, n) if n > 1 else s for s, n in out]


def start_at(seq, name, skip):
    seen = 0
    for i, s in enumerate(seq):
        if s == name:
            if seen == skip:
                return seq[i:]
            seen += 1
    sys.exit("%s not found (skip=%d)" % (name, skip))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ppsspp_log")
    ap.add_argument("mine")
    ap.add_argument("--from", dest="start")
    ap.add_argument("--skip", type=int, default=0, help="start at the (N+1)th call of --from on each side")
    ap.add_argument("--count", type=int, default=80)
    ap.add_argument("--threads", help="comma-separated PPSSPP thread names to keep")
    a = ap.parse_args()

    threads = set(a.threads.split(",")) if a.threads else None
    theirs = ppsspp_calls(a.ppsspp_log, threads)
    mine = mine_calls(a.mine, nid_names())
    if a.start:
        theirs = start_at(theirs, a.start, a.skip)
        mine = start_at(mine, a.start, a.skip)
    theirs = collapse(theirs)[: a.count]
    mine = collapse(mine)[: a.count]

    w = 46
    print("%-*s | %s" % (w, "PPSSPP", "ours"))
    print("-" * w + "-+-" + "-" * w)
    sm = difflib.SequenceMatcher(a=theirs, b=mine, autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        left, right = theirs[i1:i2], mine[j1:j2]
        mark = " " if op == "equal" else "*"
        for k in range(max(len(left), len(right))):
            l = left[k] if k < len(left) else ""
            r = right[k] if k < len(right) else ""
            print("%-*s %s %s" % (w, l, "|" if mark == " " else mark, r))


if __name__ == "__main__":
    main()
