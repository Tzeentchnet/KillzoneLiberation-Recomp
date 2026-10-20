import os
import tomllib
import unittest


ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)


class ProvenanceTests(unittest.TestCase):
    def test_supported_image_is_not_retail_redump(self):
        with open(os.path.join(ROOT, "config", "kzl.toml"), "rb") as stream:
            config = tomllib.load(stream)
        disc = config["disc"]
        provenance = config["provenance"]
        self.assertEqual(
            provenance["classification"],
            "community-distributed-v1.20",
        )
        self.assertNotEqual(disc["iso_size"], provenance["retail_usa_size"])
        self.assertNotEqual(
            disc["iso_sha1"], provenance["retail_usa_sha1"]
        )
        self.assertEqual(
            provenance["retail_usa_size"] - disc["iso_size"],
            13133824,
        )


if __name__ == "__main__":
    unittest.main()
