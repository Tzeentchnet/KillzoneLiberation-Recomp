import importlib.util
import os
import tempfile
import unittest


ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
MODULE_PATH = os.path.join(ROOT, "tools", "kzl", "calltargets.py")
SPEC = importlib.util.spec_from_file_location("calltargets", MODULE_PATH)
calltargets = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(calltargets)


class CallTargetTests(unittest.TestCase):
    def test_parse_deduplicates_edges(self):
        content = (
            "# psp-recomp call trace v1 start_pc=0x08804000\n"
            "0x08804000 jal 0x08804100\n"
            "0x08804000 jal 0x08804100\n"
            "0x08804020 jalr 0x09f00000\n"
        )
        with tempfile.NamedTemporaryFile("w", encoding="ascii", newline="\n", delete=False) as stream:
            stream.write(content)
            path = stream.name
        try:
            self.assertEqual(
                calltargets.parse_call_trace(path),
                {
                    (0x08804000, "jal", 0x08804100),
                    (0x08804020, "jalr", 0x09F00000),
                },
            )
        finally:
            os.remove(path)

    def test_parse_rejects_malformed_edges(self):
        with tempfile.NamedTemporaryFile("w", encoding="ascii", newline="\n", delete=False) as stream:
            stream.write("# psp-recomp call trace v1 start_pc=0x08804000\nbad line\n")
            path = stream.name
        try:
            with self.assertRaises(calltargets.TraceFormatError):
                calltargets.parse_call_trace(path)
        finally:
            os.remove(path)

    def test_audit_classifies_missing_and_external_targets(self):
        edges = {
            (0x08804000, "jal", 0x08804100),
            (0x08804010, "jalr", 0x08804200),
            (0x08804020, "jalr", 0x09F00000),
        }
        audit = calltargets.audit_targets(
            edges,
            {0x08804100},
            [(0x08804000, 0x08805000)],
            {0x08804200},
        )
        self.assertEqual(audit["missing"], [])
        self.assertEqual(set(audit["overridden_nonfunctions"]), {0x08804200})
        audit = calltargets.audit_targets(edges, {0x08804100}, [(0x08804000, 0x08805000)])
        self.assertEqual(audit["missing"], [0x08804200])
        self.assertEqual(set(audit["in_module"]), {0x08804100, 0x08804200})
        self.assertEqual(set(audit["external"]), {0x09F00000})


if __name__ == "__main__":
    unittest.main()
