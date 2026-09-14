"""KAN-17 capture-aware train/validation/test split.

A group is one original parent capture/session. All windows of a group land in
exactly one split, so fragments of one capture never leak across boundaries.
Groups are stratified by class (any malicious window vs benign-only), ordered by
a seeded SHA-256 of their id, and assigned until the window-count targets for
test, then validation, are met; the rest is train. The manifest's SHA-256 is the
`training_manifest_sha256` recorded in the KAN-9 model artifact.

Fitting of imputation, scaling or feature selection belongs to the training code
(KAN-18) and must use the train split only; this module does no fitting.
"""

import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass

METHOD = "stratified-group-hash-v1"
MIN_GROUPS_PER_CLASS = 3
SPLITS = ("train", "validation", "test")


class SplitError(ValueError):
    """The groups cannot be split without leakage or an empty class."""


@dataclass(frozen=True)
class WindowGroup:
    group_id: str
    windows: int
    malicious_windows: int

    def __post_init__(self) -> None:
        if not isinstance(self.group_id, str) or not self.group_id.strip():
            raise SplitError("group_id must be nonempty text")
        if type(self.windows) is not int or self.windows < 1:
            raise SplitError(f"{self.group_id}: windows must be a positive integer")
        if type(self.malicious_windows) is not int or not (
            0 <= self.malicious_windows <= self.windows
        ):
            raise SplitError(f"{self.group_id}: malicious_windows must be in [0, windows]")


@dataclass(frozen=True)
class SplitManifest:
    method: str
    seed: int
    validation_fraction: float
    test_fraction: float
    train: tuple[str, ...]
    validation: tuple[str, ...]
    test: tuple[str, ...]
    counts: dict[str, dict[str, int]]

    def split_of(self, group_id: str) -> str:
        for name in SPLITS:
            if group_id in getattr(self, name):
                return name
        raise KeyError(group_id)

    def to_json(self) -> str:
        document = asdict(self) | {name: list(getattr(self, name)) for name in SPLITS}
        return json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n"

    def sha256(self) -> str:
        return hashlib.sha256(self.to_json().encode()).hexdigest()


def _take(ordered: list[WindowGroup], target: float, limit: int) -> list[WindowGroup]:
    """Pop groups until their windows reach target, never taking more than limit.

    The limit keeps the later splits non-empty: with three uneven groups per class,
    chasing the window target alone can swallow two of them and leave train empty.
    """
    taken, total = [], 0
    while ordered and len(taken) < limit and (not taken or total < target):
        group = ordered.pop(0)
        taken.append(group)
        total += group.windows
    return taken


def split_by_group(
    groups: Sequence[WindowGroup],
    *,
    seed: int,
    validation: float = 0.15,
    test: float = 0.15,
) -> SplitManifest:
    if type(seed) is not int:
        raise SplitError("seed must be an integer")
    if not (0 < validation < 1 and 0 < test < 1 and validation + test < 1):
        raise SplitError("fractions must be positive and leave a nonempty train split")
    ids = [g.group_id for g in groups]
    if len(ids) != len(set(ids)):
        raise SplitError("duplicate group_id: one parent capture must be one group")

    def order_key(group: WindowGroup) -> tuple[str, str]:
        digest = hashlib.sha256(f"{seed}:{group.group_id}".encode()).hexdigest()
        return digest, group.group_id

    assigned: dict[str, list[WindowGroup]] = {name: [] for name in SPLITS}
    strata = {
        "malicious": [g for g in groups if g.malicious_windows > 0],
        "benign": [g for g in groups if g.malicious_windows == 0],
    }
    for label, members in strata.items():
        if len(members) < MIN_GROUPS_PER_CLASS:
            raise SplitError(
                f"{label}: {len(members)} groups; need at least {MIN_GROUPS_PER_CLASS} "
                "so every split gets whole groups of this class"
            )
        ordered = sorted(members, key=order_key)
        total = sum(g.windows for g in ordered)
        # Reserve one group for validation and one for train before filling test.
        assigned["test"] += _take(ordered, test * total, len(ordered) - 2)
        assigned["validation"] += _take(ordered, validation * total, len(ordered) - 1)
        if not ordered:
            raise SplitError(f"{label}: no groups left for train; add groups or lower fractions")
        assigned["train"] += ordered

    counts = {
        name: {
            "groups": len(members),
            "windows": sum(g.windows for g in members),
            "malicious_windows": sum(g.malicious_windows for g in members),
        }
        for name, members in assigned.items()
    }
    return SplitManifest(
        METHOD,
        seed,
        validation,
        test,
        *(tuple(sorted(g.group_id for g in assigned[name])) for name in SPLITS),
        counts,
    )
