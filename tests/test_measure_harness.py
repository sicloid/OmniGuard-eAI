"""A measurement that could not be taken must read as absent, never as zero.

These tests pin the harness's reporting contract: failed runs are kept, a frozen
configuration cannot be edited afterwards, and every figure the platform or another
role did not supply is named rather than defaulted. Real CPU and memory figures for a
Raspberry Pi are not produced here; KAN-46/53 measure that hardware.
"""

import json
import tempfile
import unittest
from pathlib import Path

from measure.clocks import ManualClock
from measure.manifest import (
    COMPLETED,
    FAILED,
    INCOMPLETE,
    MANIFEST_FORMAT,
    ExperimentManifest,
    ManifestError,
    ProvenanceFromR1,
    read_manifest,
)
from measure.resources import MemoryReading, _linux_memory, read_cpu, read_memory
from measure.stages import RunCounters, RunRecorder

# Copied byte-for-byte from `grep -E 'VmRSS|VmHWM' /proc/self/status` inside the
# Compose postgres container (Linux, 15 September 2026), tab separators included.
LINUX_STATUS = "Name:\tpsql\nVmHWM:\t     800 kB\nVmRSS:\t     800 kB\nThreads:\t1\n"


class ResourceReadingTests(unittest.TestCase):
    def test_the_linux_parser_reads_a_real_proc_status_sample(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "status"
            path.write_text(LINUX_STATUS, encoding="ascii", newline="")
            reading = _linux_memory(str(path))
        self.assertTrue(reading.measured)
        self.assertEqual(reading.rss_bytes, 800 * 1024)
        self.assertEqual(reading.peak_rss_bytes, 800 * 1024)
        self.assertIsNone(reading.unavailable)

    def test_an_unreadable_source_reports_a_reason_and_not_a_zero(self):
        reading = _linux_memory("/definitely/not/here/status")
        self.assertFalse(reading.measured)
        self.assertIsNone(reading.rss_bytes)
        self.assertIn("unreadable", reading.unavailable)

    def test_a_status_file_without_vmrss_is_unavailable_rather_than_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "status"
            path.write_text("Name:\tsomething\n", encoding="ascii", newline="")
            reading = _linux_memory(str(path))
        self.assertFalse(reading.measured)
        self.assertIn("no VmRSS", reading.unavailable)

    def test_unavailable_is_never_reported_as_a_measured_zero(self):
        absent = MemoryReading(None, None, "test", "no reader")
        self.assertFalse(absent.measured)
        self.assertIsNot(absent.rss_bytes, 0)

    def test_this_platform_reports_either_a_figure_or_a_reason(self):
        reading, cpu = read_memory(), read_cpu()
        self.assertTrue(reading.measured or reading.unavailable)
        self.assertGreaterEqual(cpu.process_seconds, 0.0)
        self.assertTrue(cpu.thread_seconds is not None or cpu.unavailable)


class StageRecordingTests(unittest.TestCase):
    def test_an_unknown_stage_is_refused(self):
        with self.assertRaises(ValueError):
            RunRecorder().stage("sorcery")

    def test_a_failing_stage_is_recorded_and_the_error_still_propagates(self):
        recorder = RunRecorder()
        with self.assertRaises(RuntimeError):
            with recorder.stage("inference"):
                raise RuntimeError("inference blew up")
        self.assertEqual(recorder.failed_stages, ["inference"])
        self.assertEqual(len(recorder.measurements), 1)
        self.assertEqual(recorder.summary()["failed_stages"], ["inference"])

    def test_elapsed_time_comes_from_the_injected_clock(self):
        clock = ManualClock()
        recorder = RunRecorder(clock=clock)
        with recorder.stage("features"):
            clock.advance(0.25)
        self.assertAlmostEqual(recorder.measurements[0].elapsed.seconds, 0.25)

    def test_a_wall_clock_jump_during_a_stage_does_not_change_the_measured_latency(self):
        clock = ManualClock()
        recorder = RunRecorder(clock=clock)
        with recorder.stage("policy"):
            clock.advance(0.10)
            clock.jump_wall_clock(-7200.0)
        self.assertAlmostEqual(recorder.measurements[0].elapsed.seconds, 0.10)

    def test_the_cost_of_measuring_is_reported_rather_than_folded_in(self):
        recorder = RunRecorder()
        with recorder.stage("features"):
            sum(i * i for i in range(50_000))
        measurement = recorder.measurements[0]
        self.assertGreaterEqual(measurement.measurement_overhead.seconds, 0.0)
        self.assertIn("measurement_overhead_seconds", recorder.summary()["stages"]["features"])

    def test_counters_owned_by_other_components_are_named_when_absent(self):
        summary = RunRecorder().summary()
        self.assertEqual(
            summary["counters_not_supplied"],
            [
                "kernel_packet_drops",
                "pipeline_queue_overflows",
                "telemetry_queue_overflows",
                "telemetry_events_dropped",
            ],
        )
        self.assertIsNone(summary["counters"]["kernel_packet_drops"])

    def test_supplied_counters_are_carried_through_and_drop_off_the_missing_list(self):
        recorder = RunRecorder(counters=RunCounters(kernel_packet_drops=12))
        summary = recorder.summary()
        self.assertEqual(summary["counters"]["kernel_packet_drops"], 12)
        self.assertNotIn("kernel_packet_drops", summary["counters_not_supplied"])

    def test_repeated_passes_through_one_stage_are_aggregated_not_overwritten(self):
        clock = ManualClock()
        recorder = RunRecorder(clock=clock)
        for seconds in (0.1, 0.3):
            with recorder.stage("inference"):
                clock.advance(seconds)
        stage = recorder.summary()["stages"]["inference"]
        self.assertEqual(stage["passes"], 2)
        self.assertAlmostEqual(stage["elapsed_seconds_total"], 0.4)
        self.assertAlmostEqual(stage["elapsed_seconds_max"], 0.3)


class ManifestTests(unittest.TestCase):
    def manifest(self, **kwargs):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        return ExperimentManifest(
            run_id="run-1", directory=Path(directory), config={"n": 3}, **kwargs
        )

    def test_freezing_writes_an_incomplete_document_before_the_run_starts(self):
        manifest = self.manifest()
        manifest.freeze()
        document = read_manifest(manifest.directory)
        self.assertEqual(document["manifest_format"], MANIFEST_FORMAT)
        self.assertEqual(document["status"], INCOMPLETE)
        self.assertIsNone(document["measurements"])

    def test_a_run_that_dies_before_closing_leaves_its_frozen_manifest_behind(self):
        # The point of writing at freeze time: a partial run is evidence, not nothing.
        manifest = self.manifest()
        manifest.freeze()
        self.assertEqual(read_manifest(manifest.directory)["status"], INCOMPLETE)
        self.assertTrue(manifest.path.exists())

    def test_the_configuration_cannot_be_changed_after_freezing(self):
        manifest = self.manifest()
        manifest.freeze()
        with self.assertRaises(ManifestError):
            manifest.set_config({"n": 9})

    def test_mutating_the_callers_dict_after_freezing_does_not_rewrite_the_run(self):
        config = {"n": 3}
        directory = self.enterContext(tempfile.TemporaryDirectory())
        manifest = ExperimentManifest(run_id="run-1", directory=Path(directory), config=config)
        manifest.freeze()
        config["n"] = 99
        self.assertEqual(read_manifest(directory)["config"]["n"], 3)

    def test_closing_records_the_measurements_and_the_completed_status(self):
        manifest = self.manifest()
        manifest.freeze()
        manifest.close(measurements=RunRecorder().summary(), outcome={"verdict": "ok"})
        document = read_manifest(manifest.directory)
        self.assertEqual(document["status"], COMPLETED)
        self.assertEqual(document["outcome"], {"verdict": "ok"})
        self.assertIn("stages", document["measurements"])

    def test_a_failed_run_is_closed_as_failed_rather_than_discarded(self):
        manifest = self.manifest()
        manifest.freeze()
        manifest.close(measurements={}, status=FAILED, outcome={"error": "capture died"})
        self.assertEqual(read_manifest(manifest.directory)["status"], FAILED)

    def test_a_run_cannot_be_closed_twice_or_closed_before_freezing(self):
        manifest = self.manifest()
        with self.assertRaises(ManifestError):
            manifest.close(measurements={})
        manifest.freeze()
        manifest.close(measurements={})
        with self.assertRaises(ManifestError):
            manifest.close(measurements={})

    def test_fields_owned_by_other_roles_are_listed_as_not_supplied(self):
        manifest = self.manifest()
        manifest.freeze()
        not_supplied = read_manifest(manifest.directory)["provenance"]["not_supplied"]
        self.assertIn("model_sha256", not_supplied["r1"])
        self.assertIn("t0_unix", not_supplied["r2"])

    def test_a_supplied_provenance_field_leaves_the_not_supplied_list(self):
        manifest = self.manifest(r1=ProvenanceFromR1(model_sha256="a" * 64))
        manifest.freeze()
        provenance = read_manifest(manifest.directory)["provenance"]
        self.assertEqual(provenance["r1"]["model_sha256"], "a" * 64)
        self.assertNotIn("model_sha256", provenance["not_supplied"]["r1"])

    def test_the_written_file_is_valid_json_and_leaves_no_temporary_behind(self):
        manifest = self.manifest()
        manifest.freeze()
        manifest.close(measurements={})
        files = sorted(p.name for p in Path(manifest.directory).iterdir())
        self.assertEqual(files, ["manifest.json"])
        json.loads(manifest.path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
