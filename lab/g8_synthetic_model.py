"""Generate a clearly labelled synthetic RF for disposable wiring smoke only."""

import argparse
import hashlib
import json
from pathlib import Path

import joblib
from sklearn.ensemble import RandomForestClassifier

from core.features import FEATURE_ORDER, FEATURE_SCHEMA_VERSION
from model.artifact import build_metadata, write_metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    labels = []
    for count, label in ((5, 0), (10, 0), (20, 0), (80, 1), (100, 1), (150, 1)):
        for _ in range(20):
            rows.append([count] + [0.0] * (len(FEATURE_ORDER) - 1))
            labels.append(label)
    model = RandomForestClassifier(n_estimators=100, random_state=1, n_jobs=1)
    model.fit(rows, labels)
    path = args.output / "model.joblib"
    joblib.dump(model, path)
    meta = build_metadata(
        path,
        model_id="SYNTHETIC-WIRING-NOT-G8",
        model_version="test",
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        feature_order=FEATURE_ORDER,
        threshold=0.5,
        training_manifest_sha256="0" * 64,
    )
    meta_path = write_metadata(meta, args.output)
    print(
        json.dumps(
            {
                "model_sha256": meta.model_sha256,
                "metadata_sha256": hashlib.sha256(meta_path.read_bytes()).hexdigest(),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
