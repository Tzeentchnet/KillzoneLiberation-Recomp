#!/usr/bin/env python3
"""Capture and compare the 50-frame KZL PPSSPP/D3D12 golden sequence."""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass


FRAME_COUNT = 50
MANIFEST_HEADER = "# psp-recomp golden frames v2"
PADSCRIPT_HEADER = "# psp-recomp pad script v3"
DISPATCH_MISS_HEADER = "# KZL interpreter-fallback regression list v1"
REQUIRED_SCENES = {"boot", "menu", "gameplay", "cutscene", "hud"}


class GoldenFrameError(RuntimeError):
    pass


@dataclass(frozen=True)
class CaptureFrame:
    ppsspp_present: int
    runtime_present: int
    name: str
    scene: str


@dataclass(frozen=True)
class PadEvent:
    ppsspp_vblank: int
    runtime_present: int
    mask: int
    ppsspp_width: int
    runtime_width: int


def read_dispatch_misses(path, missing_ok=False):
    try:
        stream = open(path, "r", encoding="ascii")
    except FileNotFoundError:
        if missing_ok:
            return set()
        raise
    addresses = set()
    with stream:
        for line_number, raw_line in enumerate(stream, 1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if (
                len(line) != 10
                or not line.startswith("0x")
                or any(character not in "0123456789abcdefABCDEF" for character in line[2:])
            ):
                raise GoldenFrameError(
                    f"{path}:{line_number}: invalid dispatch-miss address"
                )
            address = int(line, 16)
            if address in addresses:
                raise GoldenFrameError(
                    f"{path}:{line_number}: duplicate dispatch-miss address {line}"
                )
            addresses.add(address)
    return addresses


def validate_dispatch_misses(expected_path, actual_path):
    expected = read_dispatch_misses(expected_path)
    actual = read_dispatch_misses(actual_path, missing_ok=True)
    if actual != expected:
        unexpected = sorted(actual - expected)
        missing = sorted(expected - actual)
        details = []
        if unexpected:
            details.append(
                "unexpected " + ", ".join(f"0x{address:08x}" for address in unexpected)
            )
        if missing:
            details.append(
                "missing " + ", ".join(f"0x{address:08x}" for address in missing)
            )
        raise GoldenFrameError("dispatch-miss regression: " + "; ".join(details))


def read_manifest(path):
    frames = []
    names = set()
    scenes = set()
    previous_ppsspp_present = 0
    previous_runtime_present = 0
    seen_header = False
    with open(path, "r", encoding="ascii") as stream:
        for line_number, raw_line in enumerate(stream, 1):
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("#"):
                if line == MANIFEST_HEADER:
                    seen_header = True
                continue
            fields = line.split()
            if len(fields) != 4:
                raise GoldenFrameError(
                    f"{path}:{line_number}: expected PPSSPP/runtime presents, "
                    "name, and scene"
                )
            ppsspp_present_text, runtime_present_text, name, scene = fields
            try:
                ppsspp_present = int(ppsspp_present_text, 10)
                runtime_present = int(runtime_present_text, 10)
            except ValueError as exc:
                raise GoldenFrameError(
                    f"{path}:{line_number}: invalid presented-frame index"
                ) from exc
            if (
                ppsspp_present <= previous_ppsspp_present
                or runtime_present <= previous_runtime_present
            ):
                raise GoldenFrameError(
                    f"{path}:{line_number}: both presented-frame indices must increase"
                )
            if (
                not name.endswith(".ppm")
                or "/" in name
                or "\\" in name
                or name in names
            ):
                raise GoldenFrameError(
                    f"{path}:{line_number}: invalid or duplicate PPM name"
                )
            if scene not in REQUIRED_SCENES:
                raise GoldenFrameError(
                    f"{path}:{line_number}: unknown scene '{scene}'"
                )
            frames.append(
                CaptureFrame(ppsspp_present, runtime_present, name, scene)
            )
            names.add(name)
            scenes.add(scene)
            previous_ppsspp_present = ppsspp_present
            previous_runtime_present = runtime_present
    if not seen_header:
        raise GoldenFrameError(f"{path}: missing '{MANIFEST_HEADER}' header")
    if len(frames) != FRAME_COUNT:
        raise GoldenFrameError(
            f"{path}: expected {FRAME_COUNT} frames, found {len(frames)}"
        )
    missing_scenes = REQUIRED_SCENES - scenes
    if missing_scenes:
        raise GoldenFrameError(
            f"{path}: missing required scenes: {', '.join(sorted(missing_scenes))}"
        )
    return frames


def read_padscript(path):
    events = []
    previous_ppsspp_vblank = -1
    previous_runtime_present = -1
    seen_header = False
    with open(path, "r", encoding="ascii") as stream:
        for line_number, raw_line in enumerate(stream, 1):
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("#"):
                if line == PADSCRIPT_HEADER:
                    seen_header = True
                continue
            fields = line.split()
            if len(fields) != 5:
                raise GoldenFrameError(
                    f"{path}:{line_number}: expected PPSSPP/runtime vblanks, "
                    "button mask, and PPSSPP/runtime widths"
                )
            try:
                ppsspp_vblank = int(fields[0], 10)
                runtime_present = int(fields[1], 10)
                mask = int(fields[2], 16)
                ppsspp_width = int(fields[3], 10)
                runtime_width = int(fields[4], 10)
            except ValueError as exc:
                raise GoldenFrameError(
                    f"{path}:{line_number}: invalid pad event"
                ) from exc
            if (
                ppsspp_vblank <= previous_ppsspp_vblank
                or runtime_present <= previous_runtime_present
            ):
                raise GoldenFrameError(
                    f"{path}:{line_number}: PPSSPP vblank and runtime "
                    "presentation indices must increase"
                )
            if (
                not 0 <= mask <= 0xFFFFFFFF
                or ppsspp_width <= 0
                or runtime_width <= 0
            ):
                raise GoldenFrameError(
                    f"{path}:{line_number}: invalid button mask or pulse width"
                )
            events.append(
                PadEvent(
                    ppsspp_vblank,
                    runtime_present,
                    mask,
                    ppsspp_width,
                    runtime_width,
                )
            )
            previous_ppsspp_vblank = ppsspp_vblank
            previous_runtime_present = runtime_present
    if not seen_header:
        raise GoldenFrameError(f"{path}: missing '{PADSCRIPT_HEADER}' header")
    if not events:
        raise GoldenFrameError(f"{path}: pad script has no events")
    if len(events) > 256:
        raise GoldenFrameError(f"{path}: pad script exceeds 256 events")
    return events


def _resolve_file(path, description):
    resolved = os.path.abspath(path)
    if not os.path.isfile(resolved):
        raise GoldenFrameError(f"{description} does not exist: {resolved}")
    return resolved


def _resolve_directory(path, description):
    resolved = os.path.abspath(path)
    if not os.path.isdir(resolved):
        raise GoldenFrameError(f"{description} does not exist: {resolved}")
    if not os.path.isdir(os.path.join(resolved, "PSP", "SAVEDATA")):
        raise GoldenFrameError(
            f"{description} must contain a PSP/SAVEDATA directory: {resolved}"
        )
    return resolved


def _prepare_capture_dir(path, frames):
    os.makedirs(path, exist_ok=True)
    for frame in frames:
        output = os.path.join(path, frame.name)
        if os.path.exists(output):
            os.remove(output)
    complete = os.path.join(path, "capture.complete")
    if os.path.exists(complete):
        os.remove(complete)


def _run(name, command, environment, cwd, timeout, log_directory=None):
    log_path = os.path.join(log_directory or cwd, "capture.log")
    print(f"{name}: {' '.join(command)}")
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode(errors="replace")
        with open(log_path, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(output)
        raise GoldenFrameError(
            f"{name} timed out after {timeout}s; see {log_path}"
        ) from exc
    with open(log_path, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(result.stdout)
    if result.returncode:
        tail = "\n".join(result.stdout.splitlines()[-20:])
        raise GoldenFrameError(
            f"{name} exited with code {result.returncode}; see {log_path}\n{tail}"
        )


def _validate_capture(path, frames):
    expected = {frame.name for frame in frames}
    found = {
        name
        for name in os.listdir(path)
        if name.lower().endswith(".ppm") and os.path.isfile(os.path.join(path, name))
    }
    missing = sorted(expected - found)
    unexpected = sorted(found - expected)
    if missing or unexpected:
        details = []
        if missing:
            details.append(f"missing: {', '.join(missing)}")
        if unexpected:
            details.append(f"unexpected: {', '.join(unexpected)}")
        raise GoldenFrameError(f"invalid capture in {path}: {'; '.join(details)}")
    complete = os.path.join(path, "capture.complete")
    try:
        with open(complete, "r", encoding="ascii") as stream:
            count = int(stream.read().strip(), 10)
    except (OSError, ValueError) as exc:
        raise GoldenFrameError(f"invalid completion marker: {complete}") from exc
    if count != FRAME_COUNT:
        raise GoldenFrameError(
            f"completion marker reports {count} frames, expected {FRAME_COUNT}"
        )


def capture(args, frames):
    root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    manifest = _resolve_file(args.manifest, "capture manifest")
    padscript = _resolve_file(args.padscript, "pad script")
    read_padscript(padscript)
    iso = _resolve_file(args.iso, "game ISO")
    ppsspp = _resolve_file(args.ppsspp, "PPSSPPHeadless")
    runtime = _resolve_file(args.runtime, "D3D12 runtime")
    image = _resolve_file(args.image, "recompiled image")
    ppsspp_memstick_template = _resolve_directory(
        args.ppsspp_memstick_template, "PPSSPP golden memstick template"
    )
    runtime_memstick_template = _resolve_directory(
        args.runtime_memstick_template, "runtime golden memstick template"
    )
    dispatch_misses = _resolve_file(
        args.dispatch_misses, "dispatch-miss regression list"
    )
    output = os.path.abspath(args.output)
    dispatch_miss_log = os.path.join(output, "dispatch_misses.txt")
    if os.path.exists(dispatch_miss_log):
        os.remove(dispatch_miss_log)
    oracle_dir = os.path.join(output, "ppsspp")
    d3d12_dir = os.path.join(output, "d3d12")
    _prepare_capture_dir(oracle_dir, frames)
    _prepare_capture_dir(d3d12_dir, frames)

    inherited = os.environ.copy()
    for variable in (
        "PSPRECOMP_TRACE",
        "PSPRECOMP_CALLTRACE",
        "PSPRECOMP_CAPTURE_MANIFEST",
        "PSPRECOMP_CAPTURE_DIR",
    ):
        inherited.pop(variable, None)

    with tempfile.TemporaryDirectory(
        prefix="ppsspp_memstick-", dir=output
    ) as oracle_memstick, tempfile.TemporaryDirectory(
        prefix="runtime_memstick-", dir=output
    ) as runtime_memstick:
        shutil.copytree(
            ppsspp_memstick_template, oracle_memstick, dirs_exist_ok=True
        )
        shutil.copytree(
            runtime_memstick_template, runtime_memstick, dirs_exist_ok=True
        )
        oracle_env = inherited.copy()
        oracle_env.update(
            {
                "PSPRECOMP_PADSCRIPT": padscript,
                "PSPRECOMP_CAPTURE_MANIFEST": manifest,
                "PSPRECOMP_CAPTURE_DIR": oracle_dir,
                "PSPRECOMP_MEMSTICK": oracle_memstick,
            }
        )
        _run(
            "PPSSPP software renderer",
            [ppsspp, "--graphics=software", f"--timeout={args.timeout}", iso],
            oracle_env,
            oracle_dir,
            args.timeout,
        )
        _validate_capture(oracle_dir, frames)

        runtime_env = inherited.copy()
        runtime_env.update(
            {
                "PSP_ISO": iso,
                "PSPRECOMP_CAPTURE_MANIFEST": manifest,
                "PSPRECOMP_CAPTURE_DIR": d3d12_dir,
                "SR_GPU": "d3d12",
                "SR_GRAPHICS_CONFIG": "0",
                "SR_INPUT_CONFIG": "0",
                "SR_D3D12_SCALE": "1",
                "SR_MEMSTICK": runtime_memstick,
                "SR_NOVBPACE": "1",
                "SR_PADSCRIPT": padscript,
                "SR_INTERP_MISS_LOG": dispatch_miss_log,
                "PSP_VFPU_TABLES": os.path.join(
                    root, "external", "psp-recomp", "assets", "vfpu"
                ),
            }
        )
        if args.warp:
            runtime_env["SR_D3D12_WARP"] = "1"
        else:
            runtime_env.pop("SR_D3D12_WARP", None)
        _run(
            "D3D12 runtime",
            [runtime, "--boot", image, "08804000", "08804000", "none", "--gui"],
            runtime_env,
            os.path.join(root, "external", "psp-recomp"),
            args.timeout,
            d3d12_dir,
        )
        _validate_capture(d3d12_dir, frames)
        validate_dispatch_misses(dispatch_misses, dispatch_miss_log)
    return oracle_dir, d3d12_dir


def compare(args, oracle_dir, d3d12_dir):
    root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    ppmdiff = os.path.join(root, "external", "psp-recomp", "tools", "ppmdiff.py")
    report = os.path.join(os.path.abspath(args.output), "ppmdiff.json")
    command = [
        sys.executable,
        ppmdiff,
        oracle_dir,
        d3d12_dir,
        "--manifest",
        os.path.abspath(args.manifest),
        "--threshold",
        str(args.threshold),
        "--max-threshold-pixels",
        str(args.max_threshold_pixels),
        "--max-channel-delta",
        str(args.max_channel_delta),
        "--json",
        report,
    ]
    if args.max_different_pixels is not None:
        command.extend(
            ["--max-different-pixels", str(args.max_different_pixels)]
        )
    result = subprocess.run(command, check=False)
    if result.returncode:
        raise GoldenFrameError(
            f"ppmdiff rejected the capture with code {result.returncode}; see {report}"
        )
    print(f"golden-frame comparison passed; report: {report}")


def _nonnegative(value):
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be nonnegative")
    return parsed


def parse_args(argv):
    root = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iso", default=os.environ.get("KZL_ISO"))
    parser.add_argument("--ppsspp", default=os.environ.get("PPSSPP_HEADLESS"))
    parser.add_argument("--runtime", default=os.environ.get("KZL_D3D12_RUNTIME"))
    legacy_memstick = os.environ.get("KZL_GOLDEN_MEMSTICK")
    parser.add_argument(
        "--ppsspp-memstick-template",
        default=os.environ.get("KZL_GOLDEN_PPSSPP_MEMSTICK", legacy_memstick),
    )
    parser.add_argument(
        "--runtime-memstick-template",
        default=os.environ.get("KZL_GOLDEN_RUNTIME_MEMSTICK", legacy_memstick),
    )
    parser.add_argument(
        "--image",
        default=os.environ.get(
            "KZL_IMAGE", os.path.join(root, "build", "kzl", "gen", "kzl_image.bin")
        ),
    )
    parser.add_argument(
        "--manifest",
        default=os.path.join(root, "tools", "ppsspp", "kzl_golden.frames"),
    )
    parser.add_argument(
        "--padscript",
        default=os.path.join(root, "tools", "ppsspp", "kzl_golden.pad"),
    )
    parser.add_argument(
        "--output",
        default=os.path.join(root, "build", "kzl", "golden_frames"),
    )
    parser.add_argument(
        "--dispatch-misses",
        default=os.path.join(root, "config", "kzl_dispatch_misses.txt"),
    )
    parser.add_argument("--timeout", type=_nonnegative, default=1200)
    parser.add_argument("--warp", action="store_true")
    parser.add_argument("--compare-only", action="store_true")
    parser.add_argument("--threshold", type=_nonnegative, default=64)
    parser.add_argument("--max-different-pixels", type=_nonnegative)
    parser.add_argument(
        "--max-threshold-pixels", type=_nonnegative, default=6000
    )
    parser.add_argument("--max-channel-delta", type=_nonnegative, default=255)
    args = parser.parse_args(argv)
    if args.threshold > 255 or args.max_channel_delta > 255:
        parser.error("channel deltas must be at most 255")
    if not args.compare_only:
        for option in (
            "iso",
            "ppsspp",
            "runtime",
            "ppsspp_memstick_template",
            "runtime_memstick_template",
        ):
            if not getattr(args, option):
                parser.error(
                    f"--{option.replace('_', '-')} is required "
                    "(or set its documented environment variable)"
                )
    return args


def main(argv=None):
    args = parse_args(argv)
    try:
        frames = read_manifest(os.path.abspath(args.manifest))
        if args.compare_only:
            output = os.path.abspath(args.output)
            oracle_dir = os.path.join(output, "ppsspp")
            d3d12_dir = os.path.join(output, "d3d12")
            _validate_capture(oracle_dir, frames)
            _validate_capture(d3d12_dir, frames)
            validate_dispatch_misses(
                os.path.abspath(args.dispatch_misses),
                os.path.join(output, "dispatch_misses.txt"),
            )
        else:
            oracle_dir, d3d12_dir = capture(args, frames)
        compare(args, oracle_dir, d3d12_dir)
    except (GoldenFrameError, OSError) as exc:
        print(f"golden_frames: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
