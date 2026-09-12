"""Independent packet expectations for device partition, time and loss bounds."""

import unittest
from dataclasses import replace

from core.schema import Direction, PacketTuple
from gateway.windows import TumblingWindows, WindowCapacityError, WindowError


def packet(ts, device="camera"):
    return PacketTuple(
        ts, device, None, "10.0.0.2", 1234, "192.0.2.1", 80, 6, 2, 40, Direction.EGRESS
    )


class WindowsTests(unittest.TestCase):
    def test_half_open_boundary_and_per_device_partition(self):
        windows = TumblingWindows(0)
        p0, p1, p2 = packet(0, "b"), packet(4.999, "a"), packet(5, "b")
        windows.add(p0)
        windows.advance(p1.timestamp)
        windows.add(p1)
        closed = windows.advance(5)
        self.assertEqual(
            [(w.device_id, w.start, w.end, w.packets) for w in closed],
            [("a", 0, 5, (p1,)), ("b", 0, 5, (p0,))],
        )
        windows.add(p2)
        self.assertEqual(windows.advance(10)[0].packets, (p2,))
        self.assertEqual(windows.advance(10), ())

    def test_no_synthetic_windows_on_idle_or_long_gap(self):
        windows = TumblingWindows(0)
        self.assertEqual(windows.advance(1_000_000), ())
        windows.add(packet(1_000_000))
        result = windows.advance(1_000_100)
        self.assertEqual(len(result), 1)
        self.assertEqual((result[0].start, result[0].end), (1_000_000, 1_000_005))
        self.assertEqual(windows.buffered_packets, 0)

    def test_partial_end_is_not_flushed(self):
        windows = TumblingWindows(0)
        windows.add(packet(1))
        self.assertEqual(windows.advance(4.99), ())
        self.assertEqual(windows.buffered_packets, 1)

    def test_explicit_loss_discards_all_devices_and_recovers_at_boundary(self):
        windows = TumblingWindows(0)
        windows.add(packet(1, "a"))
        windows.add(packet(2, "b"))
        windows.invalidate("capture drop")
        self.assertEqual(windows.buffered_packets, 0)
        with self.assertRaises(WindowError):
            windows.add(packet(3))
        self.assertEqual(windows.advance(5), ())
        self.assertIsNone(windows.invalid_reason)
        windows.add(packet(5))
        self.assertEqual(len(windows.advance(10)), 1)

    def test_each_capacity_limit_invalidates_instead_of_emitting_partial_data(self):
        for limits, second in [
            ({"max_devices": 1}, packet(2, "other")),
            ({"max_packets_per_device": 1}, packet(2)),
            ({"max_packets_total": 1}, packet(2, "other")),
        ]:
            with self.subTest(limits=limits):
                windows = TumblingWindows(0, **limits)
                windows.add(packet(1))
                with self.assertRaises(WindowCapacityError):
                    windows.add(second)
                self.assertEqual(windows.buffered_packets, 0)
                self.assertEqual(windows.advance(5), ())

    def test_backward_watermark_and_late_packets_are_explicit_errors(self):
        for operation in (lambda w: w.advance(1), lambda w: w.add(packet(1))):
            windows = TumblingWindows(0)
            windows.add(packet(2))
            with self.assertRaises(WindowError):
                operation(windows)
            self.assertIsNotNone(windows.invalid_reason)
            self.assertEqual(windows.advance(5), ())

    def test_closed_history_is_not_reopened(self):
        windows = TumblingWindows(0)
        windows.add(packet(1))
        self.assertEqual(len(windows.advance(5)), 1)
        with self.assertRaises(WindowError):
            windows.add(packet(2))
        self.assertEqual(windows.advance(10), ())

    def test_requires_explicit_advance_without_losing_previous_interval(self):
        windows = TumblingWindows(0)
        windows.add(packet(1))
        with self.assertRaises(WindowError):
            windows.add(packet(5))
        self.assertEqual(len(windows.advance(5)), 1)
        windows.add(packet(5))
        self.assertEqual(len(windows.advance(10)), 1)

    def test_equal_timestamps_and_direction_preserved(self):
        windows = TumblingWindows(0)
        packets = tuple(replace(packet(1), direction=d) for d in Direction)
        for p in packets:
            windows.add(p)
        self.assertEqual(windows.advance(5)[0].packets, packets)

    def test_invalid_start_limits_and_clock_values(self):
        for start in (1, -5, float("nan"), float("inf"), True, 1e100):
            with self.subTest(start=start), self.assertRaises(ValueError):
                TumblingWindows(start)
        for limit in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                TumblingWindows(0, max_devices=limit)
        windows = TumblingWindows(0)
        windows.add(packet(1))
        with self.assertRaises(ValueError):
            windows.advance(float("nan"))
        self.assertEqual(windows.buffered_packets, 0)
        self.assertEqual(windows.invalid_reason, "invalid clock value")


if __name__ == "__main__":
    unittest.main()
