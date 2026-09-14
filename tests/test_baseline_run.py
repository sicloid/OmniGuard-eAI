import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from core.features import FEATURE_SCHEMA_VERSION
from model.baseline_run import PackIntegrityError, run, verify_pack


class VerifyPackTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.pack = self.dir / "windows.jsonl"
        self.pack.write_bytes(b'{"label": "benign"}\n')
        self.write_manifest()

    def write_manifest(self, **changes):
        document = {
            "windows_file": "windows.jsonl",
            "windows_sha256": hashlib.sha256(self.pack.read_bytes()).hexdigest(),
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
        } | changes
        (self.dir / "manifest.json").write_text(json.dumps(document), encoding="utf-8")

    def test_matching_pack_is_bound_to_pack_and_manifest_hashes(self):
        provenance = verify_pack(self.pack)
        manifest_bytes = (self.dir / "manifest.json").read_bytes()
        self.assertEqual(
            provenance.windows_sha256, hashlib.sha256(self.pack.read_bytes()).hexdigest()
        )
        self.assertEqual(provenance.manifest_sha256, hashlib.sha256(manifest_bytes).hexdigest())
        self.assertEqual(provenance.feature_schema_version, FEATURE_SCHEMA_VERSION)

    def test_windows_that_differ_from_the_manifest_are_rejected(self):
        with open(self.pack, "ab") as handle:
            handle.write(b'{"label": "malicious"}\n')
        with self.assertRaises(PackIntegrityError):
            verify_pack(self.pack)

    def test_foreign_wrong_catalogue_or_missing_manifest_is_rejected(self):
        for changes in (
            {"windows_file": "other.jsonl"},
            {"feature_schema_version": "stub-0.1"},
            {"windows_sha256": None},
        ):
            with self.subTest(changes=changes):
                self.write_manifest(**changes)
                with self.assertRaises(PackIntegrityError):
                    verify_pack(self.pack)
        (self.dir / "manifest.json").unlink()
        with self.assertRaises(PackIntegrityError):
            verify_pack(self.pack)

    def test_run_refuses_a_mismatched_pack_before_training(self):
        self.write_manifest(windows_sha256="0" * 64)
        with self.assertRaises(PackIntegrityError):
            run(self.pack, self.dir / "out", seeds=[1], bootstrap=0, trees=1)
        self.assertFalse((self.dir / "out").exists())


if __name__ == "__main__":
    unittest.main()
