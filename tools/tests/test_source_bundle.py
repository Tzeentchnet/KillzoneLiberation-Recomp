import hashlib
import importlib.util
import os
import tempfile
import unittest
import zipfile


ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
MODULE_PATH = os.path.join(ROOT, "tools", "kzl", "source_bundle.py")
SPEC = importlib.util.spec_from_file_location("source_bundle", MODULE_PATH)
source_bundle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(source_bundle)


class SourceBundleTests(unittest.TestCase):
    def test_safe_version(self):
        self.assertEqual(source_bundle.safe_version("v1.0 beta"), "v1.0-beta")
        with self.assertRaises(source_bundle.BundleError):
            source_bundle.safe_version("...")

    def test_manifest_records_both_commits(self):
        manifest = source_bundle._manifest("v1", "a" * 40, "b" * 40)
        self.assertIn("Parent commit: " + "a" * 40, manifest)
        self.assertIn("external/psp-recomp commit: " + "b" * 40, manifest)
        self.assertIn("contains no", manifest)

    def test_zip_is_deterministic_and_prefixed(self):
        with tempfile.TemporaryDirectory() as temporary:
            top = os.path.join(temporary, "bundle")
            os.makedirs(os.path.join(top, "nested"))
            with open(os.path.join(top, "z.txt"), "wb") as stream:
                stream.write(b"last")
            with open(os.path.join(top, "nested", "a.txt"), "wb") as stream:
                stream.write(b"first")
            first = os.path.join(temporary, "first.zip")
            second = os.path.join(temporary, "second.zip")
            source_bundle.write_deterministic_zip(top, first)
            source_bundle.write_deterministic_zip(top, second)
            with open(first, "rb") as stream:
                first_hash = hashlib.sha256(stream.read()).digest()
            with open(second, "rb") as stream:
                second_hash = hashlib.sha256(stream.read()).digest()
            self.assertEqual(
                first_hash,
                second_hash,
            )
            with zipfile.ZipFile(first) as archive:
                self.assertEqual(
                    archive.namelist(),
                    ["bundle/nested/a.txt", "bundle/z.txt"],
                )
                self.assertEqual(
                    archive.getinfo("bundle/z.txt").date_time,
                    (1980, 1, 1, 0, 0, 0),
                )


if __name__ == "__main__":
    unittest.main()
