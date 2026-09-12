"""ADR-0003 StateEvent publisher: identity, topic, QoS and spool fallback.

The transport is injected so the fault matrix (broker down, full spool, repeated
delivery, out-of-order retry) runs as ordinary unit tests. A passing fake is not
delivery evidence: the real broker and database path is proved separately on
Compose under KAN-50.

Publishing never blocks the caller. A transport failure spools; a full spool
drops the oldest entry and records the loss. Enforcement must not wait on
telemetry, so no path here raises into the caller's critical path.
"""

import json
from dataclasses import dataclass, replace
from typing import Protocol

from core.schema import SCHEMA_VERSION, StateEvent, TelemetryPayload
from telemetry.canonical import canonical_bytes
from telemetry.identity import (
    EventIdentity,
    IdentityError,
    ProducerIdentity,
    SequenceCounter,
    event_id,
    validate_device_id,
)
from telemetry.spool import BoundedSpool

TOPIC_PREFIX = "omniguard/state/v1"
QOS = 1
RETAIN = False


class TransportError(RuntimeError):
    """The transport could not accept the message; the caller spools instead."""


class Transport(Protocol):
    def publish(self, topic: str, payload: bytes, *, qos: int, retain: bool) -> None: ...


def topic_for(device_id: str) -> str:
    """Per-device topic. Validation happens here so no bad id reaches the broker."""
    return f"{TOPIC_PREFIX}/{validate_device_id(device_id)}"


@dataclass(frozen=True)
class PublishOutcome:
    event_id: str | None
    topic: str | None
    broker_ack: bool
    spooled: bool
    rejected: bool
    reason: str | None = None


@dataclass(frozen=True)
class PublisherCounters:
    published: int = 0
    spooled: int = 0
    drained: int = 0
    rejected_device_id: int = 0


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
        self._transport = transport
        self._spool = spool
        self._producer = producer
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
        body = canonical_bytes(payload.to_dict())
        try:
            self._transport.publish(topic, body, qos=QOS, retain=RETAIN)
        except TransportError as exc:
            spooled = self._spool.append(identity.sequence, body, now=now)
            self._counters = replace(self._counters, spooled=self._counters.spooled + spooled)
            return PublishOutcome(payload.event_id, topic, False, spooled, False, str(exc))
        self._counters = replace(self._counters, published=self._counters.published + 1)
        return PublishOutcome(payload.event_id, topic, True, False, False)

    def drain(self, *, now: float) -> list[PublishOutcome]:
        """Retry spooled entries oldest first; stop at the first that fails again.

        The stored bytes are republished unchanged, so the identity a consumer
        already saw cannot change on retry.
        """
        outcomes: list[PublishOutcome] = []
        self._spool.enforce(now=now)
        for entry in self._spool.pending():
            body = self._spool.read(entry)
            document = json.loads(body.decode("utf-8"))
            topic = topic_for(document["event"]["device_id"])
            try:
                self._transport.publish(topic, body, qos=QOS, retain=RETAIN)
            except TransportError as exc:
                outcomes.append(
                    PublishOutcome(document["event_id"], topic, False, True, False, str(exc))
                )
                break
            self._spool.remove(entry)
            self._counters = replace(self._counters, drained=self._counters.drained + 1)
            outcomes.append(PublishOutcome(document["event_id"], topic, True, False, False))
        return outcomes
