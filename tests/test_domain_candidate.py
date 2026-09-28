import unittest

import numpy as np

from model.domain_candidate import threshold_at_source_budgets


class DomainCandidateTests(unittest.TestCase):
    def test_threshold_must_satisfy_each_benign_source(self):
        labels = np.array([True, True, False, False, False, False])
        scores = np.array([0.9, 0.7, 0.8, 0.1, 0.6, 0.2])
        source = np.array(["attack", "attack", "iot", "iot", "cic", "cic"])
        threshold = threshold_at_source_budgets(labels, scores, source, {"iot": 0.0, "cic": 0.0})
        self.assertEqual(threshold, 0.9)

    def test_tied_scores_cannot_split_false_positive_from_true_positive(self):
        labels = np.array([True, False, True, False])
        scores = np.array([0.8, 0.8, 0.7, 0.1])
        source = np.array(["attack", "iot", "attack", "cic"])
        threshold = threshold_at_source_budgets(labels, scores, source, {"iot": 0.0, "cic": 0.0})
        self.assertIsNone(threshold)


if __name__ == "__main__":
    unittest.main()
