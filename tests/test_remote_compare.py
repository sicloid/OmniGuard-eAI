import unittest
from unittest import mock

from measure.remote_compare import _package_version, percentile


class RemoteCompareTests(unittest.TestCase):
    def test_percentile_is_deterministic_nearest_rank_floor(self):
        self.assertEqual(percentile([50, 10, 30, 20, 40], 0.5), 30)
        self.assertEqual(percentile([50, 10, 30, 20, 40], 0.95), 40)

    def test_empty_latency_is_invalid(self):
        with self.assertRaisesRegex(ValueError, "at least one"):
            percentile([], 0.5)

    def test_missing_optional_package_is_recorded_as_unavailable(self):
        with mock.patch(
            "measure.remote_compare.importlib.metadata.version",
            side_effect=__import__("importlib.metadata").metadata.PackageNotFoundError,
        ):
            self.assertIsNone(_package_version("not-installed"))


if __name__ == "__main__":
    unittest.main()
