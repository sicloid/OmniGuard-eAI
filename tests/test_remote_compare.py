import unittest

from measure.remote_compare import percentile


class RemoteCompareTests(unittest.TestCase):
    def test_percentile_is_deterministic_nearest_rank_floor(self):
        self.assertEqual(percentile([50, 10, 30, 20, 40], 0.5), 30)
        self.assertEqual(percentile([50, 10, 30, 20, 40], 0.95), 40)

    def test_empty_latency_is_invalid(self):
        with self.assertRaisesRegex(ValueError, "at least one"):
            percentile([], 0.5)


if __name__ == "__main__":
    unittest.main()
