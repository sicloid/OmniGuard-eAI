"""Capture, health, window and shared-extractor integration expectations."""

import unittest

from core.features import extract_features
from core.schema import Direction, PacketTuple
from gateway.pipeline import WindowFeaturePipeline
from gateway.windows import WindowError


def packet(ts, *, device="camera", direction=Direction.EGRESS, length=60):
    return PacketTuple(
        ts,
        device,
        None,
        "10.203.1.2",
        39028,
        "10.203.2.2",
        39027,
        17,
        0,
        length,
        direction,
    )


class Capture:
    def __init__(self, items):
        self.items = iter(items)

    def read(self, timeout=0.25):
        item = next(self.items)
        if isinstance(item, Exception):
            raise item
        return item


class PipelineTests(unittest.TestCase):
    def test_old_window_never_emits_after_long_gap(self):
        pipeline = WindowFeaturePipeline(100)
        pipeline.ingest(packet(101))
        self.assertEqual(pipeline.ingest(packet(1000)), ())
        self.assertEqual(pipeline.status, "stale")
        self.assertGreater(pipeline.reset_generation, 0)
        self.assertEqual(len(pipeline.advance(1005)), 1)

    def test_initial_partial_packets_are_discarded(self):
        pipeline = WindowFeaturePipeline(105)
        self.assertEqual(pipeline.ingest(packet(104)), ())
        self.assertEqual(pipeline.buffered_packets, 0)
        pipeline.ingest(packet(105))
        self.assertEqual(pipeline.advance(110)[0].values[0], 1)

    def test_explicit_idle_progress_closes_then_reports_empty(self):
        class Progress:
            def read_progress(self, timeout):
                return None, 105

        pipeline = WindowFeaturePipeline(100)
        pipeline.ingest(packet(101))
        self.assertEqual(len(pipeline.capture_once(Progress())), 1)
        self.assertEqual(pipeline.advance(110), ())
        self.assertEqual(pipeline.status, "empty")
        self.assertEqual(pipeline.reset_generation, 1)

    def test_shutdown_loss_discards_pending_and_propagates(self):
        class BrokenClose:
            def close(self):
                raise OSError("final drops")

        pipeline = WindowFeaturePipeline(100)
        pipeline.ingest(packet(101))
        with self.assertRaises(OSError):
            pipeline.close_capture(BrokenClose())
        self.assertEqual(pipeline.buffered_packets, 0)
        self.assertEqual(pipeline.status, "invalid")
        with self.assertRaises(ValueError):
            pipeline.advance(105)

    def test_capture_window_extractor_matches_offline_result(self):
        packets = (packet(100.1), packet(102.0, length=80), packet(105.1))
        pipeline = WindowFeaturePipeline(100)
        capture = Capture((packets[0], None, packets[1], packets[2]))

        self.assertEqual(pipeline.capture_once(capture), ())
        self.assertEqual(pipeline.capture_once(capture), ())
        self.assertEqual(pipeline.buffered_packets, 1)
        self.assertEqual(pipeline.capture_once(capture), ())
        (live_vector,) = pipeline.capture_once(capture)

        self.assertEqual(live_vector, extract_features("camera", 100, packets[:2]))
        self.assertEqual(pipeline.buffered_packets, 1)

    def test_idle_and_non_egress_do_not_create_benign_vectors(self):
        pipeline = WindowFeaturePipeline(100)
        capture = Capture((None, packet(101, direction=Direction.LOCAL)))

        self.assertEqual(pipeline.capture_once(capture), ())
        self.assertEqual(pipeline.watermark, 100)
        self.assertEqual(pipeline.capture_once(capture), ())
        self.assertEqual(pipeline.advance(105), ())

    def test_capture_failure_invalidates_whole_interval_and_recovers(self):
        pipeline = WindowFeaturePipeline(100)
        capture = Capture((packet(101), OSError("capture failed")))
        pipeline.capture_once(capture)

        with self.assertRaises(OSError):
            pipeline.capture_once(capture)
        self.assertEqual(pipeline.buffered_packets, 0)
        self.assertEqual(pipeline.invalid_reason, "capture failure: OSError")
        with self.assertRaises(WindowError):
            pipeline.ingest(packet(102))

        self.assertEqual(pipeline.advance(105), ())
        self.assertIsNone(pipeline.invalid_reason)
        pipeline.ingest(packet(105.1))
        self.assertEqual(len(pipeline.advance(110)), 1)

    def test_multi_device_windows_are_extracted_independently(self):
        pipeline = WindowFeaturePipeline(100)
        pipeline.ingest(packet(101, device="b"))
        pipeline.ingest(packet(102, device="a", length=70))

        vectors = pipeline.advance(105)
        self.assertEqual([v.device_id for v in vectors], ["a", "b"])
        self.assertEqual([v.values[0] for v in vectors], [1.0, 1.0])


if __name__ == "__main__":
    unittest.main()
