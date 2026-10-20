import importlib.util
import os
import struct
import unittest


ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
MODULE_PATH = os.path.join(ROOT, "tools", "kzl", "class_recovery.py")
SPEC = importlib.util.spec_from_file_location("class_recovery", MODULE_PATH)
class_recovery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(class_recovery)


class ClassRecoveryTests(unittest.TestCase):
    def test_method_name_sanitization(self):
        match = class_recovery.METHOD_PATTERN.search(
            "HwSoundSystemPSP::ClaimVoice : voice %d"
        )
        self.assertEqual(
            class_recovery.sanitize(match.group(1)),
            "HwSoundSystemPSP_ClaimVoice",
        )

    def test_finds_sn_pair_vtable(self):
        old_ranges = class_recovery.DATA_RANGES
        try:
            class_recovery.DATA_RANGES = (
                (class_recovery.BASE, class_recovery.BASE + 32, "test"),
            )
            image = bytearray(32)
            entries = ((0, 0), (0, 0x08805000), (4, 0x08805010), (0, 0x08805020))
            for index, entry in enumerate(entries):
                struct.pack_into("<II", image, index * 8, *entry)
            tables = class_recovery.scan_vtables(
                image, {0x08805000, 0x08805010, 0x08805020}
            )
        finally:
            class_recovery.DATA_RANGES = old_ranges
        self.assertIn(class_recovery.BASE, tables)
        self.assertEqual(len(tables[class_recovery.BASE][1]), 4)


if __name__ == "__main__":
    unittest.main()
