import importlib.util
import os
import struct
import unittest


ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
MODULE_PATH = os.path.join(ROOT, "tools", "kzl", "homebrew_elf.py")
SPEC = importlib.util.spec_from_file_location("homebrew_elf", MODULE_PATH)
homebrew_elf = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(homebrew_elf)


class HomebrewElfTests(unittest.TestCase):
    def test_minimal_elf_layout(self):
        data = homebrew_elf.build_elf()
        self.assertEqual(data[:4], b"\x7fELF")
        self.assertEqual(struct.unpack_from("<H", data, 18)[0], 8)
        self.assertEqual(struct.unpack_from("<H", data, 16)[0], 0xFFA0)
        self.assertEqual(struct.unpack_from("<I", data, 24)[0], 0)
        self.assertEqual(struct.unpack_from("<II", data, 0x100), (
            0x03E00008, 0x00000000
        ))
        self.assertIn(b".rodata.sceModuleInfo", data)


if __name__ == "__main__":
    unittest.main()
