import unittest

from core.features import FEATURE_ORDER, FEATURE_SCHEMA_VERSION
from core.schema import FeatureVector
from model.baselines import fit_rate_rule
from model.evaluate import EvaluationError, evaluate


def vector(pkt_count: float) -> FeatureVector:
    values = [0.0] * len(FEATURE_ORDER)
    values[FEATURE_ORDER.index("pkt_count")] = float(pkt_count)
    return FeatureVector("dev", 0.0, 5.0, FEATURE_SCHEMA_VERSION, FEATURE_ORDER, tuple(values))


class MetricTests(unittest.TestCase):
    def test_confusion_and_rates(self):
        labels = [True, True, False, False, False]
        scores = [0.9, 0.2, 0.7, 0.1, 0.0]
        m = evaluate(labels, scores, ["a", "a", "b", "b", "c"], 0.5, bootstrap=0)
        self.assertEqual((m.tp, m.fp, m.tn, m.fn), (1, 1, 2, 1))
        self.assertEqual((m.precision, m.recall, m.f1), (0.5, 0.5, 0.5))
        self.assertAlmostEqual(m.fpr, 1 / 3)
        self.assertEqual((m.windows, m.malicious_groups, m.benign_groups), (5, 1, 2))

    def test_threshold_is_inclusive_like_detection_result(self):
        m = evaluate([True], [0.5], ["g"], 0.5, bootstrap=0)
        self.assertEqual(m.tp, 1)

    def test_undefined_rates_are_none_not_zero(self):
        m = evaluate([False, False], [0.0, 0.1], ["a", "b"], 0.5, bootstrap=0)
        self.assertIsNone(m.precision)
        self.assertIsNone(m.recall)
        self.assertIsNone(m.f1)
        self.assertEqual(m.fpr, 0.0)

    def test_group_bootstrap_is_seeded_and_brackets_the_estimate(self):
        labels, scores, groups = [], [], []
        for g in range(10):
            for w in range(2):
                labels.append(True)
                scores.append(0.9 if (g + w) % 2 else 0.1)
                groups.append(f"attack-{g}")
                labels.append(False)
                scores.append(0.8 if g == 0 else 0.0)
                groups.append(f"benign-{g}")
        a = evaluate(labels, scores, groups, 0.5, bootstrap=300, seed=4)
        b = evaluate(labels, scores, groups, 0.5, bootstrap=300, seed=4)
        self.assertEqual(a, b)
        self.assertLessEqual(a.recall_ci[0], a.recall)
        self.assertLessEqual(a.recall, a.recall_ci[1])
        self.assertLessEqual(a.fpr_ci[0], a.fpr)
        self.assertLessEqual(a.fpr, a.fpr_ci[1])

    def test_no_bootstrap_gives_no_interval(self):
        m = evaluate([True, False], [0.9, 0.1], ["a", "b"], 0.5, bootstrap=0)
        self.assertIsNone(m.recall_ci)
        self.assertIsNone(m.fpr_ci)

    def test_rejects_malformed_input(self):
        cases = (
            ([True], [0.9, 0.1], ["a"], 0.5),
            ([], [], [], 0.5),
            ([True], [1.5], ["a"], 0.5),
            ([True], [float("nan")], ["a"], 0.5),
            ([True], [0.5], ["a"], 2.0),
            ([True], [0.5], [""], 0.5),
        )
        for labels, scores, groups, threshold in cases:
            with self.subTest(labels=labels, scores=scores), self.assertRaises(EvaluationError):
                evaluate(labels, scores, groups, threshold, bootstrap=0)


class RateRuleTests(unittest.TestCase):
    def test_fit_chooses_separating_threshold_on_training_data(self):
        vectors = [vector(v) for v in (1, 2, 3, 10, 12)]
        rule = fit_rate_rule(vectors, [False, False, False, True, True])
        self.assertEqual((rule.feature, rule.threshold), ("pkt_count", 10.0))
        self.assertEqual(rule.score(vector(11)), 1.0)
        self.assertEqual(rule.score(vector(5)), 0.0)

    def test_fit_requires_known_feature_and_both_classes(self):
        vectors = [vector(1), vector(9)]
        with self.assertRaises(ValueError):
            fit_rate_rule(vectors, [False, True], feature="no_such_feature")
        with self.assertRaises(ValueError):
            fit_rate_rule(vectors, [False, False])


if __name__ == "__main__":
    unittest.main()
