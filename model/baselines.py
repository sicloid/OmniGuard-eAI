"""KAN-18 simple rate-rule baseline: one feature, one threshold, fitted on train only.

V3 requires the Random Forest to be compared with a simple rule under the same
split. If the RF does not beat this rule, that is a result worth reporting.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from core.features import FEATURE_ORDER
from core.schema import FeatureVector


@dataclass(frozen=True)
class RateRule:
    feature: str
    threshold: float

    def score(self, vector: FeatureVector) -> float:
        """1.0 (anomalous) when the feature reaches the threshold, else 0.0."""
        value = vector.values[vector.feature_order.index(self.feature)]
        return 1.0 if value >= self.threshold else 0.0


def fit_rate_rule(
    vectors: Sequence[FeatureVector], labels: Sequence[bool], feature: str = "pkt_count"
) -> RateRule:
    """Pick the observed value that maximises train F1; ties prefer fewer alarms."""
    if feature not in FEATURE_ORDER:
        raise ValueError(f"unknown feature {feature!r}")
    if not vectors or len(vectors) != len(labels):
        raise ValueError("vectors and labels must be nonempty and equal length")
    if all(labels) or not any(labels):
        raise ValueError("fitting a rule needs both classes")
    values = [v.values[v.feature_order.index(feature)] for v in vectors]

    pairs = sorted(zip(values, labels, strict=True), key=lambda p: p[0], reverse=True)
    positives = sum(labels)
    tp = fp = 0
    best: tuple[float, float] | None = None
    i = 0
    while i < len(pairs):
        threshold = pairs[i][0]
        while i < len(pairs) and pairs[i][0] == threshold:
            tp += pairs[i][1]
            fp += not pairs[i][1]
            i += 1
        f1 = 2 * tp / (2 * tp + fp + (positives - tp))
        if best is None or (f1, threshold) > best:
            best = (f1, threshold)
    return RateRule(feature, float(best[1]))
