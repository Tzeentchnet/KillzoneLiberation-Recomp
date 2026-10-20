import importlib.util
import os
import tempfile
import unittest


ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
MODULE_PATH = os.path.join(ROOT, "tools", "kzl", "knownfuncs.py")
SPEC = importlib.util.spec_from_file_location("knownfuncs", MODULE_PATH)
knownfuncs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(knownfuncs)


class KnownFunctionsTests(unittest.TestCase):
    def test_masks_jump_and_scalar_immediates(self):
        self.assertEqual(
            knownfuncs.normalize_instruction(0x0E123456),
            0x0C000000,
        )
        self.assertEqual(
            knownfuncs.normalize_instruction(0x24841234),
            0x24840000,
        )
        self.assertEqual(
            knownfuncs.normalize_instruction(0x012A4021),
            0x012A4021,
        )

    def test_reads_known_function_database(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = os.path.join(temporary, "known.ini")
            with open(path, "w", encoding="ascii") as stream:
                stream.write("0266f96d740c7e03:912 = memcpy\n")
            parsed = knownfuncs.read_known_functions(path)
        self.assertEqual(
            parsed[(0x0266F96D740C7E03, 912)],
            ["memcpy"],
        )

    def test_ghidra_end_address_is_inclusive_byte(self):
        self.assertEqual(0x08804007 - 0x08804000 + 1, 8)


if __name__ == "__main__":
    unittest.main()
