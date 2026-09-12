"""KAN-18 window-level detection metrics with capture-group bootstrap intervals.

Predictions follow DetectionResult semantics: `score >= threshold` is ANOMALOUS.
Undefined rates are None, never 0. Intervals resample whole capture groups,
because windows of one capture are not independent observations.
"""

import random
from collections.abc import Sequence
from dataclasses import dataclass
from math import ceil, isfinite


class EvaluationError(ValueError):
    """Inputs cannot be scored honestly."""


@dataclass(frozen=True)
class Metrics:
    threshold: float
    windows: int
    malicious_groups: int
    benign_groups: int
    tp: int
    fp: int
    tn: int
    fn: int
    precision: float | None
    recall: float | None
    f1: float | None
    fpr: float | None
    recall_ci: tuple[float, float] | None
    fpr_ci: tuple[float, float] | None


def _rate(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else numerator / denominator


def _counts(labels, predicted, indices) -> tuple[int, int, int, int]:
    tp = fp = tn = fn = 0
    for i in indices:
        if labels[i]:
            tp += predicted[i]
            fn += not predicted[i]
        else:
            fp += predicted[i]
            tn += not predicted[i]
    return tp, fp, tn, fn


def _interval(values: list[float], level: float = 0.95) -> tuple[float, float] | None:
    if not values:
        return None
    ordered = sorted(values)
    last = len(ordered) - 1
    return ordered[int((1 - level) / 2 * last)], ordered[ceil((1 + level) / 2 * last)]


def _probability(value, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise EvaluationError(f"{field} must be numeric")
    if not isfinite(value) or not 0 <= value <= 1:
        raise EvaluationError(f"{field} must be finite and in [0, 1]")


def evaluate(
    labels: Sequence[bool],
    scores: Sequence[float],
    groups: Sequence[str],
    threshold: float,
    *,
    bootstrap: int = 1000,
    seed: int = 0,
) -> Metrics:
    n = len(labels)
    if n == 0 or len(scores) != n or len(groups) != n:
        raise EvaluationError("labels, scores and groups must be nonempty and equal length")
    _probability(threshold, "threshold")
    for score in scores:
        _probability(score, "score")
    if any(type(label) is not bool for label in labels):
        raise EvaluationError("labels must be bool")
    if any(not isinstance(g, str) or not g.strip() for g in groups):
        raise EvaluationError("groups must be nonempty text")
    if type(bootstrap) is not int or bootstrap < 0:
        raise EvaluationError("bootstrap must be a non-negative integer")

    predicted = [score >= threshold for score in scores]
    tp, fp, tn, fn = _counts(labels, predicted, range(n))
    by_group: dict[str, list[int]] = {}
    for i, group in enumerate(groups):
        by_group.setdefault(group, []).append(i)
    malicious_groups = sum(any(labels[i] for i in idx) for idx in by_group.values())

    recall_ci = fpr_ci = None
    if bootstrap:
        rng = random.Random(seed)
        ids = sorted(by_group)
        recalls, fprs = [], []
        for _ in range(bootstrap):
            sample = [ids[rng.randrange(len(ids))] for _ in ids]
            b_tp, b_fp, b_tn, b_fn = _counts(
                labels, predicted, (i for g in sample for i in by_group[g])
            )
            if (recall := _rate(b_tp, b_tp + b_fn)) is not None:
                recalls.append(recall)
            if (fpr := _rate(b_fp, b_fp + b_tn)) is not None:
                fprs.append(fpr)
        recall_ci, fpr_ci = _interval(recalls), _interval(fprs)

    return Metrics(
        threshold=threshold,
        windows=n,
        malicious_groups=malicious_groups,
        benign_groups=len(by_group) - malicious_groups,
        tp=tp,
        fp=fp,
        tn=tn,
        fn=fn,
        precision=_rate(tp, tp + fp),
        recall=_rate(tp, tp + fn),
        f1=_rate(2 * tp, 2 * tp + fp + fn),
        fpr=_rate(fp, fp + tn),
        recall_ci=recall_ci,
        fpr_ci=fpr_ci,
    )
