import importlib.util
import random
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from core.features import FEATURE_ORDER, FEATURE_SCHEMA_VERSION
from core.schema import FeatureVector
from model.train import LabelledWindow, TrainingError, window_groups

HAVE_SKLEARN = importlib.util.find_spec("sklearn") is not None


def synthetic_windows(seed: int = 0, groups_per_class: int = 10, per_group: int = 20):
    """Deliberately separable synthetic data: tests mechanics, not detection quality."""
    rng = random.Random(seed)
    index = {name: i for i, name in enumerate(FEATURE_ORDER)}
    out = []
    for malicious in (False, True):
        for g in range(groups_per_class):
            group_id = f"{'attack' if malicious else 'benign'}-{g}"
            for w in range(per_group):
                values = [0.0] * len(FEATURE_ORDER)
                values[index["pkt_count"]] = float(
                    rng.randint(80, 200) if malicious else rng.randint(1, 30)
                )
                values[index["syn_only_share"]] = (
                    rng.uniform(0.6, 1.0) if malicious else rng.uniform(0.0, 0.1)
                )
                values[index["uniq_dst_ip"]] = float(
                    rng.randint(20, 60) if malicious else rng.randint(1, 4)
                )
                vector = FeatureVector(
                    group_id,
                    float(w * 5),
                    float(w * 5 + 5),
                    FEATURE_SCHEMA_VERSION,
                    FEATURE_ORDER,
                    tuple(values),
                )
                out.append(LabelledWindow(group_id, vector, malicious))
    return out


class WindowGroupTests(unittest.TestCase):
    def test_groups_aggregate_window_and_label_counts(self):
        windows = synthetic_windows(groups_per_class=2, per_group=3)
        groups = {g.group_id: g for g in window_groups(windows)}
        self.assertEqual(groups["attack-0"].windows, 3)
        self.assertEqual(groups["attack-0"].malicious_windows, 3)
        self.assertEqual(groups["benign-1"].malicious_windows, 0)


@unittest.skipUnless(HAVE_SKLEARN, "scikit-learn is pinned by KAN-10; not installed here")
class RandomForestBaselineTests(unittest.TestCase):
    def setUp(self):
        from model.train import run_baseline

        self.windows = synthetic_windows()
        self.report = run_baseline(self.windows, seed=1, bootstrap=200)

    def test_report_is_on_validation_and_compares_against_rate_rule(self):
        report = self.report
        self.assertEqual(report.evaluated_split, "validation")
        self.assertGreaterEqual(report.rf.recall, 0.95)
        self.assertLessEqual(report.rf.fpr, 0.05)
        self.assertIsNotNone(report.rate_rule.recall)
        self.assertIsNotNone(report.rf.recall_ci)

    def test_training_uses_train_groups_only(self):
        report = self.report
        self.assertEqual(report.trained_groups, frozenset(report.manifest.train))
        self.assertFalse(report.trained_groups & set(report.manifest.validation))
        self.assertFalse(report.trained_groups & set(report.manifest.test))
        self.assertEqual(report.trained_windows, report.manifest.counts["train"]["windows"])

    def test_artifact_round_trip_through_kan9_loader(self):
        from model.artifact import load_model
        from model.train import rf_scores, save_artifact

        with tempfile.TemporaryDirectory() as tmp:
            meta = save_artifact(
                self.report.model,
                Path(tmp),
                model_id="rf-synthetic",
                model_version="0.0.1",
                threshold=0.5,
                manifest=self.report.manifest,
            )
            self.assertTrue((Path(tmp) / "split.manifest.json").exists())
            loaded = load_model(
                Path(tmp),
                expected_model_sha256=meta.model_sha256,
                feature_schema_version=FEATURE_SCHEMA_VERSION,
                feature_order=FEATURE_ORDER,
            )
        self.assertEqual(meta.training_manifest_sha256, self.report.manifest.sha256())
        sample = self.windows[:25]
        self.assertEqual(rf_scores(loaded.model, sample), rf_scores(self.report.model, sample))


class TrainingInputTests(unittest.TestCase):
    def test_rejects_vectors_from_another_catalogue(self):
        from model.train import feature_matrix

        window = synthetic_windows(groups_per_class=1, per_group=1)[0]
        stub = replace(
            window,
            vector=FeatureVector("dev", 0.0, 5.0, "stub-0.1", ("a", "b"), (1.0, 2.0)),
        )
        with self.assertRaises(TrainingError):
            feature_matrix([window, stub])

    @unittest.skipUnless(HAVE_SKLEARN, "scikit-learn not installed")
    def test_training_requires_both_classes(self):
        from model.train import train_random_forest

        benign_only = [w for w in synthetic_windows() if not w.malicious]
        with self.assertRaises(TrainingError):
            train_random_forest(benign_only, seed=0)


if __name__ == "__main__":
    unittest.main()
