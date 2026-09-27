import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.features import FEATURE_ORDER, FEATURE_SCHEMA_VERSION
from core.schema import FeatureVector
from model.external_benign import ExternalBenignError, prepare_spec
from model.train import LabelledWindow


class ExternalBenignSpecTests(unittest.TestCase):
    def test_prepare_is_device_disjoint_and_does_not_load_model(self):
        windows = [
            LabelledWindow(
                f"device:00:00:00:00:00:{index:02x}",
                FeatureVector(
                    f"00:00:00:00:00:{index:02x}",
                    0.0,
                    5.0,
                    FEATURE_SCHEMA_VERSION,
                    FEATURE_ORDER,
                    tuple(0.0 for _ in FEATURE_ORDER),
                ),
                False,
            )
            for index in range(10)
        ]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pack, manifest, output = (
                root / "windows.jsonl",
                root / "manifest.json",
                root / "spec.json",
            )
            pack.write_text("placeholder")
            import hashlib

            digest = hashlib.sha256(pack.read_bytes()).hexdigest()
            manifest.write_text(json.dumps({"windows_sha256": digest}))
            with patch("model.external_benign.read_windows", return_value=windows):
                first = prepare_spec(
                    pack,
                    manifest,
                    output,
                    model_sha256="a" * 64,
                    metadata_sha256="b" * 64,
                    threshold=0.9,
                )
            output.unlink()
            with patch("model.external_benign.read_windows", return_value=list(reversed(windows))):
                second = prepare_spec(
                    pack,
                    manifest,
                    output,
                    model_sha256="a" * 64,
                    metadata_sha256="b" * 64,
                    threshold=0.9,
                )
            self.assertEqual(first, second)
            self.assertFalse(set(first["split"]["development"]) & set(first["split"]["holdout"]))
            self.assertEqual(len(first["split"]["holdout"]), 2)

    def test_rejects_capture_scoped_group(self):
        window = LabelledWindow(
            "capture-a",
            FeatureVector(
                "device-a",
                0.0,
                5.0,
                FEATURE_SCHEMA_VERSION,
                FEATURE_ORDER,
                tuple(0.0 for _ in FEATURE_ORDER),
            ),
            False,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pack = root / "windows.jsonl"
            manifest = root / "manifest.json"
            pack.write_text("placeholder")
            import hashlib

            manifest.write_text(
                json.dumps({"windows_sha256": hashlib.sha256(pack.read_bytes()).hexdigest()})
            )
            with patch("model.external_benign.read_windows", return_value=[window]):
                with self.assertRaisesRegex(ExternalBenignError, "stable device group"):
                    prepare_spec(
                        pack,
                        manifest,
                        root / "spec.json",
                        model_sha256="a" * 64,
                        metadata_sha256="b" * 64,
                        threshold=0.9,
                    )


if __name__ == "__main__":
    unittest.main()
