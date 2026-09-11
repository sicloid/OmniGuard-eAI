"""KAN-19 threshold calibration on validation data only, frozen before the test split.

The threshold is chosen from validation scores under a false-alarm budget, written
to a hashed policy file, and applied to the test split exactly as recorded. Tuning
after seeing test results is what this module exists to prevent, so `calibrate_threshold`
refuses `selected_on="test"` and `apply_frozen_policy` never re-optimises.

Window FPR is a proxy for user harm. False quarantine per device-hour and benign
blocked seconds are measured later in the live experiments (KAN-51/52).
"""

import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from math import isfinite
from pathlib import Path

from model.evaluate import Metrics, evaluate

POLICY_FILENAME = "threshold.policy.json"
OBJECTIVES = ("max_recall_at_fpr", "max_f1")


class CalibrationError(ValueError):
    """No defensible threshold can be selected under the requested rule."""


@dataclass(frozen=True)
class ThresholdPolicy:
    threshold: float
    objective: str
    max_window_fpr: float | None
    selected_on: str
    candidates: int
    metrics: Metrics

    def to_json(self) -> str:
        document = asdict(self) | {"metrics": asdict(self.metrics)}
        return json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n"

    def sha256(self) -> str:
        return hashlib.sha256(self.to_json().encode()).hexdigest()


def calibrate_threshold(
    labels: Sequence[bool],
    scores: Sequence[float],
    groups: Sequence[str],
    *,
    objective: str = "max_recall_at_fpr",
    max_window_fpr: float = 0.01,
    selected_on: str = "validation",
    bootstrap: int = 0,
    seed: int = 0,
) -> ThresholdPolicy:
    if objective not in OBJECTIVES:
        raise CalibrationError(f"objective must be one of {OBJECTIVES}")
    if selected_on == "test":
        raise CalibrationError("thresholds are never selected on the test split")
    budget: float | None = None
    if objective == "max_recall_at_fpr":
        if (
            isinstance(max_window_fpr, bool)
            or not isinstance(max_window_fpr, int | float)
            or not isfinite(max_window_fpr)
            or not 0 <= max_window_fpr <= 1
        ):
            raise CalibrationError("max_window_fpr must be finite and in [0, 1]")
        budget = float(max_window_fpr)

    candidates = sorted(set(scores))
    # Validates the inputs (raising EvaluationError) before any candidate search.
    evaluate(labels, scores, groups, candidates[0] if candidates else 0.0, bootstrap=0)

    best: tuple[float, float] | None = None
    for threshold in candidates:
        metrics = evaluate(labels, scores, groups, threshold, bootstrap=0)
        if budget is None:
            score = metrics.f1
        else:
            if metrics.fpr is None or metrics.fpr > budget:
                continue
            score = metrics.recall
        key = (score if score is not None else 0.0, threshold)
        if best is None or key > best:
            best = key
    if best is None:
        raise CalibrationError(
            f"no candidate threshold keeps window FPR at or below {budget}; "
            "report this instead of relaxing the budget silently"
        )

    threshold = best[1]
    return ThresholdPolicy(
        threshold=threshold,
        objective=objective,
        max_window_fpr=budget,
        selected_on=selected_on,
        candidates=len(candidates),
        metrics=evaluate(labels, scores, groups, threshold, bootstrap=bootstrap, seed=seed),
    )


def write_policy(policy: ThresholdPolicy, out_dir: Path) -> Path:
    path = Path(out_dir) / POLICY_FILENAME
    path.write_text(policy.to_json(), encoding="utf-8")
    return path


def read_policy(path: Path) -> ThresholdPolicy:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    metrics = document.pop("metrics")
    for name in ("recall_ci", "fpr_ci"):
        if metrics[name] is not None:
            metrics[name] = tuple(metrics[name])
    return ThresholdPolicy(metrics=Metrics(**metrics), **document)


def apply_frozen_policy(
    policy: ThresholdPolicy,
    labels: Sequence[bool],
    scores: Sequence[float],
    groups: Sequence[str],
    *,
    bootstrap: int = 1000,
    seed: int = 0,
) -> Metrics:
    """Score held-out data at the frozen threshold. Run once; never re-tune afterwards."""
    return evaluate(labels, scores, groups, policy.threshold, bootstrap=bootstrap, seed=seed)
