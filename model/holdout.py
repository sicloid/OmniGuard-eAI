"""KAN-21 unseen malware-family holdout, reported apart from the KAN-18 baseline.

Every fold keeps one malware family out of training and validation entirely. The
Random Forest trains on the remaining families plus benign captures, KAN-19 selects
the threshold on validation under a window-FPR budget, and only then is the frozen
threshold applied to the held-out family and to a benign capture seen in neither.

A family is one or more captures of the same malware. When a family has a single
capture, "unseen family" is also an unseen capture, device and network, and a result
cannot separate family novelty from those confounds. Folds rotate which family
validates and which benign capture is tested, so both effects stay visible instead
of being averaged away.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass

from model.calibrate import (
    CalibrationError,
    ThresholdPolicy,
    apply_frozen_policy,
    calibrate_threshold,
)
from model.evaluate import Metrics, evaluate
from model.split import SPLITS, WindowGroup
from model.train import LabelledWindow, rf_scores, train_random_forest

METHOD = "leave-one-family-out-v1"
MIN_FAMILIES = 3
MIN_BENIGN_GROUPS = 3
REFERENCE_THRESHOLD = 0.5


class HoldoutError(ValueError):
    """The groups cannot support an unseen-family evaluation without leakage."""


@dataclass(frozen=True)
class HoldoutFold:
    held_out_family: str
    validation_family: str
    benign_test: str
    train: tuple[str, ...]
    validation: tuple[str, ...]
    test: tuple[str, ...]

    @property
    def held_out_groups(self) -> tuple[str, ...]:
        return tuple(g for g in self.test if g != self.benign_test)


def folds_sha256(folds: Sequence[HoldoutFold]) -> str:
    text = json.dumps([asdict(fold) for fold in folds], indent=2, sort_keys=True) + "\n"
    return hashlib.sha256(text.encode()).hexdigest()


def plan_folds(groups: Sequence[WindowGroup], families: Mapping[str, str]) -> list[HoldoutFold]:
    ids = [g.group_id for g in groups]
    if len(ids) != len(set(ids)):
        raise HoldoutError("duplicate group_id: one parent capture must be one group")

    by_family: dict[str, list[str]] = {}
    benign: list[str] = []
    for group in sorted(groups, key=lambda g: g.group_id):
        family = families.get(group.group_id)
        if group.malicious_windows == 0:
            if family is not None:
                raise HoldoutError(f"{group.group_id}: family {family!r} but no malicious windows")
            benign.append(group.group_id)
        elif not isinstance(family, str) or not family.strip():
            raise HoldoutError(f"{group.group_id}: malicious group has no family to hold out")
        else:
            by_family.setdefault(family, []).append(group.group_id)

    names = sorted(by_family)
    if len(names) < MIN_FAMILIES:
        raise HoldoutError(
            f"{len(names)} malware families; need {MIN_FAMILIES} to hold one out, "
            "validate on another and train on the rest"
        )
    if len(benign) < MIN_BENIGN_GROUPS:
        raise HoldoutError(
            f"{len(benign)} benign groups; need {MIN_BENIGN_GROUPS} for train, validation and test"
        )

    folds = []
    for held in names:
        remaining = [name for name in names if name != held]
        for validation_family in remaining:
            trained = [
                g for name in remaining if name != validation_family for g in by_family[name]
            ]
            for i, benign_test in enumerate(benign):
                benign_validation = benign[(i + 1) % len(benign)]
                benign_train = [g for g in benign if g not in (benign_test, benign_validation)]
                folds.append(
                    HoldoutFold(
                        held_out_family=held,
                        validation_family=validation_family,
                        benign_test=benign_test,
                        train=tuple(sorted(trained + benign_train)),
                        validation=tuple(
                            sorted([benign_validation, *by_family[validation_family]])
                        ),
                        test=tuple(sorted([benign_test, *by_family[held]])),
                    )
                )
    return folds


@dataclass(frozen=True)
class FoldResult:
    fold: HoldoutFold
    seed: int
    trained_windows: int
    policy: ThresholdPolicy | None
    calibration_error: str | None
    held_out_family: Metrics | None
    unseen_benign: Metrics | None
    reference_held_out_family: Metrics
    reference_unseen_benign: Metrics


def _columns(part):
    return [w.malicious for w, _ in part], [s for _, s in part], [w.group_id for w, _ in part]


def run_fold(
    windows: Sequence[LabelledWindow],
    fold: HoldoutFold,
    *,
    seed: int,
    max_window_fpr: float = 0.01,
    bootstrap: int = 1000,
    n_estimators: int = 200,
) -> FoldResult:
    membership = {g: name for name in SPLITS for g in getattr(fold, name)}
    present = {w.group_id for w in windows}
    if present != set(membership):
        raise HoldoutError(
            f"fold and windows disagree: unassigned {sorted(present - set(membership))}, "
            f"absent {sorted(set(membership) - present)}"
        )
    parts = {name: [w for w in windows if membership[w.group_id] == name] for name in SPLITS}
    model = train_random_forest(parts["train"], seed=seed, n_estimators=n_estimators)

    validation = parts["validation"]
    try:
        policy = calibrate_threshold(
            [w.malicious for w in validation],
            rf_scores(model, validation),
            [w.group_id for w in validation],
            max_window_fpr=max_window_fpr,
        )
        error = None
    except CalibrationError as exc:
        policy, error = None, str(exc)

    # Test windows are scored only after the threshold is fixed on validation.
    scored = list(zip(parts["test"], rf_scores(model, parts["test"]), strict=True))
    held = set(fold.held_out_groups)
    family_part = [(w, s) for w, s in scored if w.group_id in held]
    benign_part = [(w, s) for w, s in scored if w.group_id == fold.benign_test]

    def frozen(part):
        if policy is None:
            return None
        return apply_frozen_policy(policy, *_columns(part), bootstrap=bootstrap, seed=seed)

    def reference(part):
        return evaluate(*_columns(part), REFERENCE_THRESHOLD, bootstrap=bootstrap, seed=seed)

    return FoldResult(
        fold=fold,
        seed=seed,
        trained_windows=len(parts["train"]),
        policy=policy,
        calibration_error=error,
        held_out_family=frozen(family_part),
        unseen_benign=frozen(benign_part),
        reference_held_out_family=reference(family_part),
        reference_unseen_benign=reference(benign_part),
    )
