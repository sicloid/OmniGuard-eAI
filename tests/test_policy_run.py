import hashlib
import importlib.util
import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.features import FEATURE_ORDER, FEATURE_SCHEMA_VERSION
from model.baseline_run import PackIntegrityError
from model.policy_run import SPEC, PolicySpecError, load_spec, run

HAVE_SKLEARN = importlib.util.find_spec("sklearn") is not None
GROUPS = ("benign-0", "benign-1", "benign-2", "attack-0", "attack-1", "attack-2")


def write_pack(directory: Path, *, separable: bool = True, per_group: int = 30):
    """Synthetic pack: separable windows, or identical vectors that no threshold can split."""
    rng = random.Random(0)
    index = {name: i for i, name in enumerate(FEATURE_ORDER)}
    lines = []
    for group in GROUPS:
        malicious = group.startswith("attack")
        for w in range(per_group):
            values = [0.0] * len(FEATURE_ORDER)
            if separable:
                values[index["pkt_count"]] = float(
                    rng.randint(80, 200) if malicious else rng.randint(1, 30)
                )
                values[index["syn_only_share"]] = (
                    rng.uniform(0.6, 1.0) if malicious else rng.uniform(0.0, 0.1)
                )
            else:
                values[index["pkt_count"]] = 10.0
            row = {
                "group": group,
                "device_id": group,
                "window_start": float(w * 5),
                "label": "malicious" if malicious else "benign",
                "values": values,
            }
            lines.append(json.dumps(row, sort_keys=True))
    payload = "".join(line + "\n" for line in lines)
    pack = directory / "windows.jsonl"
    pack.write_text(payload, encoding="utf-8")
    sha = hashlib.sha256(payload.encode()).hexdigest()
    manifest = {
        "windows_file": "windows.jsonl",
        "windows_sha256": sha,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
    }
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return pack, sha


def write_spec(directory: Path, sha: str, **changes) -> Path:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    spec |= {"development_pack_windows_sha256": sha, "n_estimators": 10, "bootstrap": 0}
    spec |= changes
    path = directory / "spec.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


class SpecTests(unittest.TestCase):
    def test_committed_spec_fixes_the_approved_budget_and_operating_seed(self):
        spec = load_spec(SPEC)
        self.assertEqual(spec["max_window_fpr"], 0.01)
        self.assertEqual(spec["selected_on"], "validation")
        self.assertEqual(spec["objective"], "max_recall_at_fpr")
        self.assertEqual(spec["operating_seed"], 1)
        self.assertEqual(spec["sensitivity_seeds"], [2, 3])
        self.assertEqual(
            spec["development_pack_windows_sha256"],
            "4b97fb954270a2727544724aa331d20354f9e10f6aa5d1bbbf62a5f3c40c6625",
        )

    def test_specs_that_would_allow_tuning_after_results_are_rejected(self):
        cases = {
            "selected on test": {"selected_on": "test"},
            "operating seed reused for sensitivity": {"sensitivity_seeds": [1, 2]},
            "budget above one": {"max_window_fpr": 1.5},
            "boolean budget": {"max_window_fpr": True},
            "other catalogue": {"feature_schema_version": "features-2"},
            "malformed pack hash": {"development_pack_windows_sha256": "abc"},
            "unknown objective": {"objective": "best_looking"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            for name, change in cases.items():
                with self.subTest(name):
                    path = write_spec(Path(tmp), "0" * 64, **change)
                    with self.assertRaises(PolicySpecError):
                        load_spec(path)


class RefusalTests(unittest.TestCase):
    def test_a_pack_other_than_the_one_the_spec_names_is_refused_before_training(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            pack, _ = write_pack(directory)
            spec = write_spec(directory, "0" * 64)
            with self.assertRaises(PackIntegrityError):
                run(pack, directory / "out", spec)
            self.assertFalse((directory / "out").exists())


@unittest.skipUnless(HAVE_SKLEARN, "scikit-learn is pinned by KAN-10; not installed here")
class PolicyRunTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_operating_policy_is_frozen_with_a_matching_artifact(self):
        pack, sha = write_pack(self.dir)
        out = self.dir / "out"
        result = run(pack, out, write_spec(self.dir, sha))
        self.assertEqual(result["status"], "operating_policy_frozen")
        artifact = out / "operating"
        policy_bytes = (artifact / "threshold.policy.json").read_bytes()
        policy = json.loads(policy_bytes)
        meta = json.loads((artifact / "model.meta.json").read_text(encoding="utf-8"))
        provenance = json.loads((artifact / "provenance.json").read_text(encoding="utf-8"))
        self.assertEqual(policy["selected_on"], "validation")
        self.assertLessEqual(policy["metrics"]["fpr"], 0.01)
        self.assertEqual(meta["threshold"], policy["threshold"])
        self.assertEqual(provenance["threshold"], policy["threshold"])
        self.assertEqual(
            provenance["threshold_policy_sha256"], hashlib.sha256(policy_bytes).hexdigest()
        )
        self.assertEqual(provenance["windows_sha256"], sha)
        self.assertEqual(
            [(r["seed"], r["role"]) for r in result["runs"]],
            [(1, "operating"), (2, "sensitivity"), (3, "sensitivity")],
        )
        # Sensitivity seeds are reported but never produce an artifact.
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["operating", "policy_report.json"])

    def test_unmeetable_budget_is_reported_and_no_artifact_is_written(self):
        pack, sha = write_pack(self.dir, separable=False)
        out = self.dir / "out"
        result = run(pack, out, write_spec(self.dir, sha))
        self.assertEqual(result["status"], "no_operating_policy")
        self.assertIsNone(result["operating"])
        first = result["runs"][0]
        self.assertEqual((first["role"], first["status"]), ("operating", "no_threshold"))
        self.assertIn("0.01", first["error"])
        self.assertFalse((out / "operating").exists())
        self.assertTrue((out / "policy_report.json").exists())

    def test_only_validation_windows_are_scored_for_calibration(self):
        from model import policy_run

        pack, sha = write_pack(self.dir)
        with mock.patch.object(policy_run, "rf_scores", wraps=policy_run.rf_scores) as scored:
            result = run(pack, self.dir / "out", write_spec(self.dir, sha))
        for call, entry in zip(scored.call_args_list, result["runs"], strict=True):
            groups = {w.group_id for w in call.args[1]}
            self.assertEqual(groups, set(entry["split"]["validation"]))
            self.assertFalse(groups & set(entry["split"]["test"]))


if __name__ == "__main__":
    unittest.main()
