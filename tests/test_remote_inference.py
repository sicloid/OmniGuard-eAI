import unittest

from core.features import FEATURE_ORDER, FEATURE_SCHEMA_VERSION
from core.schema import Classification, DetectionResult
from gateway.remote_inference import create_app, decode_vector, predict_payload


def payload():
    return {
        "device_id": "device-a",
        "window_start": 100.0,
        "window_end": 105.0,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_order": list(FEATURE_ORDER),
        "values": [0.0] * len(FEATURE_ORDER),
    }


class Detector:
    def predict(self, vector):
        return DetectionResult(
            vector.device_id,
            vector.window_start,
            "model-a",
            "1",
            0.8,
            Classification.ANOMALOUS,
            0.7,
        )


class RemoteInferenceTests(unittest.TestCase):
    def test_exact_feature_vector_contract_is_preserved(self):
        vector = decode_vector(payload())
        self.assertEqual(vector.feature_order, FEATURE_ORDER)
        self.assertEqual(vector.window_end, 105.0)

    def test_unknown_fields_are_rejected(self):
        request = payload()
        request["fallback"] = "normal"
        with self.assertRaisesRegex(ValueError, "exactly"):
            decode_vector(request)

    def test_response_matches_local_detector_result(self):
        result = predict_payload(Detector(), payload())
        self.assertEqual(result["classification"], "ANOMALOUS")
        self.assertEqual(result["score"], 0.8)
        self.assertEqual(result["threshold"], 0.7)

    def test_optional_fastapi_app_exposes_health_and_predict(self):
        try:
            import fastapi  # noqa: F401
        except ImportError:
            self.skipTest("optional FastAPI comparison dependencies are not installed")
        paths = {route.path for route in create_app(Detector()).routes}
        self.assertTrue({"/healthz", "/v1/predict"}.issubset(paths))


if __name__ == "__main__":
    unittest.main()
