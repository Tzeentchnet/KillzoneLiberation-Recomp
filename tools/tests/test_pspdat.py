import importlib.util
import os
import unittest


ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
MODULE_PATH = os.path.join(ROOT, "tools", "kzl", "pspdat.py")
SPEC = importlib.util.spec_from_file_location("pspdat", MODULE_PATH)
pspdat = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pspdat)


def entry(offset):
    return pspdat.Entry(0, "same.bin", False, offset, 16)


class DuplicateSelectionTests(unittest.TestCase):
    def test_selects_extent_nearest_archive_cursor(self):
        copies = [entry(1000), entry(100), entry(600)]
        self.assertEqual(pspdat.nearest_copy(copies, 0).offset, 100)
        self.assertEqual(pspdat.nearest_copy(copies, 580).offset, 600)
        self.assertEqual(pspdat.nearest_copy(copies, 950).offset, 1000)

    def test_tie_preserves_candidate_order(self):
        copies = [entry(1000), entry(600)]
        self.assertIs(pspdat.nearest_copy(copies, 800), copies[0])

    def test_rejects_invalid_selection_inputs(self):
        with self.assertRaisesRegex(ValueError, "at least one"):
            pspdat.nearest_copy([], 0)
        with self.assertRaisesRegex(ValueError, "unsigned 64-bit"):
            pspdat.nearest_copy([entry(100)], -1)


if __name__ == "__main__":
    unittest.main()
