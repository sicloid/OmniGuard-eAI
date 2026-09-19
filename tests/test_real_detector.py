"""The real RF adapter uses the pinned artifact and validation threshold."""

import hashlib
import tempfile
import unittest
from pathlib import Path

from core.features import FEATURE_ORDER, FEATURE_SCHEMA_VERSION
from core.schema import Classification, FeatureVector
from gateway.detector import DetectorCompatibilityError, DetectorInferenceError
from gateway.real_detector import RandomForestDetector, load_pinned_rf_detector
from model.artifact import ArtifactIntegrityError, LoadedArtifact, build_metadata


class FakeRF:
    classes_ = (0, 1)

    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def predict_proba(self, matrix):
        self.calls.append(matrix)
        return self.rows


class RealDetectorTests(unittest.TestCase):
    def setUp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "model.joblib"
            path.write_bytes(b"test model bytes")
            self.meta = build_metadata(
                path,
                model_id="rf-test",
                model_version="0.1",
                feature_schema_version=FEATURE_SCHEMA_VERSION,
                feature_order=FEATURE_ORDER,
                threshold=0.8,
                training_manifest_sha256="a" * 64,
            )
        self.vector = FeatureVector(
            "camera",
            100.0,
            105.0,
            FEATURE_SCHEMA_VERSION,
            FEATURE_ORDER,
            tuple(float(i) for i in range(len(FEATURE_ORDER))),
        )

    def test_class_one_score_and_threshold_equality(self):
        for score, expected in ((0.79, Classification.NORMAL), (0.8, Classification.ANOMALOUS)):
            with self.subTest(score=score):
                rf = FakeRF([[1 - score, score]])
                result = RandomForestDetector(LoadedArtifact(self.meta, rf)).predict(self.vector)
                self.assertEqual(result.classification, expected)
                self.assertEqual(
                    (result.device_id, result.window_ts, result.score), ("camera", 100.0, score)
                )
                self.assertEqual(rf.calls, [[list(self.vector.values)]])

    def test_malformed_model_output_is_inference_failure(self):
        for rows in ([], [[0.1]], [[0.1, 0.9], [0.1, 0.9]], [[float("nan"), float("nan")]]):
            with self.subTest(rows=rows):
                rf = RandomForestDetector(LoadedArtifact(self.meta, FakeRF(rows)))
                with self.assertRaises(ValueError):
                    rf.predict(self.vector)

    def test_wrong_class_order_rejected_before_inference(self):
        rf = FakeRF([[0.5, 0.5]])
        rf.classes_ = (1, 0)
        with self.assertRaises(ValueError):
            RandomForestDetector(LoadedArtifact(self.meta, rf))

    def test_pins_and_extractor_catalogue_are_checked(self):
        import joblib

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            rf = FakeRF([[0.2, 0.8]])
            joblib.dump(rf, directory / "model.joblib")
            meta = build_metadata(
                directory / "model.joblib",
                model_id="rf-test",
                model_version="0.1",
                feature_schema_version=FEATURE_SCHEMA_VERSION,
                feature_order=FEATURE_ORDER,
                threshold=0.8,
                training_manifest_sha256="a" * 64,
            )
            (directory / "model.meta.json").write_text(meta.to_json())
            meta_hash = hashlib.sha256((directory / "model.meta.json").read_bytes()).hexdigest()
            detector = load_pinned_rf_detector(
                directory,
                expected_model_sha256=meta.model_sha256,
                expected_metadata_sha256=meta_hash,
            )
            self.assertEqual(detector.predict(self.vector).classification, Classification.ANOMALOUS)
            with self.assertRaises(ArtifactIntegrityError):
                load_pinned_rf_detector(
                    directory,
                    expected_model_sha256="0" * 64,
                    expected_metadata_sha256=meta_hash,
                )
            with self.assertRaises(DetectorCompatibilityError):
                detector.predict(
                    FeatureVector(
                        "camera",
                        100.0,
                        105.0,
                        FEATURE_SCHEMA_VERSION,
                        tuple(reversed(FEATURE_ORDER)),
                        self.vector.values,
                    )
                )
            rf = detector._detector.model
            rf.rows = [[float("nan"), float("nan")]]
            with self.assertRaises(DetectorInferenceError):
                detector.predict(self.vector)


if __name__ == "__main__":
    unittest.main()
