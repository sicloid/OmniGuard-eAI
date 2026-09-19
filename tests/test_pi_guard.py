"""KAN-46 guard must invalidate missing and contaminated Pi observations."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from measure.pi_guard import assess, main


def clean():
    return {
        "machine": "aarch64",
        "model": "Raspberry Pi 5 Model B Rev 1.0",
        "cpu_count": 4,
        "load_1m": 0.5,
        "throttled_bits": 0,
        "temperature_c": 48.0,
    }


class PiGuardTests(unittest.TestCase):
    def test_clean_pi_environment_is_accepted(self):
        self.assertEqual(
            assess(clean(), clean(), 0, max_load_per_core=0.5, max_temperature_c=80), []
        )

    def test_sticky_prior_throttle_and_new_throttle_both_invalidate(self):
        before, after = clean(), clean()
        before["throttled_bits"] = 0x40000
        after["throttled_bits"] = 0x4
        self.assertEqual(
            assess(before, after, 0, max_load_per_core=0.5, max_temperature_c=80),
            [
                "before_throttling_or_undervoltage",
                "after_throttling_or_undervoltage",
            ],
        )

    def test_missing_sensors_overload_and_failed_command_are_all_retained(self):
        before, after = clean(), clean()
        before["throttled_bits"] = None
        after["temperature_c"] = None
        after["load_1m"] = 3.0
        reasons = assess(before, after, 2, max_load_per_core=0.5, max_temperature_c=80)
        self.assertEqual(
            reasons,
            [
                "command_failed",
                "before_throttling_missing",
                "after_temperature_missing",
                "after_load_high",
            ],
        )

    def test_wrapper_keeps_failed_run_and_does_not_reuse_directory(self):
        with (
            tempfile.TemporaryDirectory() as root,
            patch("measure.pi_guard.probe", side_effect=[clean(), clean()]),
        ):
            directory = Path(root) / "run"
            result = main(
                [
                    "--out",
                    str(directory),
                    "--max-load-per-core",
                    "0.5",
                    "--",
                    sys.executable,
                    "-c",
                    "import sys; sys.exit(7)",
                ]
            )
            self.assertEqual(result, 1)
            self.assertEqual(
                json.loads((directory / "verdict.json").read_text())["reasons"], ["command_failed"]
            )
            with self.assertRaises(FileExistsError):
                main(
                    [
                        "--out",
                        str(directory),
                        "--max-load-per-core",
                        "0.5",
                        "--",
                        sys.executable,
                        "-c",
                        "pass",
                    ]
                )


if __name__ == "__main__":
    unittest.main()
