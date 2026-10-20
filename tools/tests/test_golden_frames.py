import importlib.util
import os
import sys
import tempfile
import unittest


ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
MODULE_PATH = os.path.join(ROOT, "tools", "kzl", "golden_frames.py")
SPEC = importlib.util.spec_from_file_location("golden_frames", MODULE_PATH)
golden_frames = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = golden_frames
SPEC.loader.exec_module(golden_frames)


class GoldenFrameTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp.cleanup()

    def write_manifest(self, mutate=None):
        scenes = ["boot", "menu", "cutscene", "gameplay", "hud"]
        lines = [golden_frames.MANIFEST_HEADER]
        for index in range(golden_frames.FRAME_COUNT):
            lines.append(
                f"{index + 1} {index + 101} "
                f"frame_{index:02d}.ppm {scenes[index // 10]}"
            )
        if mutate:
            mutate(lines)
        path = os.path.join(self.temp.name, "frames.txt")
        with open(path, "w", encoding="ascii", newline="\n") as stream:
            stream.write("\n".join(lines) + "\n")
        return path

    def write_padscript(self, lines=None):
        if lines is None:
            lines = [
                golden_frames.PADSCRIPT_HEADER,
                "10 20 0008 2 3",
                "30 50 4000 4 5",
            ]
        path = os.path.join(self.temp.name, "input.pad")
        with open(path, "w", encoding="ascii", newline="\n") as stream:
            stream.write("\n".join(lines) + "\n")
        return path

    def test_manifest_requires_50_ordered_frames_across_all_scenes(self):
        frames = golden_frames.read_manifest(self.write_manifest())

        self.assertEqual(len(frames), golden_frames.FRAME_COUNT)
        self.assertEqual(frames[0].ppsspp_present, 1)
        self.assertEqual(frames[0].runtime_present, 101)
        self.assertEqual(frames[-1].scene, "hud")

    def test_manifest_rejects_nonincreasing_present_indices(self):
        def duplicate_present(lines):
            lines[2] = lines[2].replace("2 102 ", "1 102 ", 1)

        with self.assertRaisesRegex(
            golden_frames.GoldenFrameError, "indices must increase"
        ):
            golden_frames.read_manifest(self.write_manifest(duplicate_present))

    def test_manifest_rejects_nonincreasing_runtime_present_indices(self):
        def duplicate_present(lines):
            lines[2] = lines[2].replace("2 102 ", "2 101 ", 1)

        with self.assertRaisesRegex(
            golden_frames.GoldenFrameError, "indices must increase"
        ):
            golden_frames.read_manifest(self.write_manifest(duplicate_present))

    def test_manifest_rejects_missing_scene(self):
        def remove_hud(lines):
            for index, line in enumerate(lines):
                lines[index] = line.replace(" hud", " gameplay")

        with self.assertRaisesRegex(
            golden_frames.GoldenFrameError, "missing required scenes: hud"
        ):
            golden_frames.read_manifest(self.write_manifest(remove_hud))

    def test_padscript_supports_backend_specific_timing(self):
        events = golden_frames.read_padscript(self.write_padscript())

        self.assertEqual(events[0].ppsspp_vblank, 10)
        self.assertEqual(events[0].runtime_present, 20)
        self.assertEqual(events[1].mask, 0x4000)
        self.assertEqual(events[1].runtime_width, 5)

    def test_padscript_rejects_nonincreasing_backend_timing(self):
        path = self.write_padscript(
            [
                golden_frames.PADSCRIPT_HEADER,
                "10 20 0008 2 3",
                "30 20 4000 4 5",
            ]
        )
        with self.assertRaisesRegex(
            golden_frames.GoldenFrameError, "presentation indices must increase"
        ):
            golden_frames.read_padscript(path)

    def test_comparison_defaults_allow_only_bounded_high_deltas(self):
        args = golden_frames.parse_args(["--compare-only"])

        self.assertEqual(args.threshold, 64)
        self.assertEqual(args.max_threshold_pixels, 6000)
        self.assertEqual(args.max_channel_delta, 255)

    def test_dispatch_miss_regression_accepts_empty_log(self):
        expected = os.path.join(self.temp.name, "expected.txt")
        with open(expected, "w", encoding="ascii") as stream:
            stream.write(golden_frames.DISPATCH_MISS_HEADER + "\n")
        golden_frames.validate_dispatch_misses(
            expected, os.path.join(self.temp.name, "missing-actual.txt")
        )

    def test_dispatch_miss_regression_rejects_new_target(self):
        expected = os.path.join(self.temp.name, "expected.txt")
        actual = os.path.join(self.temp.name, "actual.txt")
        with open(expected, "w", encoding="ascii") as stream:
            stream.write(golden_frames.DISPATCH_MISS_HEADER + "\n")
        with open(actual, "w", encoding="ascii") as stream:
            stream.write("# psp-recomp interpreter misses v1\n0x08812340\n")
        with self.assertRaisesRegex(
            golden_frames.GoldenFrameError, "unexpected 0x08812340"
        ):
            golden_frames.validate_dispatch_misses(expected, actual)

    def test_dispatch_miss_regression_rejects_duplicate(self):
        actual = os.path.join(self.temp.name, "actual.txt")
        with open(actual, "w", encoding="ascii") as stream:
            stream.write("0x08812340\n0x08812340\n")
        with self.assertRaisesRegex(
            golden_frames.GoldenFrameError, "duplicate dispatch-miss"
        ):
            golden_frames.read_dispatch_misses(actual)

    def test_capture_validation_requires_exact_files_and_marker(self):
        frames = golden_frames.read_manifest(self.write_manifest())
        capture_dir = os.path.join(self.temp.name, "capture")
        os.mkdir(capture_dir)
        for frame in frames:
            open(os.path.join(capture_dir, frame.name), "wb").close()
        with open(
            os.path.join(capture_dir, "capture.complete"),
            "w",
            encoding="ascii",
            newline="\n",
        ) as stream:
            stream.write(f"{golden_frames.FRAME_COUNT}\n")

        golden_frames._validate_capture(capture_dir, frames)
        open(os.path.join(capture_dir, "unexpected.ppm"), "wb").close()
        with self.assertRaisesRegex(
            golden_frames.GoldenFrameError, "unexpected: unexpected.ppm"
        ):
            golden_frames._validate_capture(capture_dir, frames)


if __name__ == "__main__":
    unittest.main()
