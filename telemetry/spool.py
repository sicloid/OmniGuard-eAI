"""ADR-0003 bounded on-disk spool with journalled oldest-first eviction.

The spool exists so a broker outage cannot block enforcement. It is bounded in
bytes and in age; when a bound is reached the oldest entry is discarded and the
loss is recorded permanently. A reconnect is not evidence that nothing was lost,
so the counters below feed the G10 completeness result directly.

Discarding an entry and recording its loss are one transaction. Deleting first
and accounting afterwards would let a crash between the two erase the event and
the evidence of the event together, leaving a directory that reads as "nothing
pending, nothing lost". Eviction therefore writes its intent to a journal first,
then deletes, then applies the counters, then clears the journal; reopening the
directory finishes whatever was in flight. Each eviction carries an id and the
counters remember the last one applied, so replaying a finished eviction cannot
double count it.

A dropped sequence range is only meaningful next to the boot that produced it,
because sequences restart at one on every boot. Entries therefore carry a scope
token, the registry maps that token back to the producer and boot, and losses
are reported per scope.

No clock is read here. Callers pass the UTC timestamp they already have, which
keeps the event-time and monotonic domains from mixing.
"""

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from telemetry.canonical import canonical_bytes

COUNTERS_FILENAME = "counters.json"
SCOPES_FILENAME = "scopes.json"
JOURNAL_FILENAME = "eviction.journal"
ENTRY_SUFFIX = ".frame"
ENTRY_PATTERN = re.compile(r"\A(\d{20})_(\d{20})_(\d{20})_([0-9a-f]{16})\.frame\Z")
DROP_REASONS = ("bytes", "age")
UNREGISTERED = ""


class SpoolError(ValueError):
    """The spool cannot accept or account for an entry."""


@dataclass(frozen=True)
class SpoolScope:
    """The producer and process lifetime an entry belongs to.

    `boot_started_at` is carried so a reader can order the scopes themselves;
    the token is derived from the producer and boot alone, so restating the same
    boot never produces a second scope.
    """

    producer_id: str
    boot_id: str
    boot_started_at: float

    def __post_init__(self) -> None:
        for field in ("producer_id", "boot_id"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise SpoolError(f"{field} must be nonempty text")
        if isinstance(self.boot_started_at, bool) or not isinstance(
            self.boot_started_at, int | float
        ):
            raise SpoolError("boot_started_at must be a number")

    @property
    def token(self) -> str:
        """Fixed-width, filename-safe digest of the producing identity."""
        digest = hashlib.blake2b(
            canonical_bytes({"boot_id": self.boot_id, "producer_id": self.producer_id}),
            digest_size=8,
        )
        return digest.hexdigest()


@dataclass(frozen=True)
class SpoolEntry:
    index: int
    sequence: int
    enqueued_micros: int
    scope_token: str
    size: int
    path: Path

    @property
    def enqueued(self) -> float:
        return self.enqueued_micros / 1_000_000


@dataclass(frozen=True)
class ScopeLoss:
    """What one producing boot lost, kept apart from every other boot's loss."""

    scope_token: str
    producer_id: str
    boot_id: str
    dropped_events: int
    first_sequence: int
    last_sequence: int


@dataclass(frozen=True)
class SpoolCounters:
    """Permanent loss accounting; survives restarts and is never reset silently."""

    dropped_events: int = 0
    dropped_bytes: int = 0
    dropped_by_bytes: int = 0
    dropped_by_age: int = 0
    rejected_oversize: int = 0
    last_applied_eviction: int = 0
    scopes: tuple[ScopeLoss, ...] = ()

    @classmethod
    def from_document(cls, document: dict) -> SpoolCounters:
        fields = dict(document)
        fields["scopes"] = tuple(ScopeLoss(**scope) for scope in fields.get("scopes", ()))
        return cls(**fields)

    def loss_for(self, scope_token: str) -> ScopeLoss | None:
        for loss in self.scopes:
            if loss.scope_token == scope_token:
                return loss
        return None

    def with_drop(
        self,
        *,
        reason: str,
        eviction_id: int,
        scope_token: str,
        producer_id: str,
        boot_id: str,
        sequence: int,
        size: int,
    ) -> SpoolCounters:
        if reason not in DROP_REASONS:
            raise SpoolError(f"drop reason must be one of {DROP_REASONS}")
        existing = self.loss_for(scope_token)
        if existing is None:
            scopes = (
                *self.scopes,
                ScopeLoss(scope_token, producer_id, boot_id, 1, sequence, sequence),
            )
        else:
            scopes = tuple(
                replace(
                    loss,
                    dropped_events=loss.dropped_events + 1,
                    first_sequence=min(loss.first_sequence, sequence),
                    last_sequence=max(loss.last_sequence, sequence),
                )
                if loss.scope_token == scope_token
                else loss
                for loss in self.scopes
            )
        return replace(
            self,
            dropped_events=self.dropped_events + 1,
            dropped_bytes=self.dropped_bytes + size,
            dropped_by_bytes=self.dropped_by_bytes + (reason == "bytes"),
            dropped_by_age=self.dropped_by_age + (reason == "age"),
            last_applied_eviction=eviction_id,
            scopes=scopes,
        )


class BoundedSpool:
    """Durable queue bounded by total bytes and entry age.

    Entry filenames carry the index, the producing sequence, the enqueue time and
    the scope token, so eviction can order entries and attribute the discarded
    sequence range to a boot without opening a single payload.
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
        self._scopes_path = self._directory / SCOPES_FILENAME
        self._journal_path = self._directory / JOURNAL_FILENAME
        self._counters = self._load_counters()
        self._scopes = self._load_scopes()
        self.recover()

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    def counters(self) -> SpoolCounters:
        return self._counters

    def scopes(self) -> dict[str, SpoolScope]:
        """Token to producing identity, so a reported loss can be attributed."""
        return dict(self._scopes)

    def _read_document(self, path: Path) -> dict | None:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise SpoolError(f"unreadable spool file {path.name}: {exc}") from exc

    def _load_counters(self) -> SpoolCounters:
        document = self._read_document(self._counters_path)
        if document is None:
            return SpoolCounters()
        try:
            return SpoolCounters.from_document(document)
        except TypeError as exc:
            raise SpoolError(f"unreadable spool counters: {exc}") from exc

    def _load_scopes(self) -> dict[str, SpoolScope]:
        document = self._read_document(self._scopes_path)
        if document is None:
            return {}
        try:
            return {token: SpoolScope(**fields) for token, fields in document.items()}
        except (AttributeError, TypeError) as exc:
            raise SpoolError(f"unreadable spool scopes: {exc}") from exc

    def _fsync_directory(self) -> None:
        """Make a rename durable where the platform allows it.

        Linux needs the directory entry flushed as well as the file it points at.
        Windows offers no directory handle to flush, so there the ordering holds
        per file only; the durability claim is measured on the Linux lab host.
        """
        if os.name != "posix":
            return
        descriptor = os.open(self._directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _write_atomic(self, path: Path, payload: bytes) -> None:
        """Write through a temporary name so a crash never leaves a half record."""
        temporary = path.with_name(path.name + ".tmp")
        with temporary.open("wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        self._fsync_directory()

    def _save_counters(self) -> None:
        self._write_atomic(self._counters_path, canonical_bytes(asdict(self._counters)))

    def _register(self, scope: SpoolScope) -> str:
        """Record the token to identity mapping once per boot, before it is used."""
        token = scope.token
        if self._scopes.get(token) == scope:
            return token
        updated = {**self._scopes, token: scope}
        self._write_atomic(
            self._scopes_path,
            canonical_bytes({key: asdict(value) for key, value in updated.items()}),
        )
        self._scopes = updated
        return token

    def recover(self) -> bool:
        """Finish an eviction that was in flight, then clear the journal.

        Returns True when a pending eviction had to be applied. Replaying a
        completed eviction is a no-op because its id is already recorded.
        """
        record = self._read_document(self._journal_path)
        if record is None:
            return False
        # A worker survives an OSError: its in-memory counter may have advanced
        # even though persistence failed. Disk state governs journal replay.
        self._counters = self._load_counters()
        applied = False
        try:
            eviction_id = int(record["eviction_id"])
            entry_name = str(record["entry_name"])
            reason = str(record["reason"])
            scope_token = str(record["scope_token"])
            sequence = int(record["sequence"])
            size = int(record["size"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SpoolError(f"unreadable eviction journal: {exc}") from exc
        if eviction_id > self._counters.last_applied_eviction:
            # The delete may or may not have happened; make both halves true.
            (self._directory / entry_name).unlink(missing_ok=True)
            scope = self._scopes.get(scope_token)
            self._counters = self._counters.with_drop(
                reason=reason,
                eviction_id=eviction_id,
                scope_token=scope_token,
                producer_id=scope.producer_id if scope else UNREGISTERED,
                boot_id=scope.boot_id if scope else UNREGISTERED,
                sequence=sequence,
                size=size,
            )
            self._save_counters()
            applied = True
        self._journal_path.unlink(missing_ok=True)
        self._fsync_directory()
        return applied

    def pending(self) -> list[SpoolEntry]:
        entries = []
        for path in self._directory.iterdir():
            match = ENTRY_PATTERN.match(path.name)
            if match is None:
                continue
            index, sequence, enqueued, scope_token = match.groups()
            entries.append(
                SpoolEntry(
                    int(index),
                    int(sequence),
                    int(enqueued),
                    scope_token,
                    path.stat().st_size,
                    path,
                )
            )
        return sorted(entries, key=lambda entry: entry.index)

    def total_bytes(self) -> int:
        return sum(entry.size for entry in self.pending())

    def append(self, sequence: int, body: bytes, *, now: float, scope: SpoolScope) -> bool:
        """Store one frame body. Returns False when the entry itself cannot fit.

        An entry larger than the whole budget is rejected instead of being stored
        and immediately evicting every older entry to make room for itself.
        """
        self.recover()
        if type(sequence) is not int or sequence < 1:
            raise SpoolError("sequence must be a positive integer")
        if not isinstance(body, bytes | bytearray) or not body:
            raise SpoolError("spooled body must be nonempty bytes")
        if not isinstance(scope, SpoolScope):
            raise SpoolError("scope must be a SpoolScope; an unattributable loss is not accounting")
        if len(body) > self._max_bytes:
            self._counters = replace(
                self._counters, rejected_oversize=self._counters.rejected_oversize + 1
            )
            self._save_counters()
            return False
        # The mapping is durable before any entry can reference it, so a crash
        # cannot leave an evicted entry whose producer can no longer be named.
        token = self._register(scope)
        existing = self.pending()
        index = existing[-1].index + 1 if existing else 1
        name = f"{index:020d}_{sequence:020d}_{int(now * 1_000_000):020d}_{token}{ENTRY_SUFFIX}"
        self._write_atomic(self._directory / name, bytes(body))
        self.enforce(now=now)
        return True

    def enforce(self, *, now: float) -> None:
        """Apply the age bound first, then the byte bound, oldest entry first."""
        self.recover()
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
        """Discard one entry and record its loss as a single recoverable step."""
        eviction_id = self._counters.last_applied_eviction + 1
        scope = self._scopes.get(entry.scope_token)
        self._write_journal(
            {
                "entry_name": entry.path.name,
                "eviction_id": eviction_id,
                "reason": reason,
                "scope_token": entry.scope_token,
                "sequence": entry.sequence,
                "size": entry.size,
            }
        )
        entry.path.unlink(missing_ok=True)
        self._counters = self._counters.with_drop(
            reason=reason,
            eviction_id=eviction_id,
            scope_token=entry.scope_token,
            producer_id=scope.producer_id if scope else UNREGISTERED,
            boot_id=scope.boot_id if scope else UNREGISTERED,
            sequence=entry.sequence,
            size=entry.size,
        )
        self._save_counters()
        self._journal_path.unlink(missing_ok=True)
        self._fsync_directory()

    def _write_journal(self, record: dict) -> None:
        """Declare the intent to evict before anything about the entry changes."""
        self._write_atomic(self._journal_path, canonical_bytes(record))

    def read(self, entry: SpoolEntry) -> bytes:
        return entry.path.read_bytes()

    def remove(self, entry: SpoolEntry) -> None:
        """Drop an entry after it was accepted downstream; not a loss."""
        entry.path.unlink(missing_ok=True)
