#!/usr/bin/env python3
"""Record unique executed jal/jalr edges with the patched PPSSPPHeadless. -> T-2.7

    ppsspp_calls.py <ISO> [--start=08804000] [--timeout=60]
                     [--out=build/kzl/ref/calls_ppsspp.txt]
                     [--padscript=PATH] [--headless=PATH]

The PPSSPP patch writes one line per unique source/target edge, so a long boot capture stays
small. Run calltargets.py afterward to compare the targets with the static function inventory.
"""

import os
import subprocess
import sys


ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
DEFAULT_HEADLESS = os.path.join(os.path.dirname(ROOT), "ppsspp", "Windows", "x64", "Release", "PPSSPPHeadless.exe")


def main(argv):
    args = [a for a in argv[1:] if not a.startswith("--")]
    opts = dict((o[2:].split("=", 1) + [""])[:2] for o in argv[1:] if o.startswith("--"))
    if len(args) != 1:
        sys.stderr.write(__doc__)
        return 2

    exe = opts.get("headless") or os.environ.get("PPSSPP_HEADLESS") or DEFAULT_HEADLESS
    if not os.path.exists(exe):
        print(f"PPSSPPHeadless not found at {exe}; see tools/ppsspp/README.md")
        return 1

    iso = os.path.abspath(args[0])
    if not os.path.exists(iso):
        print(f"ISO not found: {iso}")
        return 1
    out = os.path.abspath(opts.get("out") or os.path.join(ROOT, "build", "kzl", "ref", "calls_ppsspp.txt"))
    timeout = int(opts.get("timeout", "60"))
    if timeout <= 0:
        print("--timeout must be positive")
        return 2
    try:
        int(opts.get("start", "08804000"), 16)
    except ValueError:
        print("--start must be a hexadecimal address")
        return 2
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if os.path.exists(out):
        os.remove(out)

    env = dict(os.environ)
    for name in ("PSPRECOMP_TRACE", "PSPRECOMP_TRACE_START", "PSPRECOMP_TRACE_STEPS",
                 "PSPRECOMP_TRACE_TARGET"):
        env.pop(name, None)
    env["PSPRECOMP_CALLTRACE"] = out
    env["PSPRECOMP_CALLTRACE_START"] = opts.get("start", "08804000")
    padscript = opts.get("padscript")
    if padscript:
        padscript = os.path.abspath(padscript)
        if not os.path.exists(padscript):
            print(f"pad script not found: {padscript}")
            return 1
        env["PSPRECOMP_PADSCRIPT"] = padscript
    else:
        env.pop("PSPRECOMP_PADSCRIPT", None)

    log = out + ".log"
    cmd = [exe, "-i", "--graphics=software", f"--timeout={timeout}", iso]
    try:
        with open(log, "w", encoding="utf-8") as stream:
            result = subprocess.run(cmd, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                    timeout=timeout + 30)
    except subprocess.TimeoutExpired:
        print(f"PPSSPPHeadless exceeded the {timeout + 30}-second process limit; see {log}")
        return 1
    if result.returncode:
        print(f"PPSSPPHeadless exited {result.returncode}; see {log}")
        return result.returncode
    if not os.path.exists(out):
        print(f"PPSSPPHeadless did not create {out}; check that the call-trace patch is applied")
        return 1

    with open(out, "rb") as stream:
        edges = sum(1 for line in stream if line.startswith(b"0x"))
    if edges == 0:
        print(f"{out}: no call edges; start PC may not have been reached (log {log})")
        return 1
    print(f"{out}: {edges:,} unique call edges ({timeout} s, log {log})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
