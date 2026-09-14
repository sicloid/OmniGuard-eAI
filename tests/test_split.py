import hashlib
import json
import unittest

from model.split import SplitError, WindowGroup, split_by_group


def groups(n_benign: int, n_malicious: int, windows: int = 10) -> list[WindowGroup]:
    out = [WindowGroup(f"benign-{i}", windows, 0) for i in range(n_benign)]
    out += [WindowGroup(f"attack-{i}", windows, windows // 2) for i in range(n_malicious)]
    return out


class DisjointnessTests(unittest.TestCase):
    def test_every_group_lands_in_exactly_one_split(self):
        data = groups(20, 20)
        manifest = split_by_group(data, seed=7)
        parts = (manifest.train, manifest.validation, manifest.test)
        seen = [g for part in parts for g in part]
        self.assertEqual(sorted(seen), sorted(g.group_id for g in data))
        self.assertEqual(len(seen), len(set(seen)))

    def test_split_of_reports_membership(self):
        manifest = split_by_group(groups(6, 6), seed=1)
        for name in ("train", "validation", "test"):
            for group_id in getattr(manifest, name):
                self.assertEqual(manifest.split_of(group_id), name)
        with self.assertRaises(KeyError):
            manifest.split_of("unknown")


class ReproducibilityTests(unittest.TestCase):
    def test_same_seed_gives_identical_manifest_and_hash(self):
        a = split_by_group(groups(20, 20), seed=42)
        b = split_by_group(groups(20, 20), seed=42)
        self.assertEqual(a, b)
        self.assertEqual(a.sha256(), b.sha256())

    def test_input_order_does_not_matter(self):
        data = groups(10, 10)
        self.assertEqual(split_by_group(data, seed=3), split_by_group(list(reversed(data)), seed=3))

    def test_different_seed_changes_assignment(self):
        a = split_by_group(groups(20, 20), seed=1)
        b = split_by_group(groups(20, 20), seed=2)
        self.assertNotEqual(a.test, b.test)
        self.assertNotEqual(a.sha256(), b.sha256())


class StratificationTests(unittest.TestCase):
    def test_each_split_contains_both_classes(self):
        manifest = split_by_group(groups(12, 12), seed=5)
        for name in ("train", "validation", "test"):
            counts = manifest.counts[name]
            with self.subTest(split=name):
                self.assertGreater(counts["malicious_windows"], 0)
                self.assertGreater(counts["windows"] - counts["malicious_windows"], 0)

    def test_fractions_are_approximately_met(self):
        manifest = split_by_group(groups(40, 40), seed=9, validation=0.2, test=0.2)
        total = sum(c["windows"] for c in manifest.counts.values())
        for name, target in (("validation", 0.2), ("test", 0.2), ("train", 0.6)):
            with self.subTest(split=name):
                share = manifest.counts[name]["windows"] / total
                self.assertAlmostEqual(share, target, delta=0.05)

    def test_uneven_group_sizes_still_leave_every_split_non_empty(self):
        """Real IoT-23 window counts: benign 9770/2831/1019, malware 25655/9722/7927."""
        data = [
            WindowGroup("benign-a", 9770, 0),
            WindowGroup("benign-b", 2831, 0),
            WindowGroup("benign-c", 1019, 0),
            WindowGroup("attack-a", 25655, 25651),
            WindowGroup("attack-b", 9722, 8686),
            WindowGroup("attack-c", 7927, 6997),
        ]
        for seed in range(8):
            with self.subTest(seed=seed):
                manifest = split_by_group(data, seed=seed)
                for name in ("train", "validation", "test"):
                    self.assertEqual(len(getattr(manifest, name)), 2, name)
                    self.assertGreater(manifest.counts[name]["malicious_windows"], 0)

    def test_too_few_groups_per_class_is_an_error_not_a_silent_leak(self):
        with self.assertRaises(SplitError):
            split_by_group(groups(10, 2), seed=0)
        with self.assertRaises(SplitError):
            split_by_group(groups(2, 10), seed=0)


class ValidationTests(unittest.TestCase):
    def test_rejects_duplicate_group_ids(self):
        with self.assertRaises(SplitError):
            split_by_group([WindowGroup("benign-0", 10, 0)] + groups(3, 3), seed=0)

    def test_rejects_invalid_fractions(self):
        for kwargs in ({"validation": 0.0}, {"test": 0.0}, {"validation": 0.5, "test": 0.5}):
            with self.subTest(kwargs=kwargs), self.assertRaises(SplitError):
                split_by_group(groups(6, 6), seed=0, **kwargs)

    def test_group_record_validates_counts(self):
        for args in (("", 1, 0), ("g", 0, 0), ("g", 5, 6), ("g", 5, -1), ("g", 5.0, 0)):
            with self.subTest(args=args), self.assertRaises(SplitError):
                WindowGroup(*args)


class ManifestTests(unittest.TestCase):
    def test_json_is_canonical_and_hash_covers_it(self):
        manifest = split_by_group(groups(6, 6), seed=11)
        text = manifest.to_json()
        document = json.loads(text)
        self.assertEqual(document["method"], "stratified-group-hash-v1")
        self.assertEqual(document["seed"], 11)
        self.assertEqual(sorted(document["test"]), document["test"])
        self.assertEqual(manifest.sha256(), hashlib.sha256(text.encode()).hexdigest())


if __name__ == "__main__":
    unittest.main()
