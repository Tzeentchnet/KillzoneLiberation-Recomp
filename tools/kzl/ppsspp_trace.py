#!/usr/bin/env python3
"""Record a psp-recomp CPU trace of KZL with the patched PPSSPPHeadless.  -> T-2.11, F-048

    ppsspp_trace.py <ISO> [--start=08804000] [--steps=5000000] [--out=build/kzl/ref/trace_ppsspp.txt]
                    [--timeout=SECONDS] [--headless=PATH]

Runs PPSSPPHeadless on the interpreter with the software renderer and the PSPRECOMP_TRACE_*
variables set (see tools/ppsspp/README.md). The default start is module_start. The headless
exe is taken from --headless, then $PPSSPP_HEADLESS, then ../ppsspp next to this repo.
"""
import os
import subprocess
import sys
import time

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
    out = os.path.abspath(opts.get("out") or os.path.join(ROOT, "build", "kzl", "ref", "trace_ppsspp.txt"))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    steps = int(opts.get("steps", "5000000"))
    env = dict(os.environ, PSPRECOMP_TRACE=out, PSPRECOMP_TRACE_START=opts.get("start", "08804000"),
               PSPRECOMP_TRACE_STEPS=str(steps), PSPRECOMP_TRACE_TARGET="kzl")
    # The trace stops by itself after `steps`; the timeout only bounds the emulator run.
    timeout = opts.get("timeout") or str(max(20, steps // 50000))
    log, done = out + ".log", out + ".done"
    if os.path.exists(done):
        os.remove(done)
    t0 = time.time()
    with open(log, "w") as f:
        p = subprocess.Popen([exe, "-i", "--graphics=software", f"--timeout={timeout}", os.path.abspath(args[0])],
                             env=env, stdout=f, stderr=subprocess.STDOUT)
        # The patched build writes <trace>.done when the trace is complete; stop the emulator then.
        while p.poll() is None:
            if os.path.exists(done):
                p.kill()
                p.wait()
                break
            time.sleep(0.2)
    r = p
    lines = 0
    if os.path.exists(out):
        with open(out, "rb") as f:
            lines = sum(1 for ln in f if not ln.startswith(b"#"))
    print(f"{out}: {lines:,} steps in {time.time() - t0:.0f} s (headless exit {r.returncode}, log {log})")
    if lines < steps:
        print(f"warning: wanted {steps:,} steps; the start pc may not have been reached or the run timed out")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
