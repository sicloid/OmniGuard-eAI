import importlib.util
import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.features import FEATURE_ORDER, extract_features
from core.schema import Direction, PacketTuple
from data.samplepack.build import read_windows
from model.ablation import (
    CANDIDATE,
    DIAGNOSTIC,
    FEATURE_GROUPS,
    FULL,
    REFERENCE,
    AblationError,
    FeatureSet,
    SetResult,
    candidate_sets,
    select_compact,
)
from model.ablation_cost import (
    extract_groups,
    groups_for,
    packet_windows,
    time_extraction,
    time_extractor,
)
from model.split import split_by_group
from model.train import TrainingError, feature_matrix, window_groups

HAVE_SKLEARN = importlib.util.find_spec("sklearn") is not None


def pkt(ts, *, dst="198.51.100.1", dport=443, proto=6, flags=0x02, length=60, egress=True):
    return PacketTuple(
        ts,
        "cam-1",
        None,
        "192.168.1.2",
        None if dport is None else 50000,
        dst,
        dport,
        proto,
        flags if proto == 6 else 0,
        length,
        Direction.EGRESS if egress else Direction.LOCAL,
    )


def random_window(rng: random.Random, start: float) -> list[PacketTuple]:
    packets = []
    for _ in range(rng.randint(1, 40)):
        proto = rng.choice((6, 17, 1, 58))
        packets.append(
            pkt(
                start + rng.random() * 4.99,
                dst=f"203.0.113.{rng.randint(1, 6)}",
                dport=None if proto in (1, 58) else rng.choice((22, 80, 443, 23)),
                proto=proto,
                flags=rng.choice((0x02, 0x12, 0x04, 0x10, 0x14)),
                length=rng.randint(40, 1500),
                egress=rng.random() > 0.2,
            )
        )
    return packets


class CandidateSetTests(unittest.TestCase):
    def test_groups_partition_the_catalogue(self):
        columns = sorted(c for cols in FEATURE_GROUPS.values() for c in cols)
        self.assertEqual(columns, list(range(len(FEATURE_ORDER))))

    def test_matrix_is_declared_and_ordered(self):
        sets = candidate_sets()
        names = [s.name for s in sets]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(sets[0], FeatureSet(FULL, tuple(range(14)), REFERENCE))
        roles = [s.role for s in sets]
        self.assertEqual(roles.count(CANDIDATE), 4 + 6 + 4)
        self.assertEqual(roles.count(DIAGNOSTIC), len(FEATURE_ORDER))
        for s in sets:
            self.assertEqual(list(s.columns), sorted(set(s.columns)))
        by_name = {s.name: s for s in sets}
        self.assertEqual(
            by_name["only:protocol"].features, ("tcp_share", "udp_share", "icmp_share")
        )
        self.assertNotIn("pkt_count", by_name["without:volume"].features)
        self.assertEqual(len(by_name["pair:volume+connection"].columns), 8)
        self.assertNotIn("rst_share", by_name["drop:rst_share"].features)


class GroupExtractionTests(unittest.TestCase):
    def test_split_extraction_reproduces_the_runtime_extractor_exactly(self):
        rng = random.Random(7)
        for i in range(200):
            start = 5.0 * i
            window = random_window(rng, start)
            vector = extract_features("cam-1", start, window)
            values = extract_groups(window, FEATURE_GROUPS)
            if vector is None:
                self.assertEqual(values, {})
                continue
            self.assertEqual([values[c] for c in range(14)], list(vector.values))

    def test_a_subset_runs_every_group_it_touches_and_no_other(self):
        self.assertEqual(groups_for((0, 13)), ("volume", "connection"))
        window = [pkt(1.0), pkt(2.0, proto=17, dport=53)]
        self.assertEqual(set(extract_groups(window, ("protocol",))), {7, 8, 9})

    def test_timing_reports_the_groups_it_priced(self):
        windows = [[pkt(1.0)], [pkt(6.0)]]
        timing = time_extraction(windows, (7,), repeats=2)
        self.assertEqual((timing["groups"], timing["windows"]), (["protocol"], 2))
        self.assertIn("excludes", timing["measures"])
        with self.assertRaises(ValueError):
            time_extraction([], (7,), repeats=1)

    def test_the_full_extractor_is_timed_separately(self):
        rng = random.Random(3)
        windows = [w for w in (random_window(rng, 5.0 * i) for i in range(60)) if w]
        groups = time_extraction(windows, tuple(range(14)), repeats=5)
        whole = time_extractor(windows, repeats=5)
        self.assertIn("extract_features", whole["measures"])
        self.assertEqual(whole["windows"], groups["windows"])
        # These are independent wall-clock samples. Scheduler noise can reverse the
        # ordering even when the full extractor does more work (macOS CI, 19 Sep).
        # Verify both paths were measured, not a relative micro-benchmark value.
        self.assertGreater(whole["ns_per_window_min"], 0)
        self.assertGreater(groups["ns_per_window_min"], 0)
        with self.assertRaises(ValueError):
            time_extractor([], repeats=1)

    def test_packet_windows_stop_at_the_limit_and_skip_non_egress(self):
        stream = [pkt(1.0), pkt(2.0, egress=False), pkt(6.0), pkt(11.0), pkt(12.0)]
        consumed = []

        def packets():
            for p in stream:
                consumed.append(p)
                yield p

        windows = packet_windows(packets(), 2)
        self.assertEqual([[p.timestamp for p in w] for w in windows], [[1.0], [6.0]])
        self.assertEqual(len(consumed), 4)  # stopped at the first packet of window three
        self.assertEqual(len(packet_windows(iter(stream), 10)), 3)
        with self.assertRaises(ValueError):
            packet_windows(iter(stream), 0)


def result(name, seed, recall):
    policy = None if recall is None else {"metrics": {"recall": recall}, "threshold": 0.5}
    status = "no_threshold" if recall is None else "calibrated"
    return SetResult(name, seed, status, {}, 0.0, None, policy=policy)


class SelectionTests(unittest.TestCase):
    sets = [
        FeatureSet(FULL, tuple(range(14)), REFERENCE),
        FeatureSet("small", (0, 1, 2), CANDIDATE),
        FeatureSet("tiny", (0,), CANDIDATE),
        FeatureSet("other", (4, 5, 6), CANDIDATE),
        FeatureSet("drop:x", tuple(range(13)), DIAGNOSTIC),
    ]

    def outcome(self, recalls, tolerance=0.02):
        results = {
            name: [result(name, seed, r) for seed, r in zip((1, 2), values, strict=True)]
            for name, values in recalls.items()
        }
        return select_compact(self.sets, results, tolerance=tolerance)

    def test_fewest_features_within_tolerance_on_every_seed_wins(self):
        decision = self.outcome(
            {
                FULL: (0.95, 0.90),
                "small": (0.94, 0.89),
                "tiny": (0.99, 0.80),  # better on seed 1 but short on seed 2
                "other": (0.96, 0.91),
                "drop:x": (0.99, 0.99),  # diagnostics never compete
            }
        )
        self.assertEqual(decision["status"], "selected")
        self.assertEqual(decision["finalist"], "other")  # ties on size go to higher mean
        self.assertEqual(decision["verdicts"]["tiny"]["below_tolerance_seeds"], [2])
        self.assertNotIn("drop:x", decision["verdicts"])

    def test_a_set_without_a_threshold_on_any_seed_does_not_qualify(self):
        decision = self.outcome(
            {
                FULL: (0.95, 0.90),
                "small": (0.95, 0.90),
                "tiny": (0.99, None),
                "other": (0.5, 0.5),
            }
        )
        self.assertEqual(decision["finalist"], "small")
        self.assertEqual(decision["verdicts"]["tiny"]["no_threshold_seeds"], [2])

    def test_no_reference_means_no_finalist(self):
        decision = self.outcome(
            {FULL: (0.95, None), "small": (0.9, 0.9), "tiny": (0.9, 0.9), "other": (0.9, 0.9)}
        )
        self.assertEqual((decision["status"], decision["finalist"]), ("no_reference", None))

    def test_nothing_within_tolerance_is_reported_not_relaxed(self):
        decision = self.outcome(
            {FULL: (0.95, 0.90), "small": (0.5, 0.5), "tiny": (0.5, 0.5), "other": (0.5, 0.5)}
        )
        self.assertEqual((decision["status"], decision["finalist"]), ("no_compact_set", None))

    def test_bad_tolerance_or_missing_seed_is_refused(self):
        for tolerance in (True, -0.1, 1.0, "0.02"):
            with self.subTest(tolerance=tolerance), self.assertRaises(AblationError):
                self.outcome({FULL: (0.9, 0.9)}, tolerance=tolerance)
        results = {FULL: [result(FULL, 1, 0.9), result(FULL, 2, 0.9)]}
        results |= {n: [result(n, 1, 0.9)] for n in ("small", "tiny", "other")}
        with self.assertRaises(AblationError):
            select_compact(self.sets, results, tolerance=0.02)


class ColumnTests(unittest.TestCase):
    def windows(self):
        from tests.test_train import synthetic_windows

        return synthetic_windows(groups_per_class=3, per_group=5)

    def test_columns_select_a_subset_in_catalogue_order(self):
        windows = self.windows()
        full = feature_matrix(windows)
        self.assertEqual(feature_matrix(windows, columns=(0, 10)), [[r[0], r[10]] for r in full])
        self.assertEqual(feature_matrix(windows, columns=tuple(range(14))), full)

    def test_bad_columns_are_refused(self):
        for columns in ((), (10, 0), (0, 0), (14,), (-1,), (True,)):
            with self.subTest(columns=columns), self.assertRaises(TrainingError):
                feature_matrix(self.windows(), columns=columns)

    @unittest.skipUnless(HAVE_SKLEARN, "scikit-learn is not installed")
    def test_scoring_with_a_different_width_is_refused(self):
        from model.train import rf_scores, train_random_forest

        windows = self.windows()
        model = train_random_forest(windows, seed=0, n_estimators=3, columns=(0, 10))
        self.assertEqual(len(rf_scores(model, windows, columns=(0, 10))), len(windows))
        with self.assertRaises(TrainingError):
            rf_scores(model, windows)

    @unittest.skipUnless(HAVE_SKLEARN, "scikit-learn is not installed")
    def test_scoring_a_different_subset_of_the_same_width_is_refused(self):
        from model.train import rf_scores, train_random_forest

        windows = self.windows()
        volume, connection = (0, 1, 2, 3), (10, 11, 12, 13)
        model = train_random_forest(windows, seed=0, n_estimators=3, columns=volume)
        with self.assertRaises(TrainingError):
            rf_scores(model, windows, columns=connection)

    @unittest.skipUnless(HAVE_SKLEARN, "scikit-learn is not installed")
    def test_a_full_catalogue_forest_carries_no_subset_tag(self):
        from model.train import rf_scores, train_random_forest

        # Tagging every forest would change the bytes of artifacts whose model_sha256
        # is already pinned (KAN-18/19), so only subsets are recorded.
        windows = self.windows()
        model = train_random_forest(windows, seed=0, n_estimators=3)
        self.assertFalse(hasattr(model, "omniguard_columns"))
        self.assertEqual(len(rf_scores(model, windows)), len(windows))


def quiet(_line):
    pass


@unittest.skipUnless(HAVE_SKLEARN, "scikit-learn is not installed")
class RunnerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        from tests.test_policy_run import write_pack

        self.pack, self.sha = write_pack(self.dir)

    def spec(self, **changes) -> Path:
        from model.ablation_run import SPEC

        spec = json.loads(SPEC.read_text(encoding="utf-8"))
        spec |= {
            "development_pack_windows_sha256": self.sha,
            "n_estimators": 5,
            "bootstrap": 0,
            "seeds": [1, 2],
            "kan19_reference_threshold": None,
        }
        spec["cost"] = spec["cost"] | {"timing_captures": [], "inference_rows": 5}
        spec |= changes
        path = self.dir / "spec.json"
        path.write_text(json.dumps(spec), encoding="utf-8")
        return path

    def test_run_reports_every_set_on_validation_and_never_scores_test(self):
        from model import ablation
        from model.ablation_run import REPORT_FILENAME, run

        windows = read_windows(self.pack)
        tests = {
            seed: set(split_by_group(window_groups(windows), seed=seed).test) for seed in (1, 2)
        }
        scored = []
        real = ablation.rf_scores

        def spy(model, rows, **kwargs):
            scored.append({w.group_id for w in rows})
            return real(model, rows, **kwargs)

        with mock.patch.object(ablation, "rf_scores", spy):
            report = run(self.pack, self.dir / "out", self.spec(), log=quiet)
        for groups, seed in zip(scored, [1, 2] * len(candidate_sets()), strict=True):
            self.assertFalse(groups & tests[seed])
        self.assertEqual(report["evaluated_split"], "validation")
        self.assertEqual(len(report["sets"]), len(candidate_sets()))
        self.assertIn(report["selection"]["status"], ("selected", "no_compact_set"))
        self.assertEqual(report["timing_sample"]["status"], "skipped")
        self.assertIsNone(report["full_extractor"])
        self.assertIn("inference", report["sets"][0]["cost"])
        self.assertTrue((self.dir / "out" / REPORT_FILENAME).is_file())

    def test_an_existing_run_directory_is_refused(self):
        from model.ablation_run import run

        (self.dir / "out").mkdir()
        with self.assertRaises(FileExistsError):
            run(self.pack, self.dir / "out", self.spec(), log=quiet)

    def test_a_pack_other_than_the_declared_one_is_refused(self):
        from model.ablation_run import run
        from model.baseline_run import PackIntegrityError

        spec = self.spec(development_pack_windows_sha256="0" * 64)
        with self.assertRaises(PackIntegrityError):
            run(self.pack, self.dir / "out", spec, log=quiet)

    def test_timing_captures_outside_the_train_split_are_refused_before_any_output(self):
        from model.ablation_run import AblationSpecError, run

        split = split_by_group(window_groups(read_windows(self.pack)), seed=1)
        spec = json.loads(self.spec().read_text(encoding="utf-8"))
        spec["cost"]["timing_captures"] = [split.validation[0]]
        path = self.dir / "timing.json"
        path.write_text(json.dumps(spec), encoding="utf-8")
        with self.assertRaises(AblationSpecError):
            run(self.pack, self.dir / "out", path, log=quiet)
        self.assertFalse((self.dir / "out").exists())

    def test_spec_rules_are_enforced(self):
        from model.ablation_run import AblationSpecError, load_spec

        bad = (
            {"selected_on": "test"},
            {"max_window_fpr": True},
            {"seeds": []},
            {"seeds": [1, 1]},
            {"cost_seed": 9},
            {"compact_rule": {"tolerance": 1.5}},
            {"feature_schema_version": "features-0"},
            {"n_estimators": 0},
            {"kan19_reference_threshold": "0.9"},
        )
        for changes in bad:
            with self.subTest(changes=changes), self.assertRaises(AblationSpecError):
                load_spec(self.spec(**changes))

    def test_committed_spec_is_valid(self):
        from model.ablation_run import SPEC, load_spec

        spec = load_spec(SPEC)
        self.assertEqual(spec["max_window_fpr"], 0.01)
        self.assertIn(spec["cost_seed"], spec["seeds"])


if __name__ == "__main__":
    unittest.main()
