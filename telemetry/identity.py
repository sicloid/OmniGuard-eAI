"""ADR-0003 producer identity, ordering and deterministic `event_id` derivation.

`event_id` is a UUID5 over the canonical encoding of the producing identity plus
the event's own fields. Re-delivering the same event therefore reproduces the
same identity, which is what `SCHEMA.md` requires across retries, while two
events sharing a timestamp stay distinct because the sequence differs.

Known limit, deliberately not closed here: a sequence assigned but lost to a
crash before the spool write is not reproduced on restart. The regenerated event
takes a new sequence and therefore a new identity, which the consumer stores as a
duplicate. KAN-38 tests exercise that window and KAN-50 reports its count.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from core.schema import StateEvent, number
from telemetry.canonical import canonical_bytes

# Derived from a stable name so the constant is auditable rather than magic.
# Value: 0c8c393e-8b98-5162-9afe-bec21f5d1345. Changing the name rewrites every
# historical identity and requires its own ADR.
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_DNS, "telemetry.omniguard.eai")

DEVICE_ID_PATTERN = re.compile(r"\A[A-Za-z0-9._-]{1,64}\Z")


class IdentityError(ValueError):
    """Identity inputs are unusable; no event is published under a guessed identity."""


def validate_device_id(device_id: str) -> str:
    """Reject identifiers that would break the MQTT topic or wildcard semantics."""
    if not isinstance(device_id, str) or not DEVICE_ID_PATTERN.match(device_id):
        raise IdentityError(
            "device_id must match [A-Za-z0-9._-]{1,64}; "
            "'/', '+', '#' and whitespace break topic structure"
        )
    return device_id


@dataclass(frozen=True)
class ProducerIdentity:
    """Stable installation id plus the identity of one process lifetime."""

    producer_id: str
    boot_id: str
    boot_started_at: float

    def __post_init__(self) -> None:
        for field in ("producer_id", "boot_id"):
            value = getattr(self, field)
            if not isinstance(value, str) or not value.strip():
                raise IdentityError(f"{field} must be nonempty text")
        number(self.boot_started_at, "boot_started_at")

    @classmethod
    def start(cls, producer_id: str, boot_started_at: float) -> ProducerIdentity:
        return cls(producer_id, str(uuid.uuid4()), boot_started_at)


class SequenceCounter:
    """Gapless per-boot counter starting at one."""

    def __init__(self, start: int = 0):
        if type(start) is not int or start < 0:
            raise IdentityError("sequence start must be a non-negative integer")
        self._value = start

    @property
    def value(self) -> int:
        return self._value

    def next(self) -> int:
        self._value += 1
        return self._value


@dataclass(frozen=True)
class EventIdentity:
    """One producing identity bound to one sequence number."""

    producer: ProducerIdentity
    sequence: int

    def __post_init__(self) -> None:
        if not isinstance(self.producer, ProducerIdentity):
            raise IdentityError("producer must be a ProducerIdentity")
        if type(self.sequence) is not int or self.sequence < 1:
            raise IdentityError("sequence must be a positive integer")

    def ordering_key(self) -> tuple[float, int]:
        """Order across restarts.

        A sequence alone cannot be compared between boots because it restarts at
        one, so the boot start time leads the key.
        """
        return (self.producer.boot_started_at, self.sequence)


def identity_document(identity: EventIdentity, event: StateEvent) -> dict:
    """The exact fields hashed into `event_id`, in one place so tests can pin it."""
    if not isinstance(event, StateEvent):
        raise IdentityError("event must be a StateEvent")
    return {
        "producer_id": identity.producer.producer_id,
        "boot_id": identity.producer.boot_id,
        "sequence": identity.sequence,
        "device_id": event.device_id,
        "previous_state": str(event.previous_state),
        "new_state": str(event.new_state),
        "timestamp": event.timestamp,
        "expires_at": event.expires_at,
        "reason": event.reason,
    }


def event_id(identity: EventIdentity, event: StateEvent) -> str:
    """Derive the retry-stable identity. Never read a clock or randomness here."""
    return str(uuid.uuid5(NAMESPACE, canonical_bytes(identity_document(identity, event))))
