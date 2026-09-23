"""KAN-46 guard must invalidate missing and contaminated Pi observations."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from measure.pi_guard import assess, main, probe


def clean():
    return {
        "machine": "aarch64",
        "model": "Raspberry Pi 5 Model B Rev 1.0",
        "cpu_count": 4,
        "load_1m": 0.5,
        "throttled_bits": 0,
        "temperature_c": 48.0,
        "host_id": "pi-lab",
        "boot_id": "boot-a",
        "utc_ns": 1_000_000_000,
        "monotonic_ns": 100_000_000,
    }


class PiGuardTests(unittest.TestCase):
    def test_clean_pi_environment_is_accepted(self):
        self.assertEqual(
            assess(clean(), clean(), 0, max_load_per_core=0.5, max_temperature_c=80), []
        )

    def test_a_model_change_is_distinct_from_not_running_on_a_pi5(self):
        before, after = clean(), clean()
        after["model"] = "Raspberry Pi 4 Model B"
        self.assertEqual(
            assess(before, after, 0, max_load_per_core=0.5, max_temperature_c=80),
            ["model_changed"],
        )
        before["model"] = "generic aarch64 board"
        self.assertEqual(
            assess(before, after, 0, max_load_per_core=0.5, max_temperature_c=80),
            ["not_pi5", "model_changed"],
        )

    def test_sticky_prior_throttle_and_current_throttle_are_distinct(self):
        before, after = clean(), clean()
        before["throttled_bits"] = 0x40000
        after["throttled_bits"] = 0x4
        self.assertEqual(
            assess(before, after, 0, max_load_per_core=0.5, max_temperature_c=80),
            [
                "before_historical_throttling_or_undervoltage",
                "after_current_throttling_or_undervoltage",
            ],
        )

    def test_new_sticky_event_is_reported_as_during_run(self):
        before, after = clean(), clean()
        after["throttled_bits"] = 0x40000
        self.assertEqual(
            assess(before, after, 0, max_load_per_core=0.5, max_temperature_c=80),
            ["during_throttling_or_undervoltage"],
        )

    def test_after_load_includes_workload_and_is_context(self):
        before, after = clean(), clean()
        after["load_1m"] = 3.0
        self.assertEqual(assess(before, after, 0, max_load_per_core=0.5, max_temperature_c=80), [])

    def test_reboot_and_missing_monotonic_evidence_invalidate(self):
        before, after = clean(), clean()
        after["boot_id"] = "boot-b"
        after["monotonic_ns"] = -1
        self.assertEqual(
            assess(before, after, 0, max_load_per_core=0.5, max_temperature_c=80),
            ["boot_identity_missing_or_changed", "monotonic_interval_missing_or_invalid"],
        )

    def test_probe_handles_missing_getloadavg_without_throwing(self):
        with (
            patch("measure.pi_guard.os.getloadavg", None, create=True),
            patch("measure.pi_guard._vcgencmd", return_value=None),
        ):
            reading = probe()
        self.assertIsNone(reading["load_1m"])
        self.assertIsInstance(reading["monotonic_ns"], int)
        self.assertIn("boot_id", reading)

    def test_missing_getloadavg_keeps_full_invalid_run_evidence(self):
        with (
            tempfile.TemporaryDirectory() as root,
            patch("measure.pi_guard.os.getloadavg", None, create=True),
            patch("measure.pi_guard._vcgencmd", return_value=None),
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
                    "pass",
                ]
            )
            self.assertEqual(result, 1)
            self.assertTrue(
                {"before.json", "after.json", "verdict.json"}.issubset(
                    path.name for path in directory.iterdir()
                )
            )
            self.assertIn(
                "before_load_missing",
                json.loads((directory / "verdict.json").read_text())["reasons"],
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
