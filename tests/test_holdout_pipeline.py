import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from core.schema import Classification, DetectionResult
from data.holdout.pipeline import (
    SELECTION,
    SPEC,
    HoldoutError,
    capture_metrics,
    download,
    load_spec,
    score,
    verify_hashes,
)

FROZEN = load_spec(SPEC)["frozen"]


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def small_selection(directory: Path) -> tuple[Path, dict]:
    """A copy of the real manifest with tiny sizes, so no real bytes are involved."""
    selection = json.loads(SELECTION.read_text(encoding="utf-8"))
    for pick in selection["selection"]:
        pick["pcap_bytes"] = 8
        pick["label_bytes"] = 4
        pick["pcap_sha256"] = pick["label_sha256"] = None
    path = directory / "selection.json"
    path.write_text(json.dumps(selection), encoding="utf-8")
    return path, selection


def quiet(_line):
    pass


class SpecTests(unittest.TestCase):
    def test_committed_spec_pins_the_frozen_policy(self):
        spec = load_spec(SPEC)
        self.assertEqual((spec["frozen"]["n"], spec["frozen"]["lease_seconds"]), (2, 300))
        self.assertEqual(spec["frozen"]["threshold"], 0.9798815486832)
        scenarios = {p["scenario"] for p in json.loads(SELECTION.read_text())["selection"]}
        self.assertEqual(scenarios, set(spec["capture_topology"]) - {"rule"})

    def test_a_device_outside_its_declared_lan_is_refused(self):
        spec = json.loads(SPEC.read_text(encoding="utf-8"))
        spec["capture_topology"]["CTU-IoT-Malware-Capture-20-1"]["lan_cidr"] = "10.0.0.0/24"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "spec.json"
            path.write_text(json.dumps(spec), encoding="utf-8")
            with self.assertRaises(HoldoutError):
                load_spec(path)


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.selection_path, self.selection = small_selection(self.dir)
        self.urls = []

    def opener(self, sizes=None):
        def fetch(url):
            self.urls.append(url)
            size = (sizes or {}).get(url.rsplit("/", 1)[-1])
            if size is None:
                size = 4 if url.endswith("conn.log.labeled") else 8
            return FakeResponse(b"x" * size)

        return fetch

    def test_hashes_are_recorded_immediately_after_download(self):
        download(self.dir / "root", self.selection_path, opener=self.opener(), log=quiet)
        written = json.loads(self.selection_path.read_text())
        for pick in written["selection"]:
            self.assertEqual(pick["pcap_sha256"], hashlib.sha256(b"x" * 8).hexdigest())
            self.assertEqual(pick["label_sha256"], hashlib.sha256(b"x" * 4).hexdigest())
        self.assertIn("never scored", written["status"])
        self.assertTrue(all(u.startswith(written["source"]["base_url"]) for u in self.urls))

    def test_a_short_download_is_refused_and_leaves_no_file(self):
        pcap = self.selection["selection"][0]["pcap"]
        with self.assertRaises(HoldoutError):
            download(
                self.dir / "root", self.selection_path, opener=self.opener({pcap: 3}), log=quiet
            )
        folder = self.dir / "root" / self.selection["selection"][0]["scenario"]
        self.assertFalse((folder / pcap).exists())
        written = json.loads(self.selection_path.read_text())
        self.assertIsNone(written["selection"][0]["pcap_sha256"])

    def test_a_file_that_changed_after_its_hash_was_recorded_is_refused(self):
        root = self.dir / "root"
        download(root, self.selection_path, opener=self.opener(), log=quiet)
        verify_hashes(root, self.selection_path)
        first = self.selection["selection"][0]
        (root / first["scenario"] / first["pcap"]).write_bytes(b"y" * 8)
        with self.assertRaises(HoldoutError):
            verify_hashes(root, self.selection_path)
        with self.assertRaises(HoldoutError):
            download(root, self.selection_path, opener=self.opener(), log=quiet)

    def test_unrecorded_hashes_block_every_later_step(self):
        with self.assertRaises(HoldoutError):
            verify_hashes(self.dir / "root", self.selection_path)


class OneShotTests(unittest.TestCase):
    def test_scoring_is_refused_once_a_record_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            record = base / "score_record.json"
            record.write_text("{}", encoding="utf-8")
            with self.assertRaises(HoldoutError):
                score(
                    base / "pack", base / "artifact", base / "out", load_spec(SPEC), record=record
                )
            self.assertFalse((base / "out").exists())


def row(start, *, anomalous, malicious):
    value = 0.99 if anomalous else 0.1
    result = DetectionResult(
        "holdout-x",
        start,
        "rf-iot23",
        "0.1.0-seed1-kan19",
        value,
        Classification.ANOMALOUS if anomalous else Classification.NORMAL,
        0.98,
    )
    return (start, result, malicious)


class MetricTests(unittest.TestCase):
    def test_recall_detection_and_benign_windows_are_reported_apart(self):
        rows = [row(0.0, anomalous=False, malicious=False)]
        rows += [row(5.0 * i, anomalous=True, malicious=True) for i in range(1, 11)]
        rows += [row(60.0, anomalous=True, malicious=False)]
        metrics = capture_metrics(rows, FROZEN)
        self.assertEqual(metrics["malicious_windows"], 10)
        self.assertEqual(metrics["window_recall"], 1.0)
        self.assertTrue(metrics["quarantined"])
        # N = 2: the first malicious window starts at 5 s; the second closes at 15 s and
        # is decided at 15.5 s, so the delay from the first malicious window is 10.5 s.
        self.assertEqual(metrics["detection_delay_seconds"], 10.5)
        self.assertEqual(metrics["benign_windows_inside_infected_capture"], 2)
        self.assertEqual(metrics["benign_windows_inside_infected_capture_flagged"], 1)

    def test_isolated_anomalies_never_quarantine_at_n_two(self):
        rows = [row(10.0 * i, anomalous=True, malicious=True) for i in range(10)]
        metrics = capture_metrics(rows, FROZEN)
        self.assertEqual(metrics["window_recall"], 1.0)
        self.assertFalse(metrics["quarantined"])
        self.assertEqual(metrics["malicious_time_blocked_fraction"], 0.0)


class SelectionUntouchedTests(unittest.TestCase):
    def test_the_committed_selection_claims_nothing_before_download(self):
        document = json.loads(SELECTION.read_text(encoding="utf-8"))
        if any(p["pcap_sha256"] for p in document["selection"]):
            self.skipTest("the download has been recorded")
        self.assertIn("never scored", document["status"])


if __name__ == "__main__":
    unittest.main()
