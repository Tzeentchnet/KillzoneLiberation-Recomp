import os
import tomllib
import unittest


ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)


class SvBrowserIoTests(unittest.TestCase):
    def test_http_imports_have_no_data_plane(self):
        with open(
            os.path.join(ROOT, "research", "kzl_imports.toml"), "rb"
        ) as stream:
            imports = tomllib.load(stream)["import"]
        http_nids = {
            entry["nid"] for entry in imports if entry["lib"] == "sceHttp"
        }
        self.assertEqual(
            http_nids,
            {
                0x87797BDD,
                0xAB1ABE07,
                0xD1C8945E,
                0xE4D21302,
                0xF9D8EB63,
            },
        )

    def test_runtime_registers_all_http_lifecycle_imports(self):
        with open(
            os.path.join(
                ROOT, "external", "psp-recomp", "src", "rt", "net.c"
            ),
            "r",
            encoding="ascii",
        ) as stream:
            runtime = stream.read().lower()
        for nid in (
            0x87797BDD,
            0xAB1ABE07,
            0xD1C8945E,
            0xE4D21302,
            0xF9D8EB63,
        ):
            self.assertIn(f"0x{nid:08x}u", runtime)


if __name__ == "__main__":
    unittest.main()
