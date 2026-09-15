"""KAN-18 baseline run on a real sample pack.

Trains on the train split only and reports validation metrics; the test split is
never read here. With six capture groups a split leaves one capture per class in
each part, so every run is reported per seed: which captures landed where matters
more than any single number, and the report says so.

A run is bound to exact data. The windows file must hash to the `windows_sha256`
its manifest records before any row is read, and the pack and manifest hashes are
written next to every artifact together with its model and metadata hashes. These
are SHA-256 pins, not signatures.
"""

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from core.features import FEATURE_SCHEMA_VERSION
from data.samplepack.build import MANIFEST_FILENAME, read_windows
from model.artifact import META_FILENAME
from model.train import run_baseline, save_artifact

PROVENANCE_FILENAME = "provenance.json"


class PackIntegrityError(ValueError):
    """The sample pack is not the data its manifest describes; nothing is trained."""


@dataclass(frozen=True)
class PackProvenance:
    """What a run read, pinned by hash.

    `label_rule_version` is None for a version-1 manifest, which predates the field.
    It is reported as missing, never filled with a guessed value.
    """

    windows_file: str
    windows_sha256: str
    manifest_sha256: str
    feature_schema_version: str
    manifest_version: int = 1
    label_rule_version: str | None = None


SUPPORTED_MANIFEST_VERSIONS = (1, 2)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_pack(pack: Path, manifest: Path | None = None) -> PackProvenance:
    """Check the windows file against its manifest before any row is read."""
    pack = Path(pack)
    manifest = Path(manifest) if manifest else pack.with_name(MANIFEST_FILENAME)
    if not pack.is_file():
        raise PackIntegrityError(f"sample pack not found: {pack}")
    if not manifest.is_file():
        raise PackIntegrityError(f"manifest not found: {manifest}")
    raw = manifest.read_bytes()
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PackIntegrityError(f"manifest is not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise PackIntegrityError("manifest must be a JSON object")
    if document.get("windows_file") != pack.name:
        raise PackIntegrityError(
            f"manifest describes {document.get('windows_file')!r}, not {pack.name!r}"
        )
    if document.get("feature_schema_version") != FEATURE_SCHEMA_VERSION:
        raise PackIntegrityError(
            f"pack uses {document.get('feature_schema_version')!r}, "
            f"runtime expects {FEATURE_SCHEMA_VERSION!r}"
        )
    version = document.get("manifest_version", 1)
    label_rule_version = document.get("label_rule_version")
    if type(version) is not int or version not in SUPPORTED_MANIFEST_VERSIONS:
        raise PackIntegrityError(f"unsupported manifest_version {version!r}")
    if version == 1 and label_rule_version is not None:
        raise PackIntegrityError("a version-1 manifest cannot carry label_rule_version")
    if version >= 2 and (not isinstance(label_rule_version, str) or not label_rule_version.strip()):
        raise PackIntegrityError("a version-2 manifest must name its label_rule_version")
    actual = _sha256(pack)
    if actual != document.get("windows_sha256"):
        raise PackIntegrityError(
            f"{pack.name} hashes to {actual}, manifest records {document.get('windows_sha256')}"
        )
    return PackProvenance(
        pack.name,
        actual,
        hashlib.sha256(raw).hexdigest(),
        FEATURE_SCHEMA_VERSION,
        version,
        label_rule_version,
    )


def _metrics(metrics) -> dict:
    return asdict(metrics)


def run(
    pack: Path,
    out_dir: Path,
    seeds: list[int],
    bootstrap: int,
    trees: int,
    manifest: Path | None = None,
) -> dict:
    pack, out_dir = Path(pack), Path(out_dir)
    provenance = verify_pack(pack, manifest)
    windows = read_windows(pack)
    if _sha256(pack) != provenance.windows_sha256:
        raise PackIntegrityError(f"{pack.name} changed while it was being read")
    runs = []
    for seed in seeds:
        report = run_baseline(windows, seed=seed, bootstrap=bootstrap, n_estimators=trees)
        artifact_dir = out_dir / f"seed-{seed}"
        meta = save_artifact(
            report.model,
            artifact_dir,
            model_id="rf-iot23",
            model_version=f"0.1.0-seed{seed}",
            threshold=0.5,
            manifest=report.manifest,
        )
        bound = asdict(provenance) | {
            "model_sha256": meta.model_sha256,
            "metadata_sha256": _sha256(artifact_dir / META_FILENAME),
            "training_manifest_sha256": meta.training_manifest_sha256,
        }
        (artifact_dir / PROVENANCE_FILENAME).write_text(
            json.dumps(bound, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        runs.append(
            {
                "seed": seed,
                "split": {
                    "train": list(report.manifest.train),
                    "validation": list(report.manifest.validation),
                    "test": list(report.manifest.test),
                },
                "counts": report.manifest.counts,
                "trained_windows": report.trained_windows,
                "rf": _metrics(report.rf),
                "rate_rule": _metrics(report.rate_rule),
                "rule": {"feature": report.rule.feature, "threshold": report.rule.threshold},
                "artifact": {"dir": str(artifact_dir), **bound},
            }
        )
    result = {
        "pack": {"path": str(pack), **asdict(provenance)},
        "windows": len(windows),
        "malicious_windows": sum(w.malicious for w in windows),
        "benign_windows": sum(not w.malicious for w in windows),
        "groups": sorted({w.group_id for w in windows}),
        "evaluated_split": "validation",
        "threshold": 0.5,
        "n_estimators": trees,
        "bootstrap": bootstrap,
        "runs": runs,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "baseline_report.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, help="defaults to manifest.json beside the pack")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seeds", default="1,2,3")
    parser.add_argument("--bootstrap", type=int, default=500)
    parser.add_argument("--trees", type=int, default=200)
    args = parser.parse_args()
    result = run(
        args.pack,
        args.out,
        [int(s) for s in args.seeds.split(",")],
        args.bootstrap,
        args.trees,
        args.manifest,
    )
    print(f"pack {result['pack']['windows_sha256']} (manifest {result['pack']['manifest_sha256']})")
    for entry in result["runs"]:
        rf, rule = entry["rf"], entry["rate_rule"]
        print(f"\n=== seed {entry['seed']}")
        print("  train:", entry["split"]["train"])
        print("  validation:", entry["split"]["validation"])
        print(f"  windows train/val: {entry['trained_windows']} / {rf['windows']}")
        print(f"  artifact metadata sha256: {entry['artifact']['metadata_sha256']}")
        for name, m in (("RF        ", rf), ("rate rule ", rule)):
            print(
                f"  {name} P={m['precision']} R={m['recall']} F1={m['f1']} FPR={m['fpr']}"
                f" recallCI={m['recall_ci']} fprCI={m['fpr_ci']}"
            )


if __name__ == "__main__":
    main()
