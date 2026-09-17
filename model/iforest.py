"""KAN-22 Isolation Forest, offline research only [stretch].

The forest is fitted on **benign training windows only**: it learns what the training
device's normal traffic looks like, and anything unlike it scores high. Malicious
training windows are discarded, never used as negatives.

The score is `-score_samples`, the Isolation Forest anomaly score in (0, 1]. Higher
means more anomalous. It is **not a probability**, it is not comparable with the Random
Forest score, and 0.5 carries no meaning for it. SCHEMA.md requires an explicit score
contract before an Isolation Forest can reach the runtime, so nothing here writes a model
artifact or a `DetectionResult`.
"""

from collections.abc import Sequence

from model.train import LabelledWindow, TrainingError, feature_matrix


def train_isolation_forest(
    windows: Sequence[LabelledWindow], *, seed: int, n_estimators: int = 200
):
    """Fit on the benign windows among `windows`; malicious ones are dropped."""
    benign = [w for w in windows if not w.malicious]
    if not benign:
        raise TrainingError("an Isolation Forest needs benign training windows")
    from sklearn.ensemble import IsolationForest

    model = IsolationForest(
        n_estimators=n_estimators, contamination="auto", random_state=seed, n_jobs=1
    )
    model.fit(feature_matrix(benign))
    return model


def anomaly_scores(model, windows: Sequence[LabelledWindow]) -> list[float]:
    """Anomaly score in (0, 1] per window; higher is more anomalous. Not a probability."""
    scores = [-float(s) for s in model.score_samples(feature_matrix(windows))]
    if any(not 0 < s <= 1 for s in scores):
        raise TrainingError("Isolation Forest anomaly scores must lie in (0, 1]")
    return scores
