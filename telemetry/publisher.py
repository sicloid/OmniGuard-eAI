"""ADR-0003 StateEvent publisher: identity, topic, QoS and spool fallback.

The transport is injected so the fault matrix (broker down, full spool, repeated
delivery, out-of-order retry) runs as ordinary unit tests. A passing fake is not
delivery evidence: the real broker and database path is proved separately on
Compose under KAN-50.

A transport failure spools; a full spool drops the oldest entry and records the
loss. Enforcement must not wait on telemetry.

Two facts are kept apart, as ADR-0003 section 7 requires: the transport
*accepting* a message and the broker *acknowledging* it. A transport therefore
reports an `Acknowledgement` rather than returning nothing, and only
`Acknowledgement.ACKED` sets `broker_ack`. A transport that merely queues
locally leaves the event in the spool, because a local queue is not evidence
that anything left this host.

This class is **worker-side code and makes no non-blocking promise**. It calls
the transport and the filesystem on whatever thread invokes it, so a stalled
broker or a failing disk does reach its caller. That is deliberate: the caller
is `telemetry.handoff.TelemetryHandoff`, which owns the bounded queue and the
worker thread that keep telemetry off the enforcement path. Call `publish()`
directly only from a worker or a test.
"""

import json
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol

from core.schema import SCHEMA_VERSION, StateEvent, TelemetryPayload
from telemetry.canonical import canonical_bytes
from telemetry.envelope import unwrap, wrap
from telemetry.identity import (
    EventIdentity,
    IdentityError,
    ProducerIdentity,
    SequenceCounter,
    event_id,
    validate_device_id,
)
from telemetry.spool import BoundedSpool, SpoolScope

# v2 carries the ordering envelope. ADR-0002 asks for a separate versioned
# envelope and topic per event type with the old state topic preserved, so v1
# keeps meaning exactly what it meant and nothing is added to 0.1.0.
TOPIC_PREFIX = "omniguard/state/v2"
LEGACY_TOPIC_PREFIX = "omniguard/state/v1"
QOS = 1
RETAIN = False


class TransportError(RuntimeError):
    """The transport could not accept the message; the caller spools instead."""


class TransportContractError(RuntimeError):
    """A transport returned something other than an `Acknowledgement`.

    This is a wiring defect, not a runtime fault, so it is raised rather than
    spooled. Silently reading a missing return value as delivery is the exact
    mislabelling this contract exists to prevent.
    """


class Acknowledgement(StrEnum):
    """What the transport actually confirmed about one publish call.

    `QUEUED` is the honest answer for a client that buffers locally and returns
    before the broker replies: the message may still be lost with the process.
    `ACKED` means this specific message was acknowledged by the broker (PUBACK
    at QoS 1). Waiting for that acknowledgement belongs in the worker, never in
    the producer's critical path.
    """

    QUEUED = "QUEUED"
    ACKED = "ACKED"


class Transport(Protocol):
    def publish(self, topic: str, payload: bytes, *, qos: int, retain: bool) -> Acknowledgement: ...


def topic_for(device_id: str) -> str:
    """Per-device topic. Validation happens here so no bad id reaches the broker."""
    return f"{TOPIC_PREFIX}/{validate_device_id(device_id)}"


@dataclass(frozen=True)
class PublishOutcome:
    """The observable result of one publish attempt.

    `broker_ack` is true only for `Acknowledgement.ACKED`; `acknowledgement`
    carries what the transport reported, so a queue-only client is visible
    instead of being flattened into "delivered". `dropped` marks an event that
    was neither acknowledged nor stored, so the caller never has to infer a loss
    from every other field being false.
    """

    event_id: str | None
    topic: str | None
    broker_ack: bool
    spooled: bool
    rejected: bool
    reason: str | None = None
    acknowledgement: Acknowledgement | None = None
    dropped: bool = False


@dataclass(frozen=True)
class PublisherCounters:
    published: int = 0
    spooled: int = 0
    drained: int = 0
    rejected_device_id: int = 0
    queued_unacked: int = 0
    dropped_unspoolable: int = 0


class TelemetryPublisher:
    """Turn a StateEvent into a TelemetryPayload and hand it to the transport."""

    def __init__(
        self,
        transport: Transport,
        spool: BoundedSpool,
        producer: ProducerIdentity,
        *,
        run_id: str,
        counter: SequenceCounter | None = None,
    ):
        if not isinstance(run_id, str) or not run_id.strip():
            raise IdentityError("run_id must be nonempty text")
        if not isinstance(producer, ProducerIdentity):
            raise IdentityError("producer must be a ProducerIdentity")
        self._transport = transport
        self._spool = spool
        self._producer = producer
        # Spooled entries outlive this process, so each one is stored under the
        # boot that produced it; a sequence range alone repeats on every restart.
        self._scope = SpoolScope(producer.producer_id, producer.boot_id, producer.boot_started_at)
        self._run_id = run_id
        self._counter = counter or SequenceCounter()
        self._counters = PublisherCounters()

    @property
    def counters(self) -> PublisherCounters:
        return self._counters

    def build(self, event: StateEvent) -> tuple[EventIdentity, TelemetryPayload]:
        """Assign the next sequence and derive the retry-stable identity."""
        identity = EventIdentity(self._producer, self._counter.next())
        payload = TelemetryPayload(SCHEMA_VERSION, self._run_id, event_id(identity, event), event)
        return identity, payload

    def _acknowledge(self, topic: str, body: bytes) -> Acknowledgement:
        """Publish once and hold the transport to the acknowledgement contract."""
        acknowledgement = self._transport.publish(topic, body, qos=QOS, retain=RETAIN)
        if not isinstance(acknowledgement, Acknowledgement):
            raise TransportContractError(
                "transport.publish must return an Acknowledgement, "
                f"got {type(acknowledgement).__name__}; a missing return value "
                "cannot be read as a broker acknowledgement"
            )
        return acknowledgement

    def _store(self, sequence: int, body: bytes, *, now: float) -> bool:
        """Keep a durable copy. False means the event was lost here, not stored."""
        stored = self._spool.append(sequence, body, now=now, scope=self._scope)
        if stored:
            self._counters = replace(self._counters, spooled=self._counters.spooled + 1)
        else:
            self._counters = replace(
                self._counters, dropped_unspoolable=self._counters.dropped_unspoolable + 1
            )
        return stored

    def publish(self, event: StateEvent, *, now: float) -> PublishOutcome:
        try:
            topic = topic_for(event.device_id)
        except IdentityError as exc:
            # No sequence is consumed: a rejected event never entered the stream.
            self._counters = replace(
                self._counters, rejected_device_id=self._counters.rejected_device_id + 1
            )
            return PublishOutcome(None, None, False, False, True, str(exc))

        identity, payload = self.build(event)
        body = canonical_bytes(wrap(identity, payload.to_dict()))
        try:
            acknowledgement = self._acknowledge(topic, body)
        except TransportError as exc:
            stored = self._store(identity.sequence, body, now=now)
            return PublishOutcome(
                payload.event_id, topic, False, stored, False, reason=str(exc), dropped=not stored
            )

        if acknowledgement is Acknowledgement.QUEUED:
            # The client holds the bytes but the broker has not answered for them,
            # so the durable copy stays. The repeat this may cause is expected at
            # QoS 1 and is removed by the consumer's event_id dedup, ADR-0003 §8.
            stored = self._store(identity.sequence, body, now=now)
            self._counters = replace(
                self._counters, queued_unacked=self._counters.queued_unacked + 1
            )
            return PublishOutcome(
                payload.event_id,
                topic,
                False,
                stored,
                False,
                reason="transport queued the message without a broker acknowledgement",
                acknowledgement=acknowledgement,
                dropped=not stored,
            )

        self._counters = replace(self._counters, published=self._counters.published + 1)
        return PublishOutcome(
            payload.event_id, topic, True, False, False, acknowledgement=acknowledgement
        )

    def drain(self, *, now: float) -> list[PublishOutcome]:
        """Retry spooled entries oldest first; stop at the first that is not acked.

        The stored bytes are republished unchanged, so the identity a consumer
        already saw cannot change on retry. An entry is removed only against a
        broker acknowledgement: a transport that merely queues the retry keeps
        the durable copy, since nothing yet shows the message left this host.
        """
        outcomes: list[PublishOutcome] = []
        self._spool.enforce(now=now)
        for entry in self._spool.pending():
            body = self._spool.read(entry)
            document = unwrap(json.loads(body.decode("utf-8"))).payload
            topic = topic_for(document["event"]["device_id"])
            try:
                acknowledgement = self._acknowledge(topic, body)
            except TransportError as exc:
                outcomes.append(
                    PublishOutcome(document["event_id"], topic, False, True, False, reason=str(exc))
                )
                break
            if acknowledgement is Acknowledgement.QUEUED:
                outcomes.append(
                    PublishOutcome(
                        document["event_id"],
                        topic,
                        False,
                        True,
                        False,
                        reason="transport queued the retry without a broker acknowledgement",
                        acknowledgement=acknowledgement,
                    )
                )
                break
            self._spool.remove(entry)
            self._counters = replace(self._counters, drained=self._counters.drained + 1)
            outcomes.append(
                PublishOutcome(
                    document["event_id"], topic, True, False, False, acknowledgement=acknowledgement
                )
            )
        return outcomes
