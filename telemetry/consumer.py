"""Append delivered v2 envelopes to PostgreSQL once each, keeping what was not ordered.

This is the consumer half of ADR-0003. It decides what to write and what a failure
means; the broker client and the psql invocation live in `platform/consume.py`, so the
decisions here are testable without Docker or a broker — the same split the publisher
and the migration runner already use.

Four rules are structural rather than documented:

- **Redelivery is not a duplicate row.** `event_id` is the producer's deterministic
  uuid5, so the insert is `ON CONFLICT DO NOTHING ... RETURNING`, and whether a row
  came back is how the consumer knows which of the two happened. QoS 1 guarantees
  at-least-once, so redelivery is expected traffic, not an error to report.
- **The broker is the queue.** A message is acknowledged only after its transaction
  commits. While the database is down nothing is acknowledged, so the broker holds the
  backlog and redelivers it; a second local spool would be a second copy of the same
  durability with its own loss modes. What the consumer must never do is acknowledge a
  message it did not store, which would turn a database outage into silent loss.
- **Memory follows the durable record, never leads it.** The boot verdict is decided
  before the write and remembered only after it commits. The reverse order was a real
  bug in `telemetry/spool.py`, found by R2 on PR #19: an in-memory counter that had
  moved ahead of the disk made a drop that never persisted look recorded.
- **An unordered boot stays unordered.** The verdict is written once, at first sight,
  and the ledger is rebuilt from the database at startup. Nothing here recomputes a
  verdict for a boot that already has one, so a restart cannot turn UNORDERED into
  ORDERED by forgetting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite
from typing import Protocol

from core.schema import SCHEMA_VERSION, DeviceState
from telemetry.envelope import (
    BootLedger,
    BootOrder,
    Envelope,
    EnvelopeError,
    ProducerRef,
    unwrap,
)

PAYLOAD_FIELDS = ("schema_version", "run_id", "event_id", "event")
EVENT_FIELDS = ("device_id", "previous_state", "new_state", "reason", "timestamp")


class DatabaseError(RuntimeError):
    """The database refused or could not be reached. Carries the server's own message."""


class ConsumerError(ValueError):
    """The delivered document cannot be stored as the contract it claims to be."""


class Database(Protocol):
    def apply(self, sql: str) -> tuple[tuple[str, ...], ...]:
        """Run one script as a single transaction and return the rows it RETURNed."""
        ...


def _text(value: object, field_name: str) -> str:
    """Quote a SQL string literal, refusing what PostgreSQL text cannot hold."""
    if not isinstance(value, str):
        raise ConsumerError(f"{field_name} must be a string, not {type(value).__name__}")
    if "\x00" in value:
        raise ConsumerError(f"{field_name} contains a NUL, which PostgreSQL text cannot store")
    # standard_conforming_strings is on by default, so doubling the quote is the whole
    # escape: a backslash is an ordinary character.
    return "'" + value.replace("'", "''") + "'"


def _number(value: object, field_name: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConsumerError(f"{field_name} must be a real number, not {type(value).__name__}")
    if not isfinite(value):
        raise ConsumerError(f"{field_name} must be finite")
    if value < 0:
        raise ConsumerError(f"{field_name} must not be negative")
    return repr(float(value))


def _optional_number(value: object, field_name: str) -> str:
    return "NULL" if value is None else _number(value, field_name)


def validate_payload(payload: dict) -> dict:
    """Check the nested document against 0.1.0 before it reaches the database.

    The CHECK constraints in 001 would catch most of this, but a constraint violation
    aborts the transaction and tells the operator about SQL rather than about the wire.
    Rejecting here names the field, and keeps an unsupported schema_version from ever
    being attempted.
    """
    missing = [name for name in PAYLOAD_FIELDS if name not in payload]
    if missing:
        raise ConsumerError(f"payload is missing {', '.join(missing)}")
    if payload["schema_version"] != SCHEMA_VERSION:
        raise ConsumerError(f"unsupported payload schema_version {payload['schema_version']!r}")
    event = payload["event"]
    if not isinstance(event, dict):
        raise ConsumerError("payload event must be a document")
    absent = [name for name in EVENT_FIELDS if name not in event]
    if absent:
        raise ConsumerError(f"payload event is missing {', '.join(absent)}")
    states = (event["previous_state"], event["new_state"])
    for name, state in zip(("previous_state", "new_state"), states, strict=True):
        if state not in tuple(DeviceState):
            raise ConsumerError(f"{name} is not a known DeviceState: {state!r}")
    if states[0] == states[1]:
        raise ConsumerError("a StateEvent must describe a transition")
    return event


def insert_script(envelope: Envelope, verdict: BootOrder) -> str:
    """One transaction: record the boot if it is new, then append the event.

    The boot row is written first because the event's foreign key names it. Both
    inserts are `ON CONFLICT DO NOTHING`, so a redelivery and a second consumer are the
    same harmless case, and the event's `RETURNING` is what distinguishes a stored event
    from one that was already there.
    """
    producer, payload = envelope.producer, envelope.payload
    event = validate_payload(payload)
    values = {
        "producer_id": _text(producer.producer_id, "producer_id"),
        "boot_id": _text(producer.boot_id, "boot_id"),
        "boot_started_at": _number(producer.boot_started_at, "boot_started_at"),
        "verdict": _text(str(verdict), "verdict"),
        "event_id": _text(payload["event_id"], "event_id"),
        "run_id": _text(payload["run_id"], "run_id"),
        "schema_version": _text(payload["schema_version"], "schema_version"),
        "device_id": _text(event["device_id"], "device_id"),
        "previous_state": _text(str(event["previous_state"]), "previous_state"),
        "new_state": _text(str(event["new_state"]), "new_state"),
        "reason": _text(event["reason"], "reason"),
        "event_timestamp": _number(event["timestamp"], "timestamp"),
        "expires_at": _optional_number(event.get("expires_at"), "expires_at"),
        "sequence": str(envelope.sequence),
    }
    boot = ""
    if verdict is not BootOrder.KNOWN:
        # KNOWN means this ledger already has the boot, so the row exists and its
        # verdict is the one first sight established. Writing again could only either
        # do nothing or overwrite that, and the table forbids the second.
        boot = (
            "INSERT INTO boots (producer_id, boot_id, boot_started_at, verdict)\n"
            "VALUES ({producer_id}, {boot_id}, {boot_started_at}, {verdict})\n"
            "ON CONFLICT DO NOTHING;\n"
        ).format(**values)
    return (
        "BEGIN;\n"
        f"{boot}"
        "INSERT INTO events (\n"
        "    event_id, run_id, schema_version, device_id, previous_state, new_state,\n"
        "    reason, event_timestamp, expires_at, producer_id, boot_id, sequence\n"
        ")\n"
        "VALUES (\n"
        "    {event_id}, {run_id}, {schema_version}, {device_id}, {previous_state},\n"
        "    {new_state}, {reason}, {event_timestamp}, {expires_at}, {producer_id},\n"
        "    {boot_id}, {sequence}\n"
        ")\n"
        "ON CONFLICT (event_id) DO NOTHING\n"
        "RETURNING event_id;\n"
        "COMMIT;\n"
    ).format(**values)


def load_ledger(database: Database) -> BootLedger:
    """Rebuild the ledger from the boots already recorded.

    Without this a restarted consumer starts blank, and the next event from a boot that
    was recorded as UNORDERED presents as a boot never seen — the verdict would be
    recomputed against an empty history and could come back ORDERED. R1 raised exactly
    this on PR #19; the fix is that the durable record, not the process, is the memory.
    """
    ledger = BootLedger()
    rows = database.apply("SELECT producer_id, boot_id, boot_started_at FROM boots;")
    for row in rows:
        ledger.record(ProducerRef(row[0], row[1], float(row[2])))
    return ledger


@dataclass
class ConsumerCounters:
    """What the consumer saw. Nothing here is derived; each is incremented once."""

    stored: int = 0
    redelivered: int = 0
    rejected: int = 0
    boots_recorded: int = 0
    unordered_boots: int = 0
    database_failures: int = 0
    left_unacknowledged: int = 0

    def as_dict(self) -> dict:
        return dict(vars(self))


@dataclass(frozen=True)
class Ingest:
    """What happened to one delivered message, including whether it may be acked."""

    acknowledge: bool
    stored: bool = False
    redelivered: bool = False
    boot: BootOrder | None = None
    rejected: str | None = None
    failure: str | None = None


@dataclass
class TelemetryConsumer:
    """Applies one delivered document to the database and reports what it did."""

    database: Database
    ledger: BootLedger = field(default_factory=BootLedger)
    counters: ConsumerCounters = field(default_factory=ConsumerCounters)

    @classmethod
    def restored(cls, database: Database) -> TelemetryConsumer:
        """Build a consumer whose ledger comes from the database, not from nothing."""
        return cls(database=database, ledger=load_ledger(database))

    def ingest(self, document: object) -> Ingest:
        try:
            envelope = unwrap(document)
            verdict = self.ledger.verdict_for(envelope.producer)
            script = insert_script(envelope, verdict)
        except (EnvelopeError, ConsumerError) as error:
            # Acknowledged deliberately: the broker would otherwise redeliver a document
            # that can never be stored, forever. The count and the reason are the record
            # that it arrived and was refused.
            self.counters.rejected += 1
            return Ingest(acknowledge=True, rejected=str(error))

        try:
            returned = self.database.apply(script)
        except DatabaseError as error:
            # Not acknowledged: the message stays with the broker, which is the only
            # copy that outlives this process. Acking here would drop it silently.
            self.counters.database_failures += 1
            self.counters.left_unacknowledged += 1
            return Ingest(acknowledge=False, boot=verdict, failure=str(error))

        # Only now: the verdict is durable, so the ledger may remember it.
        if verdict is not BootOrder.KNOWN:
            self.ledger.record(envelope.producer)
            self.counters.boots_recorded += 1
            if verdict is BootOrder.UNORDERED:
                self.counters.unordered_boots += 1

        stored = bool(returned)
        if stored:
            self.counters.stored += 1
        else:
            self.counters.redelivered += 1
        return Ingest(acknowledge=True, stored=stored, redelivered=not stored, boot=verdict)

    def unordered_runs(self) -> tuple[str, ...]:
        """Runs that touched a boot whose start time did not order it.

        Ordering-dependent measurements exclude these and report how many they
        excluded. A run absent from this set is not proven ordered by its absence; it
        is only not contradicted.
        """
        rows = self.database.apply("SELECT run_id FROM unordered_runs ORDER BY run_id;")
        return tuple(row[0] for row in rows)
