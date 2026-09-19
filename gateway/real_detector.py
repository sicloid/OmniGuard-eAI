"""Pinned Random Forest inference at the existing detector boundary.

Only a trusted, locally produced artifact may be passed to this module.  The
artifact loader checks both deployment pins before deserializing joblib bytes.
"""

from pathlib import Path

from core.features import FEATURE_ORDER, FEATURE_SCHEMA_VERSION
from core.schema import Classification, DetectionResult, FeatureVector, probability
from gateway.detector import CheckedDetector, DetectorSpec
from model.artifact import LoadedArtifact, load_model


class RandomForestDetector:
    """Translate the trained model's class-1 score into the frozen 0.1.0 result."""

    def __init__(self, artifact: LoadedArtifact):
        meta = artifact.metadata
        model = artifact.model
        if tuple(getattr(model, "classes_", ())) != (0, 1):
            raise ValueError("RF artifact must have classes [0, 1] in that order")
        if not callable(getattr(model, "predict_proba", None)):
            raise ValueError("RF artifact must implement predict_proba")
        if getattr(model, "n_features_in_", None) != len(meta.feature_order):
            raise ValueError("RF artifact feature width differs from its metadata")
        columns = getattr(model, "omniguard_columns", None)
        if columns is not None and tuple(columns) != tuple(range(len(FEATURE_ORDER))):
            raise ValueError("RF ablation artifact cannot serve the full feature catalogue")
        self.model = model
        self.meta = meta

    def predict(self, vector: FeatureVector) -> DetectionResult:
        rows = self.model.predict_proba([list(vector.values)])
        if len(rows) != 1 or len(rows[0]) != 2:
            raise ValueError("RF must return one two-class probability row")
        score = float(rows[0][1])
        probability(score, "RF class-1 score")
        return DetectionResult(
            vector.device_id,
            vector.window_start,
            self.meta.model_id,
            self.meta.model_version,
            score,
            Classification.ANOMALOUS if score >= self.meta.threshold else Classification.NORMAL,
            self.meta.threshold,
        )


def load_pinned_rf_detector(
    artifact_dir: Path,
    *,
    expected_model_sha256: str,
    expected_metadata_sha256: str,
) -> CheckedDetector:
    """Verify the complete artifact and bind it to the shared extractor catalog."""
    artifact = load_model(
        artifact_dir,
        expected_model_sha256=expected_model_sha256,
        expected_metadata_sha256=expected_metadata_sha256,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        feature_order=FEATURE_ORDER,
    )
    meta = artifact.metadata
    return CheckedDetector(
        RandomForestDetector(artifact),
        DetectorSpec(
            meta.model_id,
            meta.model_version,
            meta.feature_schema_version,
            meta.feature_order,
            meta.threshold,
        ),
    )
