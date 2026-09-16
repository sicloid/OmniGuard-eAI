"""ADR-0003 versioned transport envelope carrying the ordering metadata.

`event_id` is a UUID5. It is stable across retries, which is what dedup needs,
but it is opaque: a consumer cannot read the producer, the boot or the sequence
back out of it. Publishing only the 0.1.0 `TelemetryPayload` therefore leaves a
consumer unable to apply ADR-0002's rule that an older event must not undo newer
state, because nothing on the wire says which event is older.

The fix is not to add fields to 0.1.0. That contract is frozen, and quietly
widening it would break the promise every consumer was written against. Instead
the 0.1.0 document is nested **verbatim** inside a separately versioned envelope,
and the envelope goes to its own topic version. A consumer reading the old topic
sees exactly what it saw before; a consumer that wants ordering subscribes to the
new one and states which envelope version it understands.

Cross-boot ordering rests on `boot_started_at`, a UTC wall clock, so it inherits
that clock's weaknesses. `BootLedger` below names those cases instead of letting
them pass as fact: see `BootOrder`.
"""

from dataclasses import dataclass
from enum import StrEnum

from telemetry.identity import EventIdentity, IdentityError

ENVELOPE_VERSION = "1"
ENVELOPE_FIELDS = ("envelope_version", "producer", "sequence", "payload")
PRODUCER_FIELDS = ("producer_id", "boot_id", "boot_started_at")


class EnvelopeError(ValueError):
    """The envelope is absent, malformed, or of a version this code cannot read."""


@dataclass(frozen=True)
class ProducerRef:
    """The producing identity as it appears on the wire."""

    producer_id: str
    boot_id: str
    boot_started_at: float


@dataclass(frozen=True)
class Envelope:
    """One transport envelope: ordering metadata plus an untouched 0.1.0 payload."""

    envelope_version: str
    producer: ProducerRef
    sequence: int
    payload: dict

    def ordering_key(self) -> tuple[float, str, int]:
        """A total order over events from one producer.

        `boot_started_at` leads because `sequence` restarts at one on every boot.
        `boot_id` breaks a tie between two boots that report the same start time,
        so the order is total and the same for every consumer; it is a
        tie-breaker, not a claim about which boot really started first.
        """
        return (self.producer.boot_started_at, self.producer.boot_id, self.sequence)


def wrap(identity: EventIdentity, payload: dict) -> dict:
    """Put the ordering metadata beside the payload without touching the payload."""
    if not isinstance(payload, dict) or not payload:
        raise EnvelopeError("payload must be a nonempty document")
    producer = identity.producer
    return {
        "envelope_version": ENVELOPE_VERSION,
        "payload": payload,
        "producer": {
            "boot_id": producer.boot_id,
            "boot_started_at": producer.boot_started_at,
            "producer_id": producer.producer_id,
        },
        "sequence": identity.sequence,
    }


def unwrap(document: dict) -> Envelope:
    """Read an envelope, refusing anything this code cannot claim to understand."""
    if not isinstance(document, dict):
        raise EnvelopeError("envelope must be a document")
    missing = [field for field in ENVELOPE_FIELDS if field not in document]
    if missing:
        raise EnvelopeError(f"envelope is missing {', '.join(missing)}")
    version = document["envelope_version"]
    if version != ENVELOPE_VERSION:
        # Guessing at an unknown version is how a consumer silently misreads a
        # contract it was never reviewed against.
        raise EnvelopeError(f"unsupported envelope_version {version!r}")
    producer = document["producer"]
    if not isinstance(producer, dict) or any(field not in producer for field in PRODUCER_FIELDS):
        raise EnvelopeError(f"producer must carry {', '.join(PRODUCER_FIELDS)}")
    sequence = document["sequence"]
    if type(sequence) is not int or sequence < 1:
        raise EnvelopeError("sequence must be a positive integer")
    payload = document["payload"]
    if not isinstance(payload, dict) or not payload:
        raise EnvelopeError("payload must be a nonempty document")
    try:
        reference = ProducerRef(
            producer["producer_id"], producer["boot_id"], producer["boot_started_at"]
        )
    except (KeyError, TypeError) as exc:
        raise EnvelopeError(f"unreadable producer: {exc}") from exc
    return Envelope(version, reference, sequence, payload)


class BootOrder(StrEnum):
    """What a newly seen boot means for ordering.

    `ORDERED` is the only case where the UTC start time actually establishes that
    this boot follows the ones already seen. `UNORDERED` covers a start time that
    is equal to or earlier than a boot already recorded: a clock rollback, a
    coarse clock, or a restored backup. The tie-breaker still yields a total
    order, but it is not evidence about real time, so it is reported.
    """

    ORDERED = "ORDERED"
    KNOWN = "KNOWN"
    UNORDERED = "UNORDERED"


class BootLedger:
    """Remembers the boots each producer has presented, so a rollback is visible.

    Held by the consumer. KAN-40 decides what to do with an `UNORDERED` verdict;
    this class only refuses to let it pass unnamed.

    Deciding and remembering are separate calls because a consumer must not let
    memory run ahead of the durable record. If the ledger marked a boot seen and
    the database write then failed, the retry would read `KNOWN`, skip writing
    the boot, and the verdict would exist nowhere. `verdict_for` decides without
    recording; `record` is called after the write commits. `observe` keeps both
    in one step for callers that hold no separate record.
    """

    def __init__(self) -> None:
        self._seen: dict[str, dict[str, float]] = {}

    def verdict_for(self, producer: ProducerRef) -> BootOrder:
        """Decide how this boot orders against the ones already known. No mutation."""
        if not isinstance(producer, ProducerRef):
            raise IdentityError("producer must be a ProducerRef")
        boots = self._seen.get(producer.producer_id, {})
        if producer.boot_id in boots:
            return BootOrder.KNOWN
        latest = max(boots.values(), default=None)
        if latest is None or producer.boot_started_at > latest:
            return BootOrder.ORDERED
        return BootOrder.UNORDERED

    def record(self, producer: ProducerRef) -> None:
        """Remember a boot whose verdict is now durable somewhere this ledger trusts."""
        if not isinstance(producer, ProducerRef):
            raise IdentityError("producer must be a ProducerRef")
        self._seen.setdefault(producer.producer_id, {})[producer.boot_id] = producer.boot_started_at

    def observe(self, producer: ProducerRef) -> BootOrder:
        verdict = self.verdict_for(producer)
        self.record(producer)
        return verdict

    def boots_for(self, producer_id: str) -> dict[str, float]:
        return dict(self._seen.get(producer_id, {}))
