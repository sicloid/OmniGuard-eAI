"""Wrong-domain clock arithmetic must fail, not produce a plausible number.

R2's objection on 12 September 2026, recorded on KAN-42: `NewType` is erased at
runtime and ruff is not a type checker, so a `NewType`-based scheme would let
`UnixSeconds - MonotonicSeconds` run and return a float. These are the negative tests
that objection asked for. They are the point of the module, not an extra.
"""

import unittest

from measure.clocks import (
    Clock,
    ClockDomainError,
    Duration,
    ManualClock,
    MonotonicInstant,
    UnixInstant,
    WallOffset,
)


class WrongDomainArithmeticIsRejected(unittest.TestCase):
    def setUp(self):
        self.unix = UnixInstant(1_000_000.0)
        self.mono = MonotonicInstant(10.0)
        self.duration = Duration(2.0)
        self.offset = WallOffset(2.0)

    def test_subtracting_a_monotonic_reading_from_a_wall_reading_is_refused(self):
        with self.assertRaises(ClockDomainError):
            self.unix - self.mono

    def test_subtracting_a_wall_reading_from_a_monotonic_reading_is_refused(self):
        with self.assertRaises(ClockDomainError):
            self.mono - self.unix

    def test_a_duration_cannot_be_added_to_a_wall_reading(self):
        # This would assert the wall clock advanced by exactly the measured amount.
        with self.assertRaises(ClockDomainError):
            self.unix + self.duration

    def test_a_wall_offset_cannot_be_combined_with_anything(self):
        for other in (self.offset, self.duration, 1.0):
            with self.subTest(other=type(other).__name__):
                with self.assertRaises(ClockDomainError):
                    self.offset + other
                with self.assertRaises(ClockDomainError):
                    self.offset - other

    def test_a_duration_cannot_absorb_a_wall_offset(self):
        for operation in ("__add__", "__sub__", "__lt__", "__ge__"):
            with self.subTest(operation):
                with self.assertRaises(ClockDomainError):
                    getattr(self.duration, operation)(self.offset)

    def test_a_duration_cannot_be_compared_to_a_bare_number(self):
        # A bare float has no domain: 3.0 of what, measured against which clock?
        with self.assertRaises(ClockDomainError):
            self.duration.__lt__(3.0)

    def test_raw_floats_are_not_accepted_as_instants(self):
        with self.assertRaises(ClockDomainError):
            self.mono - 5.0

    def test_monotonic_readings_from_different_sources_do_not_subtract(self):
        # A stored reading from an earlier process is not comparable to a current one.
        other_boot = MonotonicInstant(5.0, source="monotonic:other-process")
        with self.assertRaises(ClockDomainError):
            self.mono - other_boot

    def test_non_numeric_and_non_finite_readings_are_refused(self):
        for value in (float("nan"), float("inf"), True, "10", None):
            with self.subTest(value=repr(value)):
                with self.assertRaises(ClockDomainError):
                    MonotonicInstant(value)


class RightDomainArithmeticWorks(unittest.TestCase):
    def test_two_monotonic_readings_give_a_duration(self):
        elapsed = MonotonicInstant(12.5) - MonotonicInstant(10.0)
        self.assertIsInstance(elapsed, Duration)
        self.assertAlmostEqual(elapsed.seconds, 2.5)
        self.assertAlmostEqual(elapsed.milliseconds, 2500.0)

    def test_two_wall_readings_give_a_wall_offset_and_not_a_duration(self):
        offset = UnixInstant(1_000_010.0) - UnixInstant(1_000_000.0)
        self.assertIsInstance(offset, WallOffset)
        self.assertNotIsInstance(offset, Duration)

    def test_a_backwards_wall_offset_is_representable_rather_than_an_error(self):
        # The point of the type: make the backwards jump visible instead of hiding it.
        offset = UnixInstant(1_000_000.0) - UnixInstant(1_000_010.0)
        self.assertEqual(offset.seconds, -10.0)

    def test_a_negative_duration_is_refused(self):
        with self.assertRaises(ClockDomainError):
            MonotonicInstant(10.0) - MonotonicInstant(12.0)

    def test_durations_add_and_compare_with_each_other(self):
        self.assertEqual((Duration(1.0) + Duration(2.0)).seconds, 3.0)
        self.assertTrue(Duration(1.0) < Duration(2.0))


class ClockBehaviour(unittest.TestCase):
    def test_the_real_clock_returns_the_two_domains_as_distinct_types(self):
        clock = Clock()
        self.assertIsInstance(clock.now(), UnixInstant)
        self.assertIsInstance(clock.monotonic(), MonotonicInstant)

    def test_a_wall_clock_jump_does_not_change_a_measured_duration(self):
        clock = ManualClock()
        started = clock.monotonic()
        clock.advance(3.0)
        clock.jump_wall_clock(-3600.0)  # NTP correction during the measurement
        elapsed = clock.monotonic() - started
        self.assertEqual(elapsed.seconds, 3.0)

    def test_the_same_jump_does_corrupt_the_wall_offset_which_is_why_it_is_named_apart(self):
        clock = ManualClock()
        started = clock.now()
        clock.advance(3.0)
        clock.jump_wall_clock(-3600.0)
        self.assertLess((clock.now() - started).seconds, 0)

    def test_two_injected_clocks_are_not_the_same_monotonic_source(self):
        # Reported on PR #32: sharing the process default made independent test clocks
        # subtractable, so 900 - 10 returned Duration(890) from two unrelated timelines.
        first, second = ManualClock(monotonic=900.0), ManualClock(monotonic=10.0)
        with self.assertRaises(ClockDomainError):
            first.monotonic() - second.monotonic()

    def test_an_injected_clock_is_not_comparable_with_the_real_one(self):
        with self.assertRaises(ClockDomainError):
            ManualClock().monotonic() - Clock().monotonic()

    def test_one_injected_clock_still_measures_its_own_elapsed_time(self):
        clock = ManualClock(monotonic=10.0)
        started = clock.monotonic()
        clock.advance(2.5)
        self.assertEqual((clock.monotonic() - started).seconds, 2.5)


if __name__ == "__main__":
    unittest.main()
