"""Bounded live ordering preserves timestamps and refuses unprovable progress."""

import unittest

from core.schema import Direction, PacketTuple
from sources.live import CaptureError
from sources.reorder import BoundedReorderCapture


def packet(timestamp):
    return PacketTuple(
        timestamp,
        "camera",
        None,
        "10.203.1.2",
        1234,
        "10.203.2.2",
        9999,
        17,
        0,
        32,
        Direction.EGRESS,
    )


class Source:
    def __init__(self, results):
        self.results = iter(results)
        self.closed = False

    def read_progress(self, timeout):
        result = next(self.results)
        if isinstance(result, Exception):
            raise result
        return result

    def close(self):
        self.closed = True


class ReorderTests(unittest.TestCase):
    def test_microsecond_inversion_is_sorted_without_changing_timestamps(self):
        source = Source(
            [
                (packet(100.002), None),
                (packet(100.001), None),
                (packet(100.005), None),
                (None, 105.0),
            ]
        )
        ordered = BoundedReorderCapture(source)
        self.assertEqual(ordered.read_progress()[0].timestamp, 100.001)
        self.assertEqual(ordered.read_progress()[0].timestamp, 100.002)
        self.assertEqual(ordered.read_progress()[0].timestamp, 100.005)
        self.assertEqual(ordered.read_progress(), (None, 105.0))
        self.assertEqual(ordered.stats["reordered_packets"], 1)
        self.assertAlmostEqual(ordered.stats["max_inversion_seconds"], 0.001)
        self.assertEqual(ordered.stats["buffer_high_water"], 3)
        ordered.close()
        self.assertTrue(source.closed)

    def test_packet_behind_emitted_watermark_fails_closed(self):
        source = Source(
            [
                (packet(100.0), None),
                (None, 100.1),
                (packet(100.05), None),
            ]
        )
        ordered = BoundedReorderCapture(source)
        self.assertEqual(ordered.read_progress()[0].timestamp, 100.0)
        self.assertEqual(ordered.read_progress(), (None, 100.1))
        with self.assertRaises(CaptureError):
            ordered.read_progress()
        self.assertAlmostEqual(ordered.stats["excess_lateness_seconds"], 0.05)
        with self.assertRaises(CaptureError):
            ordered.read_progress()

    def test_socket_failure_discards_pending_and_latches_failure(self):
        source = Source([(packet(100.001), None), OSError("socket lost")])
        ordered = BoundedReorderCapture(source)
        with self.assertRaises(OSError):
            ordered.read_progress()
        with self.assertRaises(CaptureError):
            ordered.read_progress()

    def test_capacity_is_a_hard_observation_failure(self):
        source = Source([(packet(100.0), None), (packet(100.001), None)])
        ordered = BoundedReorderCapture(source, capacity=1)
        with self.assertRaises(CaptureError):
            ordered.read_progress()

    def test_filtered_frame_does_not_advance_watermark(self):
        source = Source([(None, None), (packet(100.0), None), (None, 101.0)])
        ordered = BoundedReorderCapture(source)
        self.assertEqual(ordered.read_progress()[0].timestamp, 100.0)
        self.assertEqual(ordered.read_progress(), (None, 101.0))


if __name__ == "__main__":
    unittest.main()
