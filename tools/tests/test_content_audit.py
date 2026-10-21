import hashlib
import importlib.util
import os
import tempfile
import unittest


ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
MODULE_PATH = os.path.join(ROOT, "tools", "kzl", "content_audit.py")
SPEC = importlib.util.spec_from_file_location("content_audit", MODULE_PATH)
content_audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(content_audit)


class ContentAuditTests(unittest.TestCase):
    def audit_bytes(self, display, data, forbidden=()):
        with tempfile.NamedTemporaryFile(delete=False) as stream:
            stream.write(data)
            path = stream.name
        try:
            return content_audit.audit_file(display, path, set(forbidden))
        finally:
            os.remove(path)

    def test_rejects_paths_and_signatures(self):
        self.assertIn(
            "prohibited game-container extension .iso",
            self.audit_bytes("renamed.iso", b"not an iso"),
        )
        self.assertIn(
            "generated game code/image",
            self.audit_bytes("build/kzl_recomp_001.c", b"source"),
        )
        self.assertIn(
            "tracked save/memory-stick data",
            self.audit_bytes("memstick/PSP/SAVEDATA/save.bin", b"save"),
        )
        self.assertIn(
            "encrypted PSP executable signature",
            self.audit_bytes("payload.bin", b"~PSP" + bytes(32)),
        )
        iso = bytearray(0x8006)
        iso[0x8001:0x8006] = b"CD001"
        self.assertIn(
            "ISO9660 disc-image signature",
            self.audit_bytes("renamed.payload", iso),
        )

    def test_rejects_renamed_known_hash(self):
        data = b"known game payload"
        digest = hashlib.sha1(data).hexdigest()
        issues = self.audit_bytes("innocent.txt", data, {digest})
        self.assertTrue(any("known game payload SHA-1" in issue for issue in issues))

    def test_allows_vfpu_data_and_rejects_unknown_fonts(self):
        self.assertEqual(
            self.audit_bytes(
                "external/psp-recomp/assets/vfpu/table.dat", b"table"
            ),
            [],
        )
        self.assertIn(
            "unapproved tracked PGF font",
            self.audit_bytes("external/psp-recomp/font/other.pgf", b"font"),
        )


if __name__ == "__main__":
    unittest.main()
