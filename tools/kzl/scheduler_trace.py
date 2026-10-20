#!/usr/bin/env python3
"""Run multi-start PPSSPP/runtime scheduler traces and compare them streaming."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass


ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
POINTS_HEADER = "# KZL scheduler trace points v1"
IGNORED_PC_RANGES = (
    ("08000000-08800000", 0x08000000, 0x08800000),
    ("09f00000-0a000000", 0x09F00000, 0x0A000000),
)
FIXED_RTC_TICK = "62135596923456789"


class SchedulerTraceError(RuntimeError):
    pass


@dataclass(frozen=True)
class TracePoint:
    name: str
    start_pc: int
    steps: int


def read_points(path):
    points = []
    names = set()
    addresses = set()
    seen_header = False
    with open(path, "r", encoding="ascii") as stream:
        for line_number, raw_line in enumerate(stream, 1):
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("#"):
                if line == POINTS_HEADER:
                    seen_header = True
                continue
            fields = line.split()
            if len(fields) != 3:
                raise SchedulerTraceError(
                    f"{path}:{line_number}: expected name, start PC, and step count"
                )
            name, start_text, steps_text = fields
            if not re.fullmatch(r"[a-z][a-z0-9_-]*", name):
                raise SchedulerTraceError(
                    f"{path}:{line_number}: invalid point name {name!r}"
                )
            try:
                start_pc = int(start_text, 16)
                steps = int(steps_text, 10)
            except ValueError as exc:
                raise SchedulerTraceError(
                    f"{path}:{line_number}: invalid start PC or step count"
                ) from exc
            if start_pc & 3 or not 0x08800000 <= start_pc < 0x0A000000:
                raise SchedulerTraceError(
                    f"{path}:{line_number}: start PC is outside aligned user code"
                )
            if not 1 <= steps <= 50000000:
                raise SchedulerTraceError(
                    f"{path}:{line_number}: steps must be in [1, 50000000]"
                )
            if name in names or start_pc in addresses:
                raise SchedulerTraceError(
                    f"{path}:{line_number}: duplicate point name or address"
                )
            names.add(name)
            addresses.add(start_pc)
            points.append(TracePoint(name, start_pc, steps))
    if not seen_header:
        raise SchedulerTraceError(f"{path}: missing {POINTS_HEADER!r}")
    if len(points) < 3:
        raise SchedulerTraceError(f"{path}: at least three trace points are required")
    if points[0].name != "module_start" or points[0].start_pc != 0x08804000:
        raise SchedulerTraceError(
            f"{path}: first point must be module_start at 0x08804000"
        )
    return points


def count_steps(path):
    with open(path, "rb") as stream:
        return sum(1 for line in stream if line.strip() and not line.startswith(b"#"))


def count_comparable_steps(path):
    count = 0
    with open(path, "r", encoding="ascii") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip() or line.startswith("#"):
                continue
            fields = line.split()
            if len(fields) < 2 or not fields[1].startswith("pc=0x"):
                raise SchedulerTraceError(
                    f"{path}:{line_number}: malformed trace step"
                )
            try:
                pc = int(fields[1][3:], 16)
            except ValueError as exc:
                raise SchedulerTraceError(
                    f"{path}:{line_number}: malformed trace PC"
                ) from exc
            if not any(start <= pc < end for _, start, end in IGNORED_PC_RANGES):
                count += 1
    return count


def write_seed_trace(source, destination):
    saw_init = False
    with open(source, "r", encoding="ascii") as input_stream, open(
        destination, "w", encoding="ascii", newline="\n"
    ) as output_stream:
        for line in input_stream:
            if not line.startswith("#"):
                break
            output_stream.write(line)
            if line.startswith("# init "):
                saw_init = True
    if not saw_init:
        raise SchedulerTraceError(f"{source}: trace has no # init state")


def require_file(path, label):
    if not path or not os.path.isfile(path):
        raise SchedulerTraceError(f"{label} is missing: {path}")
    return os.path.abspath(path)


def require_directory(path, label):
    if not path or not os.path.isdir(path):
        raise SchedulerTraceError(f"{label} is missing: {path}")
    return os.path.abspath(path)


def run_ppsspp(executable, iso, point, output, memstick, timeout):
    done = output + ".done"
    log = output + ".log"
    for path in (output, done, log):
        if os.path.exists(path):
            os.remove(path)
    env = os.environ.copy()
    env.update(
        {
            "PSPRECOMP_TRACE": output,
            "PSPRECOMP_TRACE_START": f"{point.start_pc:08x}",
            "PSPRECOMP_TRACE_STEPS": str(point.steps),
            "PSPRECOMP_TRACE_TARGET": f"kzl-{point.name}",
            "PSPRECOMP_MEMSTICK": memstick,
            "PSPRECOMP_RTC_TICK": FIXED_RTC_TICK,
        }
    )
    started = time.monotonic()
    with open(log, "w", encoding="utf-8", errors="replace") as stream:
        process = subprocess.Popen(
            [
                executable,
                "-i",
                "--graphics=software",
                f"--timeout={timeout}",
                iso,
            ],
            env=env,
            stdout=stream,
            stderr=subprocess.STDOUT,
        )
        deadline = started + timeout
        while process.poll() is None and time.monotonic() < deadline:
            if os.path.isfile(done):
                process.kill()
                process.wait()
                break
            time.sleep(0.1)
        if process.poll() is None:
            process.kill()
            process.wait()
            raise SchedulerTraceError(
                f"PPSSPP point {point.name} timed out; see {log}"
            )
    if not os.path.isfile(done):
        raise SchedulerTraceError(
            f"PPSSPP point {point.name} ended before completion; see {log}"
        )
    steps = count_steps(output)
    if steps != point.steps:
        raise SchedulerTraceError(
            f"PPSSPP point {point.name}: expected {point.steps} steps, got {steps}"
        )
    return time.monotonic() - started


def run_runtime(
    executable, iso, image, seed_trace, point, trace_steps, output, memstick, timeout
):
    done = output + ".done"
    log = output + ".log"
    for path in (output, done, log):
        if os.path.exists(path):
            os.remove(path)
    env = os.environ.copy()
    env.update(
        {
            "PSP_ISO": iso,
            "PSP_VFPU_TABLES": os.path.join(
                ROOT, "external", "psp-recomp", "assets", "vfpu"
            ),
            "SR_INTERP_MISS_LOG": output + ".misses",
            "SR_MEMSTICK": memstick,
            "SR_NOAUDIO": "1",
            "SR_NOVBPACE": "1",
            "SR_RTC_FIXED_TICK": FIXED_RTC_TICK,
            "SR_TRACE_STEPS": str(trace_steps),
        }
    )
    if os.path.exists(env["SR_INTERP_MISS_LOG"]):
        os.remove(env["SR_INTERP_MISS_LOG"])
    command = [
        executable,
        "--image",
        image,
        "08804000",
        "08804000",
        seed_trace,
        output,
        "--sched",
        f"--trace-start={point.start_pc:08x}",
    ]
    started = time.monotonic()
    try:
        with open(log, "w", encoding="utf-8", errors="replace") as stream:
            result = subprocess.run(
                command,
                cwd=os.path.join(ROOT, "external", "psp-recomp"),
                env=env,
                stdout=stream,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                check=False,
            )
    except subprocess.TimeoutExpired as exc:
        raise SchedulerTraceError(
            f"runtime point {point.name} timed out; see {log}"
        ) from exc
    if result.returncode != 0 or not os.path.isfile(done):
        raise SchedulerTraceError(
            f"runtime point {point.name} failed with {result.returncode}; see {log}"
        )
    steps = count_steps(output)
    if steps != trace_steps:
        raise SchedulerTraceError(
            f"runtime point {point.name}: expected {trace_steps} steps, got {steps}"
        )
    if os.path.exists(env["SR_INTERP_MISS_LOG"]):
        raise SchedulerTraceError(
            f"runtime point {point.name} used interpreter fallback; "
            f"see {env['SR_INTERP_MISS_LOG']}"
        )
    return time.monotonic() - started


def compare_traces(oracle, runtime):
    tracediff = os.path.join(
        ROOT, "external", "psp-recomp", "tools", "tracediff.py"
    )
    command = [sys.executable, tracediff, oracle, runtime]
    for value, _, _ in IGNORED_PC_RANGES:
        command.extend(["--ignore-pc-range", value])
    command.append("--ignore-syscall-writes")
    result = subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.returncode:
        raise SchedulerTraceError(result.stdout.strip())
    return result.stdout.strip()


def run(args):
    points_path = require_file(args.points, "trace-point manifest")
    points = read_points(points_path)
    iso = require_file(args.iso, "game ISO")
    ppsspp = require_file(args.ppsspp, "PPSSPPHeadless")
    runtime = require_file(args.runtime, "runtime")
    image = require_file(args.image, "recompiled image")
    ppsspp_template = require_directory(
        args.ppsspp_memstick_template, "PPSSPP memstick template"
    )
    runtime_template = require_directory(
        args.runtime_memstick_template, "runtime memstick template"
    )
    output = os.path.abspath(args.output)
    os.makedirs(output, exist_ok=True)
    results = []
    seed_trace = None
    for point in points:
        oracle_trace = os.path.join(output, f"{point.name}.ppsspp.txt")
        runtime_trace = os.path.join(output, f"{point.name}.runtime.txt")
        with tempfile.TemporaryDirectory(
            prefix=f"{point.name}-ppsspp-", dir=output
        ) as ppsspp_memstick, tempfile.TemporaryDirectory(
            prefix=f"{point.name}-runtime-", dir=output
        ) as runtime_memstick:
            shutil.copytree(
                ppsspp_template, ppsspp_memstick, dirs_exist_ok=True
            )
            shutil.copytree(
                runtime_template, runtime_memstick, dirs_exist_ok=True
            )
            oracle_seconds = run_ppsspp(
                ppsspp, iso, point, oracle_trace, ppsspp_memstick, args.timeout
            )
            if seed_trace is None:
                seed_trace = os.path.join(output, "module_start.seed.txt")
                write_seed_trace(oracle_trace, seed_trace)
            compared_steps = count_comparable_steps(oracle_trace)
            runtime_seconds = run_runtime(
                runtime, iso, image, seed_trace, point, compared_steps, runtime_trace,
                runtime_memstick, args.timeout,
            )
        comparison = compare_traces(oracle_trace, runtime_trace)
        results.append(
            {
                "name": point.name,
                "start_pc": f"0x{point.start_pc:08x}",
                "captured_steps": point.steps,
                "compared_steps": compared_steps,
                "ppsspp_seconds": round(oracle_seconds, 3),
                "runtime_seconds": round(runtime_seconds, 3),
                "comparison": comparison,
            }
        )
        print(
            f"{point.name}: {compared_steps:,} steps matched "
            f"(PPSSPP {oracle_seconds:.1f}s, runtime {runtime_seconds:.1f}s)"
        )
    report = os.path.join(output, "scheduler_trace.json")
    with open(report, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(
            {
                "schema": 1,
                "ignored_pc_ranges": [value for value, _, _ in IGNORED_PC_RANGES],
                "ignored_syscall_writes": True,
                "points": results,
            },
            stream,
            indent=2,
        )
        stream.write("\n")
    print(f"scheduler trace gate passed; report: {report}")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iso", default=os.environ.get("KZL_ISO"))
    parser.add_argument("--ppsspp", default=os.environ.get("PPSSPP_HEADLESS"))
    parser.add_argument("--runtime", required=True)
    parser.add_argument(
        "--image",
        default=os.path.join(ROOT, "build", "kzl", "gen", "kzl_image.bin"),
    )
    parser.add_argument(
        "--points",
        default=os.path.join(ROOT, "config", "kzl_scheduler_trace_points.txt"),
    )
    parser.add_argument("--ppsspp-memstick-template", required=True)
    parser.add_argument("--runtime-memstick-template", required=True)
    parser.add_argument(
        "--output",
        default=os.path.join(ROOT, "build", "kzl", "scheduler_trace"),
    )
    parser.add_argument("--timeout", type=int, default=1200)
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    return args


def main(argv=None):
    try:
        run(parse_args(argv))
    except (OSError, SchedulerTraceError) as exc:
        print(f"scheduler_trace: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
