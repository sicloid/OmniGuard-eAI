import json
import tempfile
import unittest
from pathlib import Path

from model.runtime_profile import RuntimeProfileError, field, load_profile


class RuntimeProfileTests(unittest.TestCase):
    def test_committed_profile_pins_the_accepted_candidate(self):
        profile = load_profile(Path("model/runtime_profile.json"))
        self.assertEqual(profile["profile_id"], "competition-demo-20260928")
        self.assertEqual(
            field(profile, "model_sha256"),
            "5c8909d717e79ca30b667140894ef0a1661835cf298437b956fbe5e95b5f843a",
        )
        self.assertEqual(
            field(profile, "metadata_sha256"),
            "3e0246b0c899d88eefe8fe99d348ad628b36bec95b9e7e003b3a942134e12c29",
        )
        self.assertEqual(field(profile, "n"), "2")
        self.assertEqual(field(profile, "lease_seconds"), "300")
        self.assertTrue(profile["selection"]["limitations"])

    def test_malformed_profile_is_rejected(self):
        profile = json.loads(Path("model/runtime_profile.json").read_text())
        profile["artifact"]["model_sha256"] = "not-a-hash"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            path.write_text(json.dumps(profile))
            with self.assertRaisesRegex(RuntimeProfileError, "model_sha256"):
                load_profile(path)

    def test_unknown_field_is_rejected(self):
        profile = load_profile(Path("model/runtime_profile.json"))
        with self.assertRaisesRegex(RuntimeProfileError, "unsupported"):
            field(profile, "missing")


if __name__ == "__main__":
    unittest.main()
