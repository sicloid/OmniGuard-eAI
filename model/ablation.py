"""KAN-20 feature ablation: which catalogue groups earn their per-window cost.

Every candidate set is a subset of `features-1` in catalogue order, never a new
feature. Each set is trained on the KAN-17 train split, its threshold is selected on
validation under the same window-FPR budget as KAN-19, and it is judged on validation
only. The test split is never scored and the ADR-0004 holdout is never read, so the
ablation cannot spend the evaluation that the frozen policy is waiting for.

The compact finalist is chosen by a rule fixed in `ablation_spec.json` before the run:
the fewest features whose validation recall at the budget stays within a declared
tolerance of the full set on every seed. Measured timings are reported beside the
detection result but never used to choose, because they are noisy on a laptop and the
gateway numbers belong to the KAN-42 harness.

Validation both selects each threshold and scores it, so every recall here is
optimistic in the same way for every set. The comparison between sets is the result,
not the absolute recall. Threshold-free average precision is reported as a check that
does not depend on the selected threshold.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from itertools import combinations
from math import fsum
from time import perf_counter

from core.features import FEATURE_ORDER
from model.calibrate import CalibrationError, calibrate_threshold
from model.split import SPLITS, split_by_group
from model.train import LabelledWindow, rf_scores, train_random_forest, window_groups

# data/FEATURE_CATALOG.md: how much (1-4), to how many places (5-7), with which
# protocol mix (8-10), how connections behave (11-14). Zero-based here.
FEATURE_GROUPS: dict[str, tuple[int, ...]] = {
    "volume": (0, 1, 2, 3),
    "destinations": (4, 5, 6),
    "protocol": (7, 8, 9),
    "connection": (10, 11, 12, 13),
}
FULL = "full"
REFERENCE, CANDIDATE, DIAGNOSTIC = "reference", "compact_candidate", "diagnostic"


class AblationError(ValueError):
    """The ablation inputs or rule would let a set be chosen after seeing results."""


@dataclass(frozen=True)
class FeatureSet:
    name: str
    columns: tuple[int, ...]
    role: str

    @property
    def features(self) -> tuple[str, ...]:
        return tuple(FEATURE_ORDER[c] for c in self.columns)

    @property
    def groups(self) -> tuple[str, ...]:
        return tuple(g for g, cols in FEATURE_GROUPS.items() if set(cols) & set(self.columns))


def _union(*names: str) -> tuple[int, ...]:
    return tuple(sorted(c for name in names for c in FEATURE_GROUPS[name]))


def candidate_sets() -> list[FeatureSet]:
    """The declared matrix, in a fixed order: reference, group sets, then diagnostics."""
    everything = tuple(range(len(FEATURE_ORDER)))
    groups = tuple(FEATURE_GROUPS)
    sets = [FeatureSet(FULL, everything, REFERENCE)]
    sets += [FeatureSet(f"only:{g}", _union(g), CANDIDATE) for g in groups]
    sets += [
        FeatureSet(f"pair:{a}+{b}", _union(a, b), CANDIDATE) for a, b in combinations(groups, 2)
    ]
    sets += [
        FeatureSet(f"without:{g}", _union(*(o for o in groups if o != g)), CANDIDATE)
        for g in groups
    ]
    # Leave-one-feature-out shows which single column carries weight. It is not a
    # compact candidate: dropping one column inside a group saves almost nothing,
    # because the group's shared pass still runs (see model.ablation_cost).
    sets += [
        FeatureSet(f"drop:{name}", tuple(c for c in everything if c != i), DIAGNOSTIC)
        for i, name in enumerate(FEATURE_ORDER)
    ]
    return sets


def average_precision(labels: Sequence[bool], scores: Sequence[float]) -> float | None:
    """Threshold-free ranking quality; None when validation has only one class."""
    if all(labels) or not any(labels):
        return None
    from sklearn.metrics import average_precision_score

    return float(average_precision_score([int(v) for v in labels], list(scores)))


@dataclass
class SetResult:
    name: str
    seed: int
    status: str
    split: dict[str, list[str]]
    train_seconds: float
    average_precision: float | None
    policy: dict | None = None
    error: str | None = None
    model: object = field(default=None, repr=False)

    @property
    def recall(self) -> float | None:
        return None if self.policy is None else self.policy["metrics"]["recall"]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "seed": self.seed,
            "status": self.status,
            "split": self.split,
            "train_seconds": round(self.train_seconds, 3),
            "validation_average_precision": self.average_precision,
            "policy": self.policy,
            "error": self.error,
        }


def run_set(
    windows: Sequence[LabelledWindow],
    feature_set: FeatureSet,
    *,
    seed: int,
    max_window_fpr: float,
    objective: str,
    n_estimators: int,
    bootstrap: int,
) -> SetResult:
    """Train on train, select and score on validation. Test rows are never scored."""
    manifest = split_by_group(window_groups(windows), seed=seed)
    membership = {g: name for name in SPLITS for g in getattr(manifest, name)}
    train = [w for w in windows if membership[w.group_id] == "train"]
    validation = [w for w in windows if membership[w.group_id] == "validation"]
    split = {name: list(getattr(manifest, name)) for name in SPLITS}

    started = perf_counter()
    model = train_random_forest(
        train, seed=seed, n_estimators=n_estimators, columns=feature_set.columns
    )
    train_seconds = perf_counter() - started
    labels = [w.malicious for w in validation]
    scores = rf_scores(model, validation, columns=feature_set.columns)
    common = {
        "name": feature_set.name,
        "seed": seed,
        "split": split,
        "train_seconds": train_seconds,
        "average_precision": average_precision(labels, scores),
        "model": model,
    }
    try:
        policy = calibrate_threshold(
            labels,
            scores,
            [w.group_id for w in validation],
            objective=objective,
            max_window_fpr=max_window_fpr,
            bootstrap=bootstrap,
            seed=seed,
        )
    except CalibrationError as exc:
        return SetResult(status="no_threshold", error=str(exc), **common)
    return SetResult(status="calibrated", policy=json.loads(policy.to_json()), **common)


def select_compact(
    sets: Sequence[FeatureSet],
    results: Mapping[str, Sequence[SetResult]],
    *,
    tolerance: float,
) -> dict:
    """Apply the declared rule. Returns the decision and every candidate's verdict.

    A candidate qualifies only if it calibrated on every seed and, on each seed, its
    validation recall at the budget is at least the full set's recall minus
    `tolerance`. Among qualifiers the fewest features win; ties go to the higher mean
    recall, then to the name. If the full set failed to calibrate on any seed there is
    nothing to compare against, and no finalist is named.
    """
    if isinstance(tolerance, bool) or not isinstance(tolerance, int | float):
        raise AblationError("tolerance must be a number")
    if not 0 <= tolerance < 1:
        raise AblationError("tolerance must be in [0, 1)")
    reference = results.get(FULL)
    if not reference or any(r.status != "calibrated" for r in reference):
        return {"status": "no_reference", "finalist": None, "verdicts": {}}
    floor = {r.seed: r.recall - tolerance for r in reference}

    verdicts, qualified = {}, []
    for feature_set in sets:
        if feature_set.role != CANDIDATE:
            continue
        runs = results[feature_set.name]
        if {r.seed for r in runs} != set(floor):
            raise AblationError(f"{feature_set.name} was not run on the reference seeds")
        failed = [r.seed for r in runs if r.status != "calibrated"]
        short = [r.seed for r in runs if r.status == "calibrated" and r.recall < floor[r.seed]]
        verdicts[feature_set.name] = {
            "qualifies": not failed and not short,
            "no_threshold_seeds": failed,
            "below_tolerance_seeds": short,
        }
        if not failed and not short:
            mean = fsum(r.recall for r in runs) / len(runs)
            qualified.append((len(feature_set.columns), -mean, feature_set.name))
    if not qualified:
        return {"status": "no_compact_set", "finalist": None, "verdicts": verdicts}
    return {"status": "selected", "finalist": min(qualified)[2], "verdicts": verdicts}
