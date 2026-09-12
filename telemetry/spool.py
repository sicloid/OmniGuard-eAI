"""ADR-0003 bounded on-disk spool with oldest-first eviction.

The spool exists so a broker outage cannot block enforcement. It is bounded in
bytes and in age; when a bound is reached the oldest entry is discarded and the
loss is recorded permanently. A reconnect is not evidence that nothing was lost,
so the counters below feed the G10 completeness result directly.

No clock is read here. Callers pass the UTC timestamp they already have, which
keeps the event-time and monotonic domains from mixing.
"""

import json
import os
import re
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from telemetry.canonical import canonical_bytes

COUNTERS_FILENAME = "counters.json"
ENTRY_SUFFIX = ".frame"
ENTRY_PATTERN = re.compile(r"\A(\d{20})_(\d{20})_(\d{20})\.frame\Z")
DROP_REASONS = ("bytes", "age")


class SpoolError(ValueError):
    """The spool cannot accept or account for an entry."""


@dataclass(frozen=True)
class SpoolEntry:
    index: int
    sequence: int
    enqueued_micros: int
    size: int
    path: Path

    @property
    def enqueued(self) -> float:
        return self.enqueued_micros / 1_000_000


@dataclass(frozen=True)
class SpoolCounters:
    """Permanent loss accounting; survives restarts and is never reset silently."""

    dropped_events: int = 0
    dropped_bytes: int = 0
    dropped_by_bytes: int = 0
    dropped_by_age: int = 0
    rejected_oversize: int = 0
    first_dropped_sequence: int | None = None
    last_dropped_sequence: int | None = None

    def with_drop(self, reason: str, sequence: int, size: int) -> SpoolCounters:
        if reason not in DROP_REASONS:
            raise SpoolError(f"drop reason must be one of {DROP_REASONS}")
        return replace(
            self,
            dropped_events=self.dropped_events + 1,
            dropped_bytes=self.dropped_bytes + size,
            dropped_by_bytes=self.dropped_by_bytes + (reason == "bytes"),
            dropped_by_age=self.dropped_by_age + (reason == "age"),
            first_dropped_sequence=(
                sequence if self.first_dropped_sequence is None else self.first_dropped_sequence
            ),
            last_dropped_sequence=sequence,
        )


class BoundedSpool:
    """Durable queue bounded by total bytes and entry age.

    Entry filenames carry the index, the producing sequence and the enqueue time,
    so eviction can order entries and report the discarded sequence range without
    opening a single payload.
    """

    def __init__(self, directory: Path, *, max_bytes: int, max_age_seconds: float):
        for name, value in (("max_bytes", max_bytes), ("max_age_seconds", max_age_seconds)):
            if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
                raise SpoolError(f"{name} must be a positive number")
        self._directory = Path(directory)
        self._directory.mkdir(parents=True, exist_ok=True)
        self._max_bytes = int(max_bytes)
        self._max_age = float(max_age_seconds)
        self._counters_path = self._directory / COUNTERS_FILENAME
        self._counters = self._load_counters()

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    def counters(self) -> SpoolCounters:
        return self._counters

    def _load_counters(self) -> SpoolCounters:
        if not self._counters_path.exists():
            return SpoolCounters()
        try:
            document = json.loads(self._counters_path.read_text(encoding="utf-8"))
            return SpoolCounters(**document)
        except (OSError, UnicodeError, ValueError, TypeError) as exc:
            raise SpoolError(f"unreadable spool counters: {exc}") from exc

    def _write_atomic(self, path: Path, payload: bytes) -> None:
        """Write through a temporary name so a crash never leaves a half record."""
        temporary = path.with_name(path.name + ".tmp")
        with temporary.open("wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)

    def _save_counters(self) -> None:
        self._write_atomic(self._counters_path, canonical_bytes(asdict(self._counters)))

    def pending(self) -> list[SpoolEntry]:
        entries = []
        for path in self._directory.iterdir():
            match = ENTRY_PATTERN.match(path.name)
            if match is None:
                continue
            index, sequence, enqueued = (int(group) for group in match.groups())
            entries.append(SpoolEntry(index, sequence, enqueued, path.stat().st_size, path))
        return sorted(entries, key=lambda entry: entry.index)

    def total_bytes(self) -> int:
        return sum(entry.size for entry in self.pending())

    def append(self, sequence: int, body: bytes, *, now: float) -> bool:
        """Store one frame body. Returns False when the entry itself cannot fit.

        An entry larger than the whole budget is rejected instead of being stored
        and immediately evicting every older entry to make room for itself.
        """
        if type(sequence) is not int or sequence < 1:
            raise SpoolError("sequence must be a positive integer")
        if not isinstance(body, bytes | bytearray) or not body:
            raise SpoolError("spooled body must be nonempty bytes")
        if len(body) > self._max_bytes:
            self._counters = replace(
                self._counters, rejected_oversize=self._counters.rejected_oversize + 1
            )
            self._save_counters()
            return False
        existing = self.pending()
        index = existing[-1].index + 1 if existing else 1
        name = f"{index:020d}_{sequence:020d}_{int(now * 1_000_000):020d}{ENTRY_SUFFIX}"
        self._write_atomic(self._directory / name, bytes(body))
        self.enforce(now=now)
        return True

    def enforce(self, *, now: float) -> None:
        """Apply the age bound first, then the byte bound, oldest entry first."""
        for entry in self.pending():
            if now - entry.enqueued > self._max_age:
                self._evict(entry, "age")
        entries = self.pending()
        total = sum(entry.size for entry in entries)
        for entry in entries:
            if total <= self._max_bytes:
                break
            self._evict(entry, "bytes")
            total -= entry.size

    def _evict(self, entry: SpoolEntry, reason: str) -> None:
        entry.path.unlink(missing_ok=True)
        self._counters = self._counters.with_drop(reason, entry.sequence, entry.size)
        self._save_counters()

    def read(self, entry: SpoolEntry) -> bytes:
        return entry.path.read_bytes()

    def remove(self, entry: SpoolEntry) -> None:
        """Drop an entry after it was accepted downstream; not a loss."""
        entry.path.unlink(missing_ok=True)
