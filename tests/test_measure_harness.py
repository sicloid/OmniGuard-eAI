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
    HOLDOUT_PRECONDITIONS,
    INCOMPLETE,
    MANIFEST_FORMAT,
    POLICY_CONFIG_VERSION,
    ExperimentManifest,
    ManifestError,
    ObservedFromR2,
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

    def test_actual_t0_and_sink_are_recorded_only_after_the_same_run(self):
        clock = ManualClock(unix=1_700_000_000)
        manifest = self.manifest(clock=clock)
        manifest.freeze()
        before = read_manifest(manifest.directory)["provenance"]
        self.assertIsNone(before["r2"]["t0_unix"])
        self.assertIn("sink_evidence", before["not_supplied"]["r2"])
        clock.advance(10)
        manifest.close(
            measurements={},
            r2_observed=ObservedFromR2(
                run_id="run-1", t0_unix=1_700_000_005, sink_evidence="tcp+udp sink log"
            ),
        )
        after = read_manifest(manifest.directory)["provenance"]
        self.assertEqual(after["r2"]["t0_unix"], 1_700_000_005)
        self.assertEqual(after["r2"]["sink_evidence"], "tcp+udp sink log")
        self.assertEqual(after["r2_observation_phase"], "at-close")
        self.assertNotIn("t0_unix", after["not_supplied"]["r2"])

    def test_t0_from_another_run_cannot_replace_the_frozen_record(self):
        clock = ManualClock(unix=1_700_000_000)
        manifest = self.manifest(clock=clock)
        manifest.freeze()
        opening = manifest.path.read_bytes()
        clock.advance(10)
        for foreign_t0 in (1_699_999_999, 1_700_000_011):
            with self.subTest(foreign_t0=foreign_t0), self.assertRaises(ManifestError):
                manifest.close(
                    measurements={},
                    r2_observed=ObservedFromR2(run_id="run-1", t0_unix=foreign_t0),
                )
            self.assertEqual(manifest.path.read_bytes(), opening)
        manifest.close(
            measurements={},
            r2_observed=ObservedFromR2(run_id="run-1", t0_unix=1_700_000_005),
        )
        self.assertEqual(read_manifest(manifest.directory)["status"], COMPLETED)

    def test_empty_r2_observation_has_no_at_close_phase(self):
        manifest = self.manifest()
        manifest.freeze()
        manifest.close(measurements={}, r2_observed=ObservedFromR2(run_id="run-1"))
        provenance = read_manifest(manifest.directory)["provenance"]
        self.assertIsNone(provenance["r2_observation_phase"])
        self.assertIn("t0_unix", provenance["not_supplied"]["r2"])

    def test_legacy_format_is_rejected_instead_of_reinterpreted_as_at_close(self):
        manifest = self.manifest()
        manifest.freeze()
        legacy = json.loads(manifest.path.read_text(encoding="utf-8"))
        legacy["manifest_format"] = "omniguard-experiment-manifest/1"
        manifest.path.write_text(json.dumps(legacy), encoding="utf-8")
        with self.assertRaisesRegex(ManifestError, "historical /1"):
            read_manifest(manifest.directory)

    def test_foreign_run_observation_cannot_close_or_replace_frozen_run(self):
        manifest = self.manifest()
        manifest.freeze()
        before = manifest.path.read_bytes()
        with self.assertRaises(ManifestError):
            manifest.close(
                measurements={},
                r2_observed=ObservedFromR2(run_id="run-2", t0_unix=1789852223.0),
            )
        self.assertEqual(manifest.path.read_bytes(), before)
        self.assertEqual(read_manifest(manifest.directory)["status"], INCOMPLETE)

    def test_future_t0_and_sink_cannot_be_supplied_before_freeze(self):
        from measure.manifest import ProvenanceFromR2

        manifest = self.manifest(r2=ProvenanceFromR2(t0_unix=1789852223.0))
        with self.assertRaises(ManifestError):
            manifest.freeze()
        self.assertFalse(manifest.path.exists())

    def test_the_written_file_is_valid_json_and_leaves_no_temporary_behind(self):
        manifest = self.manifest()
        manifest.freeze()
        manifest.close(measurements={})
        files = sorted(p.name for p in Path(manifest.directory).iterdir())
        self.assertEqual(files, ["manifest.json"])
        json.loads(manifest.path.read_text(encoding="utf-8"))


class SealedRunTests(unittest.TestCase):
    """A frozen run must not be editable through any route the caller still holds."""

    def manifest(self, **kwargs):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        kwargs.setdefault("config", {"n": 3, "nested": {"lease": 30}})
        return ExperimentManifest(run_id="run-1", directory=Path(directory), **kwargs)

    def test_a_nested_config_value_changed_after_freezing_is_not_published(self):
        # Reported on PR #32: the JSON round-trip only detached the caller's original,
        # and the document was rebuilt from self.config, so this was published silently.
        manifest = self.manifest()
        manifest.freeze()
        manifest.config["n"] = 999
        manifest.config["nested"]["lease"] = 999
        manifest.close(measurements={})
        config = read_manifest(manifest.directory)["config"]
        self.assertEqual(config["n"], 3)
        self.assertEqual(config["nested"]["lease"], 30)

    def test_replacing_a_sealed_attribute_outright_is_refused(self):
        manifest = self.manifest()
        manifest.freeze()
        for name, value in (
            ("config", {"n": 999}),
            ("r1", ProvenanceFromR1(model_sha256="b" * 64)),
            ("run_id", "run-2"),
        ):
            with self.subTest(name), self.assertRaises(ManifestError):
                setattr(manifest, name, value)

    def test_provenance_edited_after_freezing_is_not_published(self):
        manifest = self.manifest(r1=ProvenanceFromR1(model_sha256="a" * 64))
        manifest.freeze()
        manifest.r1.model_sha256 = "b" * 64
        manifest.r1.data_role = "holdout"
        manifest.close(measurements={})
        r1 = read_manifest(manifest.directory)["provenance"]["r1"]
        self.assertEqual(r1["model_sha256"], "a" * 64)
        self.assertIsNone(r1["data_role"])


class RunOwnershipTests(unittest.TestCase):
    """A run directory holds one run; the second must fail rather than replace it."""

    def directory(self):
        return Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_a_second_run_cannot_overwrite_a_completed_record(self):
        directory = self.directory()
        first = ExperimentManifest(run_id="run-1", directory=directory, config={})
        first.freeze()
        first.close(measurements={}, outcome={"verdict": "ok"})
        second = ExperimentManifest(run_id="run-2", directory=directory, config={})
        with self.assertRaises(ManifestError):
            second.freeze()
        document = read_manifest(directory)
        self.assertEqual(document["run_id"], "run-1")
        self.assertEqual(document["status"], COMPLETED)
        self.assertEqual(document["outcome"], {"verdict": "ok"})

    def test_a_second_run_cannot_overwrite_an_incomplete_record_either(self):
        # A run that died is evidence too; reuse must not quietly erase it.
        directory = self.directory()
        ExperimentManifest(run_id="run-1", directory=directory, config={}).freeze()
        second = ExperimentManifest(run_id="run-2", directory=directory, config={})
        with self.assertRaises(ManifestError):
            second.freeze()
        document = read_manifest(directory)
        self.assertEqual(document["run_id"], "run-1")
        self.assertEqual(document["status"], INCOMPLETE)

    def test_closing_is_refused_when_the_record_now_belongs_to_another_run(self):
        directory = self.directory()
        manifest = ExperimentManifest(run_id="run-1", directory=directory, config={})
        manifest.freeze()
        foreign = json.dumps({"run_id": "run-9", "status": COMPLETED})
        manifest.path.write_text(foreign, encoding="utf-8", newline="\n")
        with self.assertRaises(ManifestError):
            manifest.close(measurements={})
        self.assertEqual(json.loads(manifest.path.read_text(encoding="utf-8"))["run_id"], "run-9")


class FailingOnce(ExperimentManifest):
    """A manifest whose next write fails once, to exercise the retry path."""

    def _write(self, document: dict) -> None:
        if getattr(self, "_fail_next", False):
            self._fail_next = False
            raise OSError("no space left on device")
        super()._write(document)


class WriteFailureTests(unittest.TestCase):
    """A write that fails must leave the run retryable, not permanently unclosable."""

    def manifest(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        return FailingOnce(run_id="run-1", directory=Path(directory), config={"n": 3})

    def test_a_freeze_whose_write_fails_can_be_frozen_again(self):
        manifest = self.manifest()
        manifest._fail_next = True
        with self.assertRaises(OSError):
            manifest.freeze()
        self.assertFalse(manifest._frozen)
        manifest.freeze()
        self.assertEqual(read_manifest(manifest.directory)["status"], INCOMPLETE)

    def test_a_close_whose_write_fails_can_be_closed_again(self):
        # Reported on PR #32: _closed was set before the write, so a failed close left
        # the run marked closed while the file on disk stayed incomplete.
        manifest = self.manifest()
        manifest.freeze()
        manifest._fail_next = True
        with self.assertRaises(OSError):
            manifest.close(measurements={}, outcome={"verdict": "ok"})
        self.assertFalse(manifest._closed)
        self.assertEqual(read_manifest(manifest.directory)["status"], INCOMPLETE)
        manifest.close(measurements={}, outcome={"verdict": "ok"})
        self.assertEqual(read_manifest(manifest.directory)["status"], COMPLETED)

    def test_a_failed_write_leaves_no_temporary_file_behind(self):
        manifest = self.manifest()
        manifest._fail_next = True
        with self.assertRaises(OSError):
            manifest.freeze()
        # The reserved manifest.json is the claim on the directory; nothing else.
        files = sorted(p.name for p in Path(manifest.directory).iterdir())
        self.assertEqual(files, ["manifest.json"])


class ProvenanceValidationTests(unittest.TestCase):
    """Supplied provenance is checked, because a wrong hash is worse than a missing one."""

    def test_a_hash_that_is_not_a_full_sha256_is_refused(self):
        for value in ("d30725a9", "A" * 64, "g" * 64, "a" * 63):
            with self.subTest(value), self.assertRaises(ManifestError):
                ProvenanceFromR1(model_sha256=value)

    def test_a_full_lowercase_hash_is_accepted_and_absence_stays_allowed(self):
        self.assertEqual(ProvenanceFromR1(model_sha256="a" * 64).model_sha256, "a" * 64)
        self.assertIsNone(ProvenanceFromR1().model_sha256)

    def test_an_unknown_data_role_is_refused(self):
        with self.assertRaises(ManifestError):
            ProvenanceFromR1(data_role="dev")
        for role in ("development", "holdout", "external_transfer"):
            with self.subTest(role):
                self.assertEqual(ProvenanceFromR1(data_role=role).data_role, role)

    def test_a_holdout_run_names_the_decision_7b_fields_it_did_not_record(self):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        manifest = ExperimentManifest(
            run_id="run-1",
            directory=directory,
            config={},
            r1=ProvenanceFromR1(data_role="holdout", model_sha256="a" * 64),
        )
        manifest.freeze()
        unmet = read_manifest(directory)["provenance"]["holdout_preconditions_unmet"]
        self.assertIn("threshold_policy_sha256", unmet)
        self.assertIn("holdout_selection_sha256", unmet)
        self.assertNotIn("model_sha256", unmet)

    def test_a_development_run_is_not_measured_against_the_holdout_preconditions(self):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        manifest = ExperimentManifest(
            run_id="run-1",
            directory=directory,
            config={},
            r1=ProvenanceFromR1(data_role="development"),
        )
        manifest.freeze()
        self.assertEqual(read_manifest(directory)["provenance"]["holdout_preconditions_unmet"], [])


def supplied_r1(**overrides) -> ProvenanceFromR1:
    """Every decision 7b field R1 owns, filled, so only the policy half is under test."""
    fields = {name: "a" * 64 for name in HOLDOUT_PRECONDITIONS if name.endswith("_sha256")}
    fields["feature_schema_version"] = "features-1"
    return ProvenanceFromR1(data_role="holdout", **(fields | overrides))


POLICY = {
    "policy_config_version": POLICY_CONFIG_VERSION,
    "n": 3,
    "lease_seconds": 30.0,
    "max_lease": 300.0,
}


class HoldoutPolicyConfigTests(unittest.TestCase):
    """Decision 7b lists N and the lease beside the hashes; both halves are checked.

    Reported on PR #32 after the first round of fixes: a holdout manifest with all six
    R1 fields and an empty config published `holdout_preconditions_unmet: []`, because
    only the R1 half was checked while the policy half was left to a sentence in a
    README. That is the same shape of gap this card exists to close.
    """

    def unmet(self, config, **overrides) -> list[str]:
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        manifest = ExperimentManifest(
            run_id="holdout-1",
            directory=directory,
            config=config,
            r1=supplied_r1(**overrides),
        )
        manifest.freeze()
        return read_manifest(directory)["provenance"]["holdout_preconditions_unmet"]

    def test_an_empty_config_leaves_the_policy_half_visibly_unmet(self):
        self.assertEqual(self.unmet({}), ["config.policy"])

    def test_a_config_without_a_policy_block_is_unmet(self):
        self.assertEqual(self.unmet({"n": 3, "lease_seconds": 30.0}), ["config.policy"])

    def test_a_partial_policy_block_names_the_parameters_it_is_missing(self):
        unmet = self.unmet({"policy": {"policy_config_version": POLICY_CONFIG_VERSION, "n": 3}})
        self.assertEqual(unmet, ["config.policy.lease_seconds"])

    def test_a_fully_recorded_holdout_run_is_the_only_one_that_reads_as_met(self):
        self.assertEqual(self.unmet({"policy": dict(POLICY)}), [])

    def test_a_policy_block_from_another_contract_version_is_unmet(self):
        self.assertIn(
            "config.policy.policy_config_version",
            self.unmet({"policy": dict(POLICY) | {"policy_config_version": "something-else/9"}}),
        )

    def test_values_that_cannot_describe_the_policy_that_ran_count_as_unrecorded(self):
        cases = (
            ({"n": 0}, "config.policy.n"),
            ({"n": -1}, "config.policy.n"),
            ({"n": 3.0}, "config.policy.n"),  # N counts windows; a float is not a count
            ({"n": True}, "config.policy.n"),
            ({"lease_seconds": 0}, "config.policy.lease_seconds"),
            ({"lease_seconds": -30.0}, "config.policy.lease_seconds"),
            ({"lease_seconds": "30"}, "config.policy.lease_seconds"),
            # A bound below the lease it is recorded with is not the ceiling of this run.
            ({"max_lease": 10.0}, "config.policy.max_lease"),
            ({"max_lease": -1.0}, "config.policy.max_lease"),
        )
        for override, expected in cases:
            with self.subTest(override):
                self.assertIn(expected, self.unmet({"policy": dict(POLICY) | override}))

    def test_max_lease_is_optional_when_it_is_simply_absent(self):
        block = {k: v for k, v in POLICY.items() if k != "max_lease"}
        self.assertEqual(self.unmet({"policy": block}), [])

    def test_a_holdout_run_missing_both_halves_reports_both(self):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        manifest = ExperimentManifest(
            run_id="holdout-1",
            directory=directory,
            config={},
            r1=ProvenanceFromR1(data_role="holdout"),
        )
        manifest.freeze()
        unmet = read_manifest(directory)["provenance"]["holdout_preconditions_unmet"]
        self.assertIn("threshold_policy_sha256", unmet)
        self.assertIn("config.policy", unmet)

    def test_a_development_run_is_not_asked_for_a_policy_block(self):
        directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        manifest = ExperimentManifest(
            run_id="run-1",
            directory=directory,
            config={},
            r1=ProvenanceFromR1(data_role="development"),
        )
        manifest.freeze()
        self.assertEqual(read_manifest(directory)["provenance"]["holdout_preconditions_unmet"], [])


if __name__ == "__main__":
    unittest.main()
