import importlib.util
import os
import unittest


ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
MODULE_PATH = os.path.join(ROOT, "tools", "kzl", "version_match.py")
SPEC = importlib.util.spec_from_file_location("version_match", MODULE_PATH)
version_match = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(version_match)


@unittest.skipIf(version_match.CityHash64 is None, "optional cityhash unavailable")
class VersionMatchTests(unittest.TestCase):
    def test_matches_unique_normalized_function(self):
        image_a = bytearray(32)
        image_b = bytearray(32)
        image_a[:8] = bytes.fromhex("341284240800e003")
        image_b[:8] = bytes.fromhex("785684240800e003")
        functions = [{
            "address": version_match.BASE,
            "end": version_match.BASE + 7,
            "name": "FUN_test",
        }]
        first, _ = version_match.build_index(image_a, functions)
        second, _ = version_match.build_index(image_b, functions)
        matches = version_match.unique_matches(first, second)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["size"], 8)

    def test_ambiguous_hash_is_not_matched(self):
        function = {
            "address": version_match.BASE,
            "end": version_match.BASE + 3,
            "name": "FUN_test",
        }
        key = (123, 4)
        matches = version_match.unique_matches(
            {key: [function, function]}, {key: [function]}
        )
        self.assertEqual(matches, [])


if __name__ == "__main__":
    unittest.main()
