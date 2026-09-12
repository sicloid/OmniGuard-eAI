import json
import tempfile
import unittest
from pathlib import Path

from model.calibrate import (
    CalibrationError,
    apply_frozen_policy,
    calibrate_threshold,
    read_policy,
    write_policy,
)
from model.evaluate import EvaluationError


def validation_set():
    """10 malicious windows (scores 0.9/0.6) and 10 benign (one 0.7, rest 0.1)."""
    labels, scores, groups = [], [], []
    for g in range(5):
        for w in range(2):
            labels.append(True)
            scores.append(0.9 if w == 0 else 0.6)
            groups.append(f"attack-{g}")
            labels.append(False)
            scores.append(0.7 if (g, w) == (0, 0) else 0.1)
            groups.append(f"benign-{g}")
    return labels, scores, groups


class SelectionTests(unittest.TestCase):
    def test_only_validation_is_an_accepted_selection_source(self):
        for source in ("train", "test", "TEST", "", None):
            with self.subTest(source=source), self.assertRaises(CalibrationError):
                calibrate_threshold(*validation_set(), selected_on=source)

    def test_picks_highest_recall_within_the_false_alarm_budget(self):
        labels, scores, groups = validation_set()
        policy = calibrate_threshold(labels, scores, groups, max_window_fpr=0.15)
        self.assertEqual(policy.threshold, 0.6)
        self.assertEqual(policy.metrics.recall, 1.0)
        self.assertLessEqual(policy.metrics.fpr, 0.15)
        self.assertEqual(policy.selected_on, "validation")
        self.assertEqual(policy.candidates, 4)

    def test_a_stricter_budget_forces_a_higher_threshold(self):
        labels, scores, groups = validation_set()
        policy = calibrate_threshold(labels, scores, groups, max_window_fpr=0.0)
        self.assertEqual(policy.threshold, 0.9)
        self.assertEqual(policy.metrics.fpr, 0.0)
        self.assertEqual(policy.metrics.recall, 0.5)

    def test_ties_prefer_the_higher_threshold_fewer_alarms(self):
        labels = [True, True, False, False]
        scores = [0.9, 0.9, 0.3, 0.2]
        groups = ["attack-0", "attack-1", "benign-0", "benign-1"]
        policy = calibrate_threshold(labels, scores, groups, max_window_fpr=0.6)
        self.assertEqual(policy.threshold, 0.9)
        self.assertEqual(policy.metrics.recall, 1.0)

    def test_unreachable_budget_is_an_error_not_a_quiet_fallback(self):
        labels = [True, False]
        scores = [0.4, 1.0]
        groups = ["attack-0", "benign-0"]
        with self.assertRaises(CalibrationError):
            calibrate_threshold(labels, scores, groups, max_window_fpr=0.0)

    def test_max_f1_objective(self):
        labels, scores, groups = validation_set()
        policy = calibrate_threshold(labels, scores, groups, objective="max_f1")
        self.assertEqual(policy.threshold, 0.6)
        self.assertEqual(policy.objective, "max_f1")
        self.assertIsNone(policy.max_window_fpr)

    def test_rejects_unknown_objective_and_impossible_budget(self):
        labels, scores, groups = validation_set()
        with self.assertRaises(CalibrationError):
            calibrate_threshold(labels, scores, groups, objective="max_accuracy")
        with self.assertRaises(CalibrationError):
            calibrate_threshold(labels, scores, groups, max_window_fpr=1.5)
        with self.assertRaises(EvaluationError):
            calibrate_threshold([], [], [], max_window_fpr=0.1)


class FreezeTests(unittest.TestCase):
    def test_loaded_policy_cannot_bypass_selection_invariants(self):
        policy = calibrate_threshold(*validation_set(), max_window_fpr=0.15)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy.json"
            for field, value in (
                ("selected_on", "test"),
                ("threshold", 0.8),
                ("objective", "unknown"),
                ("max_window_fpr", 0.0),
                ("candidates", 0),
            ):
                with self.subTest(field=field):
                    document = json.loads(policy.to_json())
                    document[field] = value
                    path.write_text(json.dumps(document), encoding="utf-8")
                    with self.assertRaises(CalibrationError):
                        read_policy(path)
            for text in ("[]", "{}", '{"threshold": 0.2, "threshold": 0.3}', '{"x": NaN}'):
                path.write_text(text, encoding="utf-8")
                with self.subTest(text=text), self.assertRaises(CalibrationError):
                    read_policy(path)

    def test_policy_survives_a_json_round_trip_with_a_stable_hash(self):
        labels, scores, groups = validation_set()
        policy = calibrate_threshold(labels, scores, groups, max_window_fpr=0.15, bootstrap=50)
        with tempfile.TemporaryDirectory() as tmp:
            path = write_policy(policy, Path(tmp))
            self.assertEqual(path.name, "threshold.policy.json")
            restored = read_policy(path)
        self.assertEqual(restored, policy)
        self.assertEqual(restored.sha256(), policy.sha256())

    def test_test_evaluation_uses_the_frozen_threshold_not_a_better_one(self):
        labels, scores, groups = validation_set()
        policy = calibrate_threshold(labels, scores, groups, max_window_fpr=0.0)
        test_labels = [True, True, False, False]
        test_scores = [0.7, 0.65, 0.2, 0.1]
        test_groups = ["attack-9", "attack-9", "benign-9", "benign-9"]
        metrics = apply_frozen_policy(policy, test_labels, test_scores, test_groups, bootstrap=0)
        self.assertEqual(metrics.threshold, 0.9)
        self.assertEqual(metrics.recall, 0.0)  # the frozen threshold misses both, and that stands
        self.assertEqual(metrics.fpr, 0.0)


if __name__ == "__main__":
    unittest.main()
