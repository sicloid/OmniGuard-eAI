"""Two clock domains that refuse to be mixed, and the only type allowed to be elapsed time.

The project reports latencies. A latency is a difference between two readings of the
*same* clock, and only the monotonic clock is valid for that: UTC wall time can jump
backwards on an NTP correction or a manual change, so a difference between two wall
readings is not a measured duration and must never be reported as one.

`NewType` cannot enforce this. It is erased at runtime, and ruff is a linter rather
than a type checker, so `UnixSeconds - MonotonicSeconds` would run and produce a
plausible-looking number. That objection was raised by R2 on 12 September 2026 and is
recorded on KAN-42. The types here therefore reject wrong-domain arithmetic at
runtime, and the negative tests in `tests/test_measure_clocks.py` are the evidence.

What each type is for:

- `UnixInstant`  — a UTC wall-clock reading. Goes on the wire, into StateEvent
  timestamps and into manifests as *when* something happened. It has no arithmetic.
- `MonotonicInstant` — a reading of a clock that only moves forward. Never leaves the
  process and is meaningless to compare across processes or boots.
- `Duration` — the difference between two `MonotonicInstant`s from the same source.
  This is the only type that may be reported as elapsed time.
- `WallOffset` — the difference between two `UnixInstant`s, named so that it cannot be
  mistaken for `Duration`. It exists because comparing wall times is sometimes
  necessary; it is not a measurement of how long anything took.
"""

import time
from dataclasses import dataclass, field
from math import isfinite

# A monotonic reading is only comparable to another reading from the same clock in the
# same process. Restarting the process gives a new epoch, so a stored MonotonicInstant
# from an earlier boot is not comparable to a current one; the source id makes an
# attempt to compare them an error instead of a wrong number.
_SOURCE = f"monotonic:{time.get_clock_info('monotonic').resolution}:{id(time.monotonic)}"


class ClockDomainError(TypeError):
    """An operation mixed two clock domains, or two incomparable monotonic sources."""


def _finite(value: float, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ClockDomainError(f"{what} must be a real number, not {type(value).__name__}")
    if not isfinite(value):
        raise ClockDomainError(f"{what} must be finite")
    return float(value)


def _refuse(left: object, right: object, operation: str):
    raise ClockDomainError(
        f"{type(left).__name__} {operation} {type(right).__name__} mixes clock domains. "
        "Elapsed time is MonotonicInstant - MonotonicInstant, which gives a Duration; "
        "UTC wall readings cannot measure how long something took."
    )


@dataclass(frozen=True, order=False)
class Duration:
    """Elapsed time from one monotonic clock. The only type that may be reported."""

    seconds: float

    def __post_init__(self) -> None:
        _finite(self.seconds, "Duration seconds")
        if self.seconds < 0:
            # A monotonic clock going backwards is a broken assumption, not a small
            # negative number to average away.
            raise ClockDomainError("Duration cannot be negative; the monotonic clock moved back")

    def __add__(self, other):
        if not isinstance(other, Duration):
            _refuse(self, other, "+")
        return Duration(self.seconds + other.seconds)

    def __sub__(self, other):
        if not isinstance(other, Duration):
            _refuse(self, other, "-")
        return Duration(self.seconds - other.seconds)

    def __lt__(self, other):
        if not isinstance(other, Duration):
            _refuse(self, other, "<")
        return self.seconds < other.seconds

    def __le__(self, other):
        if not isinstance(other, Duration):
            _refuse(self, other, "<=")
        return self.seconds <= other.seconds

    def __gt__(self, other):
        if not isinstance(other, Duration):
            _refuse(self, other, ">")
        return self.seconds > other.seconds

    def __ge__(self, other):
        if not isinstance(other, Duration):
            _refuse(self, other, ">=")
        return self.seconds >= other.seconds

    @property
    def milliseconds(self) -> float:
        return self.seconds * 1000.0


@dataclass(frozen=True, order=False)
class WallOffset:
    """Difference between two wall-clock readings. Deliberately not a Duration.

    Kept separate so that a wall-clock difference cannot be passed anywhere a measured
    elapsed time is expected. It may be negative: that is exactly the case this type
    exists to make visible rather than hide.
    """

    seconds: float

    def __post_init__(self) -> None:
        _finite(self.seconds, "WallOffset seconds")

    def __add__(self, other):
        _refuse(self, other, "+")

    def __sub__(self, other):
        _refuse(self, other, "-")


@dataclass(frozen=True, order=False)
class MonotonicInstant:
    """A reading of the monotonic clock. Never serialise this as a time of day."""

    seconds: float
    source: str = field(default=_SOURCE, compare=True)

    def __post_init__(self) -> None:
        _finite(self.seconds, "MonotonicInstant seconds")

    def __sub__(self, other):
        if not isinstance(other, MonotonicInstant):
            _refuse(self, other, "-")
        if self.source != other.source:
            raise ClockDomainError(
                "these MonotonicInstants come from different clock sources or processes; "
                "their difference is not a duration"
            )
        return Duration(self.seconds - other.seconds)

    def __add__(self, other):
        if not isinstance(other, Duration):
            _refuse(self, other, "+")
        return MonotonicInstant(self.seconds + other.seconds, self.source)


@dataclass(frozen=True, order=False)
class UnixInstant:
    """UTC Unix seconds: what happened when. Carries no notion of how long."""

    seconds: float

    def __post_init__(self) -> None:
        _finite(self.seconds, "UnixInstant seconds")
        if self.seconds < 0:
            raise ClockDomainError("UnixInstant must not be negative")

    def __sub__(self, other):
        if not isinstance(other, UnixInstant):
            _refuse(self, other, "-")
        # Named WallOffset, not Duration: two wall readings cannot measure elapsed time.
        return WallOffset(self.seconds - other.seconds)

    def __add__(self, other):
        # Adding a measured Duration to a wall instant silently asserts that the wall
        # clock advanced by exactly that much, which is the assumption under test.
        _refuse(self, other, "+")


class Clock:
    """The single place readings are taken, so tests can inject time without patching."""

    def now(self) -> UnixInstant:
        return UnixInstant(time.time())

    def monotonic(self) -> MonotonicInstant:
        return MonotonicInstant(time.monotonic())


class ManualClock(Clock):
    """A clock driven by the test, including backwards wall jumps.

    Each instance is its own monotonic source. Sharing the process default would make
    two independent injected clocks subtractable — one at 900 and one at 10 returning
    Duration(890) — which is the wrong-domain arithmetic this module exists to reject,
    reintroduced through the seam used to test it. R2 found this on PR #32.
    """

    _created = 0

    def __init__(self, unix: float = 1_000_000.0, monotonic: float = 0.0):
        self._unix, self._monotonic = float(unix), float(monotonic)
        ManualClock._created += 1
        self._source = f"manual:{ManualClock._created}:{id(self)}"

    def now(self) -> UnixInstant:
        return UnixInstant(self._unix)

    def monotonic(self) -> MonotonicInstant:
        return MonotonicInstant(self._monotonic, self._source)

    def advance(self, seconds: float) -> None:
        """Move both clocks forward, as an untroubled machine would."""
        self._unix += seconds
        self._monotonic += seconds

    def jump_wall_clock(self, seconds: float) -> None:
        """Move only the wall clock, forwards or backwards. The monotonic clock ignores it."""
        self._unix += seconds
