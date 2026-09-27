import unittest

from model.candidate_run import threshold_at_budget


class CandidateThresholdTests(unittest.TestCase):
    def test_equal_scores_cannot_split_benign_from_malicious(self):
        self.assertIsNone(threshold_at_budget([True, False], [1.0, 1.0], 0.01))

    def test_max_recall_under_budget(self):
        self.assertEqual(threshold_at_budget([True, True, False], [0.9, 0.8, 0.7], 0), 0.8)

    def test_nonfinite_rejected(self):
        with self.assertRaises(ValueError):
            threshold_at_budget([True, False], [float("nan"), 0.1], 0.01)

    def test_missing_class_rejected(self):
        with self.assertRaises(ValueError):
            threshold_at_budget([True, True], [0.9, 0.8], 0.01)
