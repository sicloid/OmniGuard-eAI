import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from data.samplepack.build import read_windows
from model.split import split_by_group
from model.train import TrainingError, window_groups

HAVE_SKLEARN = importlib.util.find_spec("sklearn") is not None


@unittest.skipUnless(HAVE_SKLEARN, "scikit-learn is not installed")
class IsolationForestTests(unittest.TestCase):
    def windows(self):
        from tests.test_train import synthetic_windows

        return synthetic_windows(groups_per_class=3, per_group=10)

    def test_only_benign_windows_are_fitted(self):
        from sklearn.ensemble import IsolationForest

        from model.iforest import train_isolation_forest

        windows = self.windows()
        seen = []
        real = IsolationForest.fit

        def spy(self, rows, *args, **kwargs):
            seen.append(len(rows))
            return real(self, rows, *args, **kwargs)

        with mock.patch.object(IsolationForest, "fit", spy):
            train_isolation_forest(windows, seed=0, n_estimators=5)
        self.assertEqual(seen, [sum(not w.malicious for w in windows)])

    def test_no_benign_windows_is_refused(self):
        from model.iforest import train_isolation_forest

        attacks = [w for w in self.windows() if w.malicious]
        with self.assertRaises(TrainingError):
            train_isolation_forest(attacks, seed=0)

    def test_scores_lie_in_the_unit_interval_and_rank_attacks_higher(self):
        from model.iforest import anomaly_scores, train_isolation_forest

        windows = self.windows()
        model = train_isolation_forest(windows, seed=0, n_estimators=50)
        scores = anomaly_scores(model, windows)
        self.assertTrue(all(0 < s <= 1 for s in scores))
        benign = [s for s, w in zip(scores, windows, strict=True) if not w.malicious]
        attack = [s for s, w in zip(scores, windows, strict=True) if w.malicious]
        self.assertGreater(min(attack), sum(benign) / len(benign))


def small_spec(directory: Path, sha: str, **changes) -> Path:
    from model.iforest_run import SPEC

    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    spec |= {"development_pack_windows_sha256": sha, "bootstrap": 0, "seeds": [1, 2]}
    spec["iforest"] = spec["iforest"] | {"n_estimators": 10}
    spec["random_forest_reference"] = spec["random_forest_reference"] | {"n_estimators": 5}
    spec |= changes
    path = directory / "spec.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


@unittest.skipUnless(HAVE_SKLEARN, "scikit-learn is not installed")
class RunnerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        from tests.test_policy_run import write_pack

        self.pack, self.sha = write_pack(self.dir)

    def test_the_run_is_refused_without_a_recorded_approval(self):
        from model.iforest_run import IForestSpecError, run

        spec = small_spec(self.dir, self.sha)
        for approval in ("", "   ", None):
            with self.subTest(approval=approval), self.assertRaises(IForestSpecError):
                run(self.pack, self.dir / "out", spec, approval=approval)
        self.assertFalse((self.dir / "out").exists())

    def test_both_models_are_judged_on_validation_only_and_nothing_else_is_written(self):
        from model import iforest_run
        from model.iforest_run import REPORT_FILENAME, run

        windows = read_windows(self.pack)
        tests = {s: set(split_by_group(window_groups(windows), seed=s).test) for s in (1, 2)}
        scored = []

        def spy(real):
            def wrapper(model, rows, **kwargs):
                scored.append({w.group_id for w in rows})
                return real(model, rows, **kwargs)

            return wrapper

        fitted = []
        real_fit = iforest_run.train_isolation_forest

        def fit_spy(rows, **kwargs):
            fitted.append({w.group_id for w in rows})
            return real_fit(rows, **kwargs)

        with (
            mock.patch.object(iforest_run, "train_isolation_forest", fit_spy),
            mock.patch.object(iforest_run, "anomaly_scores", spy(iforest_run.anomaly_scores)),
            mock.patch.object(iforest_run, "rf_scores", spy(iforest_run.rf_scores)),
        ):
            report = run(
                self.pack,
                self.dir / "out",
                small_spec(self.dir, self.sha),
                approval="test: synthetic pack",
            )
        for groups, seed in zip(scored, [1, 1, 2, 2], strict=True):
            self.assertFalse(groups & tests[seed])
        infected = {g.group_id for g in window_groups(windows) if g.malicious_windows}
        self.assertTrue(fitted and all(groups and not groups & infected for groups in fitted))
        self.assertEqual(report["approval"], "test: synthetic pack")
        self.assertEqual(report["evaluated_split"], "validation")
        for entry in report["seeds"]:
            models = [r["model"] for r in entry["results"]]
            self.assertEqual(models, ["isolation_forest", "random_forest"])
            for result in entry["results"]:
                self.assertIn(result["status"], ("calibrated", "no_threshold"))
        self.assertEqual(sorted(p.name for p in (self.dir / "out").iterdir()), [REPORT_FILENAME])

    def test_a_pack_other_than_the_declared_one_is_refused(self):
        from model.baseline_run import PackIntegrityError
        from model.iforest_run import run

        spec = small_spec(self.dir, "0" * 64)
        with self.assertRaises(PackIntegrityError):
            run(self.pack, self.dir / "out", spec, approval="test")

    def test_spec_rules_are_enforced(self):
        from model.iforest_run import IForestSpecError, load_spec

        bad = (
            {"selected_on": "test"},
            {"seeds": []},
            {"seeds": [1, 1]},
            {"hypothesis": " "},
            {"iforest": {"n_estimators": 0}},
            {"random_forest_reference": None},
            {"max_window_fpr": -0.1},
            {"feature_schema_version": "features-0"},
        )
        for changes in bad:
            with self.subTest(changes=changes), self.assertRaises(IForestSpecError):
                load_spec(small_spec(self.dir, self.sha, **changes))

    def test_committed_spec_is_valid(self):
        from model.iforest_run import SPEC, load_spec

        spec = load_spec(SPEC)
        self.assertEqual(spec["max_window_fpr"], 0.01)
        self.assertEqual(spec["selected_on"], "validation")


if __name__ == "__main__":
    unittest.main()
