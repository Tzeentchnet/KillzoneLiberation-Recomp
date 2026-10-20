import importlib.util
import os
import sys
import tempfile
import unittest


ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
MODULE_PATH = os.path.join(ROOT, "tools", "kzl", "scheduler_trace.py")
SPEC = importlib.util.spec_from_file_location("scheduler_trace", MODULE_PATH)
scheduler_trace = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = scheduler_trace
SPEC.loader.exec_module(scheduler_trace)


class SchedulerTraceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temporary.cleanup()

    def write_points(self, lines):
        path = os.path.join(self.temporary.name, "points.txt")
        with open(path, "w", encoding="ascii", newline="\n") as stream:
            stream.write("\n".join(lines) + "\n")
        return path

    def test_reads_three_ordered_trace_points(self):
        path = self.write_points(
            [
                scheduler_trace.POINTS_HEADER,
                "module_start 0x08804000 10",
                "post_sort 0x088265ec 20",
                "user_main 0x0880410c 30",
            ]
        )
        points = scheduler_trace.read_points(path)
        self.assertEqual([point.name for point in points], [
            "module_start", "post_sort", "user_main"
        ])
        self.assertEqual(points[1].start_pc, 0x088265EC)
        self.assertEqual(points[2].steps, 30)

    def test_rejects_non_module_first_point(self):
        path = self.write_points(
            [
                scheduler_trace.POINTS_HEADER,
                "other 0x08805000 10",
                "post_sort 0x088265ec 20",
                "user_main 0x0880410c 30",
            ]
        )
        with self.assertRaisesRegex(
            scheduler_trace.SchedulerTraceError, "first point must be"
        ):
            scheduler_trace.read_points(path)

    def test_rejects_duplicate_address(self):
        path = self.write_points(
            [
                scheduler_trace.POINTS_HEADER,
                "module_start 0x08804000 10",
                "duplicate 0x08804000 20",
                "user_main 0x0880410c 30",
            ]
        )
        with self.assertRaisesRegex(
            scheduler_trace.SchedulerTraceError, "duplicate point"
        ):
            scheduler_trace.read_points(path)

    def test_counts_steps_without_loading_trace(self):
        path = os.path.join(self.temporary.name, "trace.txt")
        with open(path, "w", encoding="ascii") as stream:
            stream.write("# header\n0 pc=x op=x\n1 pc=x op=x\n")
        self.assertEqual(scheduler_trace.count_steps(path), 2)

    def test_comparable_count_excludes_native_boot_execution(self):
        path = os.path.join(self.temporary.name, "trace.txt")
        with open(path, "w", encoding="ascii") as stream:
            stream.write(
                "# header\n"
                "0 pc=0x08804000 op=0x00000000\n"
                "1 pc=0x08000030 op=0x00000000\n"
                "2 pc=0x09f01c44 op=0x00000000\n"
                "3 pc=0x08804004 op=0x00000000\n"
            )
        self.assertEqual(scheduler_trace.count_comparable_steps(path), 2)

    def test_writes_header_only_seed_trace(self):
        source = os.path.join(self.temporary.name, "source.txt")
        destination = os.path.join(self.temporary.name, "seed.txt")
        with open(source, "w", encoding="ascii") as stream:
            stream.write(
                "# psp-recomp trace v1\n"
                "# init r0=0x00000000\n"
                "# kernel next_uid=0x11d\n"
                "0 pc=0x08804000 op=0x00000000\n"
            )
        scheduler_trace.write_seed_trace(source, destination)
        with open(destination, "r", encoding="ascii") as stream:
            self.assertEqual(
                stream.read(),
                "# psp-recomp trace v1\n"
                "# init r0=0x00000000\n"
                "# kernel next_uid=0x11d\n",
            )


if __name__ == "__main__":
    unittest.main()
