"""Exercise the boundary with replaceable detectors, mismatches and failures."""

import unittest
from dataclasses import FrozenInstanceError, replace
from unittest.mock import Mock

from core.schema import Classification, DetectionResult
from gateway.detector import (
    CheckedDetector,
    DetectorCompatibilityError,
    DetectorInferenceError,
    DetectorSpec,
)
from stubs.fake_detector import FakeDetector
from stubs.fake_features import STUB_FEATURE_ORDER, STUB_FEATURE_VERSION, fake_features


def spec(**changes):
    return replace(
        DetectorSpec("STUB-NOT-TRAINED", "0.1", STUB_FEATURE_VERSION, STUB_FEATURE_ORDER, 0.5),
        **changes,
    )


class DetectorTests(unittest.TestCase):
    def test_stub_sequence_threshold_equality_and_exhaustion(self):
        detector = CheckedDetector(FakeDetector((0.49, 0.5, 1.0)), spec())
        for ts, expected in zip(
            (0, 5, 10),
            (Classification.NORMAL, Classification.ANOMALOUS, Classification.ANOMALOUS),
            strict=True,
        ):
            result = detector.predict(fake_features("camera", ts))
            self.assertEqual((result.device_id, result.window_ts), ("camera", ts))
            self.assertEqual(result.classification, expected)
        with self.assertRaises(DetectorInferenceError) as caught:
            detector.predict(fake_features("camera", 15))
        self.assertIsInstance(caught.exception.__cause__, StopIteration)

    def test_unrelated_implementation_can_replace_stub(self):
        class AnotherModel:
            def predict(self, vector):
                return DetectionResult(
                    vector.device_id,
                    vector.window_start,
                    "other",
                    "v2",
                    0.25,
                    Classification.NORMAL,
                    0.75,
                )

        detector = CheckedDetector(
            AnotherModel(), spec(model_id="other", model_version="v2", threshold=0.75)
        )
        self.assertEqual(detector.predict(fake_features()).model_id, "other")

    def test_input_rejected_before_backend_call(self):
        base = fake_features()
        invalid = [
            None,
            replace(base, feature_schema_version="wrong"),
            replace(base, feature_order=tuple(reversed(base.feature_order))),
            replace(base, window_start=1, window_end=6),
            replace(base, window_end=10),
        ]
        for vector in invalid:
            with self.subTest(vector=vector):
                backend = Mock()
                detector = CheckedDetector(backend, spec())
                with self.assertRaises(DetectorCompatibilityError):
                    detector.predict(vector)
                backend.predict.assert_not_called()

    def test_output_identity_and_threshold_are_checked(self):
        base = FakeDetector().predict(fake_features())
        invalid = [
            None,
            {"score": 0.1},
            replace(base, device_id="other"),
            replace(base, window_ts=5),
            replace(base, model_id="unexpected"),
            replace(base, model_version="unexpected"),
            replace(base, threshold=0.6),
        ]
        for result in invalid:
            with self.subTest(result=result):
                with self.assertRaises(DetectorCompatibilityError):
                    CheckedDetector(Mock(predict=Mock(return_value=result)), spec()).predict(
                        fake_features()
                    )

    def test_backend_error_is_not_a_normal_score_or_retry(self):
        backend = Mock(predict=Mock(side_effect=RuntimeError("inference failed")))
        with self.assertRaises(DetectorInferenceError) as caught:
            CheckedDetector(backend, spec()).predict(fake_features())
        self.assertIsInstance(caught.exception.__cause__, RuntimeError)
        backend.predict.assert_called_once()

    def test_process_cancellation_propagates(self):
        backend = Mock(predict=Mock(side_effect=KeyboardInterrupt))
        with self.assertRaises(KeyboardInterrupt):
            CheckedDetector(backend, spec()).predict(fake_features())

    def test_spec_is_validated_and_immutable(self):
        for change in (
            {"schema_version": "0.1.0-draft"},
            {"model_id": ""},
            {"feature_order": ()},
            {"feature_order": ("x", "x")},
            {"feature_order": ["x"]},
            {"threshold": float("nan")},
            {"threshold": 1.1},
            {"threshold": True},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                spec(**change)
        with self.assertRaises(FrozenInstanceError):
            spec().threshold = 0.9
        with self.assertRaises(TypeError):
            CheckedDetector(None, spec())


if __name__ == "__main__":
    unittest.main()
