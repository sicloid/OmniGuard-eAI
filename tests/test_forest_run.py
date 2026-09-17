import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from data.samplepack.build import read_windows
from model.ablation import SetResult
from model.forest_run import ForestSpecError, select_smallest
from model.split import split_by_group
from model.train import window_groups

HAVE_SKLEARN = importlib.util.find_spec("sklearn") is not None


def result(trees, seed, recall):
    policy = None if recall is None else {"metrics": {"recall": recall}, "threshold": 0.5}
    status = "no_threshold" if recall is None else "calibrated"
    return SetResult(f"trees={trees}", seed, status, {}, 0.0, None, policy=policy)


def results(table):
    return {
        trees: [result(trees, seed, r) for seed, r in zip((1, 2), recalls, strict=True)]
        for trees, recalls in table.items()
    }


class SelectionTests(unittest.TestCase):
    def test_smallest_forest_within_tolerance_on_every_seed_is_named(self):
        decision = select_smallest(
            results({10: (0.95, 0.80), 25: (0.94, 0.89), 50: (0.99, 0.95), 200: (0.95, 0.90)}),
            200,
            0.02,
        )
        self.assertEqual((decision["status"], decision["smallest"]), ("selected", 25))
        self.assertEqual(decision["verdicts"]["10"]["below_tolerance_seeds"], [2])
        self.assertTrue(decision["verdicts"]["200"]["qualifies"])

    def test_a_forest_without_a_threshold_does_not_qualify(self):
        decision = select_smallest(results({10: (None, 0.9), 200: (0.9, 0.9)}), 200, 0.02)
        self.assertEqual(decision["smallest"], 200)
        self.assertEqual(decision["verdicts"]["10"]["no_threshold_seeds"], [1])

    def test_no_reference_names_nothing(self):
        decision = select_smallest(results({10: (0.9, 0.9), 200: (0.9, None)}), 200, 0.02)
        self.assertEqual((decision["status"], decision["smallest"]), ("no_reference", None))

    def test_a_size_missing_a_seed_is_refused(self):
        table = results({200: (0.9, 0.9)})
        table[10] = [result(10, 1, 0.9)]
        with self.assertRaises(ForestSpecError):
            select_smallest(table, 200, 0.02)


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
        from model.forest_run import SPEC

        spec = json.loads(SPEC.read_text(encoding="utf-8"))
        spec |= {
            "development_pack_windows_sha256": self.sha,
            "bootstrap": 0,
            "tree_counts": [2, 5],
            "reference_trees": 5,
            "seeds": [1, 2],
            "kan19_reference_threshold": None,
        }
        spec["cost"] = {"inference_rows": 3, "batch_rows": 4, "batch_repeats": 2}
        spec |= changes
        path = self.dir / "spec.json"
        path.write_text(json.dumps(spec), encoding="utf-8")
        return path

    def test_run_scores_validation_only_and_reports_cost_per_size(self):
        from model import ablation
        from model.forest_run import REPORT_FILENAME, run

        windows = read_windows(self.pack)
        tests = {s: set(split_by_group(window_groups(windows), seed=s).test) for s in (1, 2)}
        scored, real = [], ablation.rf_scores

        def spy(model, rows, **kwargs):
            scored.append({w.group_id for w in rows})
            return real(model, rows, **kwargs)

        with mock.patch.object(ablation, "rf_scores", spy):
            report = run(self.pack, self.dir / "out", self.spec(), log=quiet)
        for groups, seed in zip(scored, [1, 2, 1, 2], strict=True):
            self.assertFalse(groups & tests[seed])
        self.assertEqual([f["trees"] for f in report["forests"]], [2, 5])
        self.assertIn(report["status"], ("selected", "no_reference"))
        for entry in report["forests"]:
            self.assertEqual(entry["cost"]["batched"]["batch_rows"], 4)
            self.assertGreater(entry["cost"]["model"]["tree_nodes"], 0)
        self.assertTrue((self.dir / "out" / REPORT_FILENAME).is_file())

    def test_existing_output_or_foreign_pack_is_refused(self):
        from model.baseline_run import PackIntegrityError
        from model.forest_run import run

        foreign = self.spec(development_pack_windows_sha256="0" * 64)
        with self.assertRaises(PackIntegrityError):
            run(self.pack, self.dir / "a", foreign, log=quiet)
        (self.dir / "b").mkdir()
        with self.assertRaises(FileExistsError):
            run(self.pack, self.dir / "b", self.spec(), log=quiet)

    def test_spec_rules_are_enforced(self):
        from model.forest_run import load_spec

        bad = (
            {"selected_on": "test"},
            {"tree_counts": [5, 2]},
            {"tree_counts": [0, 5]},
            {"tree_counts": [2, 2]},
            {"reference_trees": 7},
            {"reference_trees": True},
            {"seeds": []},
            {"cost_seed": 9},
            {"smallest_rule": {"tolerance": -0.1}},
            {"cost": {"inference_rows": 0, "batch_rows": 1, "batch_repeats": 1}},
            {"max_window_fpr": 2},
        )
        for changes in bad:
            with self.subTest(changes=changes), self.assertRaises(ForestSpecError):
                load_spec(self.spec(**changes))

    def test_committed_spec_is_valid(self):
        from model.forest_run import SPEC, load_spec

        spec = load_spec(SPEC)
        self.assertEqual(spec["reference_trees"], 200)
        self.assertEqual(spec["max_window_fpr"], 0.01)


if __name__ == "__main__":
    unittest.main()
