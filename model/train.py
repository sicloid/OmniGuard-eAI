"""KAN-18 first local Random Forest baseline, compared with a rate rule.

Training uses the train split only and metrics are reported on validation. The
test split is never read here: it is reserved for the frozen final evaluation,
after KAN-19 selects the threshold on validation. scikit-learn and joblib are
imported lazily; their exact pins belong to KAN-10.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from core.features import FEATURE_ORDER, FEATURE_SCHEMA_VERSION
from core.schema import FeatureVector
from model.artifact import MODEL_FILENAME, ArtifactMetadata, build_metadata, write_metadata
from model.baselines import RateRule, fit_rate_rule
from model.evaluate import Metrics, evaluate
from model.split import SPLITS, SplitManifest, WindowGroup, split_by_group

SPLIT_MANIFEST_FILENAME = "split.manifest.json"


class TrainingError(ValueError):
    """Training inputs are inconsistent; no model or report is produced."""


@dataclass(frozen=True)
class LabelledWindow:
    group_id: str
    vector: FeatureVector
    malicious: bool

    def __post_init__(self) -> None:
        if not isinstance(self.group_id, str) or not self.group_id.strip():
            raise TrainingError("group_id must be nonempty text")
        if not isinstance(self.vector, FeatureVector):
            raise TrainingError("vector must be a FeatureVector")
        if type(self.malicious) is not bool:
            raise TrainingError("malicious must be bool")


def window_groups(windows: Sequence[LabelledWindow]) -> list[WindowGroup]:
    totals: dict[str, list[int]] = {}
    for w in windows:
        counts = totals.setdefault(w.group_id, [0, 0])
        counts[0] += 1
        counts[1] += w.malicious
    return [WindowGroup(g, n, m) for g, (n, m) in sorted(totals.items())]


def feature_matrix(windows: Sequence[LabelledWindow]) -> list[list[float]]:
    for w in windows:
        if (
            w.vector.feature_schema_version != FEATURE_SCHEMA_VERSION
            or w.vector.feature_order != FEATURE_ORDER
        ):
            raise TrainingError(
                f"{w.group_id}: vector is {w.vector.feature_schema_version}, "
                f"expected {FEATURE_SCHEMA_VERSION} in catalogue order"
            )
    return [list(w.vector.values) for w in windows]


def train_random_forest(
    windows: Sequence[LabelledWindow],
    *,
    seed: int,
    n_estimators: int = 200,
    max_depth: int | None = None,
    min_samples_leaf: int = 1,
):
    labels = [w.malicious for w in windows]
    if not labels or all(labels) or not any(labels):
        raise TrainingError("training needs windows of both classes")
    from sklearn.ensemble import RandomForestClassifier

    model = RandomForestClassifier(
        n_estimators=n_estimators,
        max_depth=max_depth,
        min_samples_leaf=min_samples_leaf,
        class_weight="balanced",
        random_state=seed,
        n_jobs=1,
    )
    model.fit(feature_matrix(windows), [int(label) for label in labels])
    return model


def rf_scores(model, windows: Sequence[LabelledWindow]) -> list[float]:
    """Probability of class 1 from the forest; a score, not a calibrated probability."""
    if list(model.classes_) != [0, 1]:
        raise TrainingError("model must be trained on classes [0, 1]")
    return [float(row[1]) for row in model.predict_proba(feature_matrix(windows))]


@dataclass(frozen=True)
class BaselineReport:
    evaluated_split: str
    manifest: SplitManifest
    model: object
    rf: Metrics
    rate_rule: Metrics
    rule: RateRule
    trained_groups: frozenset[str]
    trained_windows: int


def run_baseline(
    windows: Sequence[LabelledWindow],
    *,
    seed: int,
    threshold: float = 0.5,
    validation: float = 0.15,
    test: float = 0.15,
    bootstrap: int = 1000,
    n_estimators: int = 200,
) -> BaselineReport:
    manifest = split_by_group(window_groups(windows), seed=seed, validation=validation, test=test)
    membership = {g: name for name in SPLITS for g in getattr(manifest, name)}
    train = [w for w in windows if membership[w.group_id] == "train"]
    held_out = [w for w in windows if membership[w.group_id] == "validation"]

    model = train_random_forest(train, seed=seed, n_estimators=n_estimators)
    rule = fit_rate_rule([w.vector for w in train], [w.malicious for w in train])

    labels = [w.malicious for w in held_out]
    groups = [w.group_id for w in held_out]
    rf_metrics = evaluate(
        labels, rf_scores(model, held_out), groups, threshold, bootstrap=bootstrap, seed=seed
    )
    rule_metrics = evaluate(
        labels,
        [rule.score(w.vector) for w in held_out],
        groups,
        0.5,  # rule scores are 0/1
        bootstrap=bootstrap,
        seed=seed,
    )
    return BaselineReport(
        evaluated_split="validation",
        manifest=manifest,
        model=model,
        rf=rf_metrics,
        rate_rule=rule_metrics,
        rule=rule,
        trained_groups=frozenset(w.group_id for w in train),
        trained_windows=len(train),
    )


def save_artifact(
    model,
    out_dir: Path,
    *,
    model_id: str,
    model_version: str,
    threshold: float,
    manifest: SplitManifest,
) -> ArtifactMetadata:
    """Write model.joblib + model.meta.json (KAN-9) and the split manifest beside them."""
    import joblib

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = out_dir / MODEL_FILENAME
    joblib.dump(model, model_path)
    (out_dir / SPLIT_MANIFEST_FILENAME).write_text(manifest.to_json(), encoding="utf-8")
    meta = build_metadata(
        model_path,
        model_id=model_id,
        model_version=model_version,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        feature_order=FEATURE_ORDER,
        threshold=threshold,
        training_manifest_sha256=manifest.sha256(),
    )
    write_metadata(meta, out_dir)
    return meta
