import importlib.util
import json
import random
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from core.features import FEATURE_ORDER, FEATURE_SCHEMA_VERSION
from core.schema import FeatureVector
from model.holdout import HoldoutError, plan_folds
from model.split import WindowGroup
from model.train import LabelledWindow, window_groups

HAVE_SKLEARN = importlib.util.find_spec("sklearn") is not None
FAMILIES = {"attack-a": "Alpha", "attack-b": "Beta", "attack-c": "Gamma"}
BENIGN = ("benign-0", "benign-1", "benign-2")


def windows_for(groups, seed: int = 0, per_group: int = 20):
    """Deliberately separable synthetic windows: fold mechanics, not detection quality."""
    rng = random.Random(seed)
    index = {name: i for i, name in enumerate(FEATURE_ORDER)}
    out = []
    for group_id, malicious in groups:
        for w in range(per_group):
            values = [0.0] * len(FEATURE_ORDER)
            values[index["pkt_count"]] = float(
                rng.randint(80, 200) if malicious else rng.randint(1, 30)
            )
            values[index["syn_only_share"]] = (
                rng.uniform(0.6, 1.0) if malicious else rng.uniform(0.0, 0.1)
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


def default_windows(**kwargs):
    return windows_for([(g, False) for g in BENIGN] + [(g, True) for g in FAMILIES], **kwargs)


class PlanFoldsTests(unittest.TestCase):
    def setUp(self):
        self.groups = window_groups(default_windows(per_group=2))
        self.folds = plan_folds(self.groups, FAMILIES)

    def test_held_out_family_never_reaches_train_or_validation(self):
        everything = {g.group_id for g in self.groups}
        for fold in self.folds:
            with self.subTest(fold=fold):
                held = {g for g, family in FAMILIES.items() if family == fold.held_out_family}
                self.assertEqual(set(fold.held_out_groups), held)
                self.assertFalse(held & (set(fold.train) | set(fold.validation)))
                parts = [set(fold.train), set(fold.validation), set(fold.test)]
                self.assertEqual(set().union(*parts), everything)
                self.assertEqual(sum(map(len, parts)), len(everything))
                self.assertIn(fold.benign_test, fold.test)
                self.assertNotEqual(fold.validation_family, fold.held_out_family)

    def test_every_family_and_benign_capture_is_tested_equally(self):
        self.assertEqual(len(self.folds), 3 * 2 * 3)
        for family in FAMILIES.values():
            self.assertEqual(sum(f.held_out_family == family for f in self.folds), 6)
        for benign in BENIGN:
            self.assertEqual(sum(f.benign_test == benign for f in self.folds), 6)

    def test_input_order_does_not_change_the_folds(self):
        self.assertEqual(plan_folds(list(reversed(self.groups)), FAMILIES), self.folds)

    def test_a_family_with_several_captures_is_held_out_whole(self):
        families = FAMILIES | {"attack-a2": "Alpha"}
        alpha = {"attack-a", "attack-a2"}
        for fold in plan_folds([*self.groups, WindowGroup("attack-a2", 2, 2)], families):
            with self.subTest(fold=fold):
                if fold.held_out_family == "Alpha":
                    self.assertTrue(alpha <= set(fold.test))
                else:
                    self.assertTrue(alpha <= set(fold.train) or alpha <= set(fold.validation))

    def test_inputs_that_would_leak_or_hide_a_family_are_rejected(self):
        cases = {
            "malicious group without a family": (
                self.groups,
                {"attack-a": "Alpha", "attack-b": "Beta"},
            ),
            "benign group with a family": (self.groups, FAMILIES | {"benign-0": "Alpha"}),
            "only two families": (self.groups, FAMILIES | {"attack-c": "Beta"}),
            "only two benign groups": (
                [g for g in self.groups if g.group_id != "benign-2"],
                FAMILIES,
            ),
            "duplicate group": ([*self.groups, WindowGroup("benign-0", 2, 0)], FAMILIES),
        }
        for name, (groups, families) in cases.items():
            with self.subTest(name), self.assertRaises(HoldoutError):
                plan_folds(groups, families)


@unittest.skipUnless(HAVE_SKLEARN, "scikit-learn is pinned by KAN-10; not installed here")
class RunFoldTests(unittest.TestCase):
    def setUp(self):
        self.windows = default_windows()
        self.fold = next(
            f
            for f in plan_folds(window_groups(self.windows), FAMILIES)
            if f.held_out_family == "Gamma"
            and f.validation_family == "Beta"
            and f.benign_test == "benign-0"
        )

    def run_fold(self, windows, **kwargs):
        from model.holdout import run_fold

        return run_fold(windows, self.fold, seed=1, bootstrap=0, n_estimators=20, **kwargs)

    def test_threshold_is_frozen_on_validation_before_test_windows_matter(self):
        result = self.run_fold(self.windows)
        flipped = [
            replace(w, malicious=not w.malicious) if w.group_id in self.fold.test else w
            for w in self.windows
        ]
        again = self.run_fold(flipped)
        self.assertIsNotNone(result.policy)
        self.assertEqual(result.policy.selected_on, "validation")
        self.assertEqual(again.policy, result.policy)
        self.assertNotEqual(again.held_out_family, result.held_out_family)

    def test_only_train_windows_are_trained_on_and_parts_are_scored_apart(self):
        result = self.run_fold(self.windows)
        self.assertEqual(
            result.trained_windows, sum(w.group_id in self.fold.train for w in self.windows)
        )
        self.assertEqual(result.held_out_family.malicious_groups, 1)
        self.assertEqual(result.held_out_family.benign_groups, 0)
        self.assertEqual(result.unseen_benign.malicious_groups, 0)
        self.assertEqual(result.unseen_benign.benign_groups, 1)

    def test_an_unmeetable_fpr_budget_is_recorded_not_relaxed(self):
        # benign-1 validates in this fold; give it exact copies of Beta's malicious vectors,
        # so every candidate threshold flags at least one benign validation window.
        copies = iter([w.vector for w in self.windows if w.group_id == "attack-b"])
        windows = [
            replace(w, vector=next(copies)) if w.group_id == "benign-1" else w for w in self.windows
        ]
        result = self.run_fold(windows, max_window_fpr=0.01)
        self.assertIsNone(result.policy)
        self.assertIn("0.01", result.calibration_error)
        self.assertIsNone(result.held_out_family)
        self.assertIsNone(result.unseen_benign)
        self.assertIsNotNone(result.reference_held_out_family.recall)

    def test_windows_outside_the_fold_are_an_error(self):
        extra = windows_for([("benign-9", False)], per_group=2)
        with self.assertRaises(HoldoutError):
            self.run_fold([*self.windows, *extra])


class HoldoutRunTests(unittest.TestCase):
    def test_run_refuses_a_mismatched_pack_before_training(self):
        from model.baseline_run import PackIntegrityError
        from model.holdout_run import run

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            pack = directory / "windows.jsonl"
            pack.write_bytes(b'{"label": "benign"}\n')
            manifest = {
                "windows_file": "windows.jsonl",
                "windows_sha256": "0" * 64,
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
            }
            (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(PackIntegrityError):
                run(pack, directory / "out", seed=1, bootstrap=0, trees=1, max_window_fpr=0.01)
            self.assertFalse((directory / "out").exists())


if __name__ == "__main__":
    unittest.main()
