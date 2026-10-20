import csv
import importlib.util
import os
import tempfile
import unittest


ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
MODULE_PATH = os.path.join(ROOT, "tools", "kzl", "ghidra_symbols.py")
SPEC = importlib.util.spec_from_file_location("ghidra_symbols", MODULE_PATH)
ghidra_symbols = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ghidra_symbols)


class GhidraSymbolTests(unittest.TestCase):
    def test_canonical_imports_all_have_names(self):
        symbols = ghidra_symbols.collect_symbols(ROOT)
        self.assertEqual(symbols[0], (0x08804000, "module_start", "export"))
        self.assertEqual(len(symbols), 302)
        self.assertIn(
            (0x08D8EB78, "sceHttpInit", "import:sceHttp"),
            symbols,
        )

    def test_writes_stable_csv(self):
        symbols = ghidra_symbols.collect_symbols(ROOT)
        with tempfile.TemporaryDirectory() as temporary:
            path = os.path.join(temporary, "symbols.csv")
            ghidra_symbols.write_symbols(path, symbols)
            with open(path, "r", encoding="ascii", newline="") as stream:
                rows = list(csv.DictReader(stream))
        self.assertEqual(rows[0]["address"], "0x08804000")
        self.assertEqual(rows[-1]["source"].split(":", 1)[0], "import")


if __name__ == "__main__":
    unittest.main()
