"""Small shared boundary outcomes with no publisher, spool or socket dependency."""

from enum import StrEnum


class HandoffOutcome(StrEnum):
    """What a bounded handoff did with one submitted event."""

    ACCEPTED = "ACCEPTED"
    OVERFLOWED = "OVERFLOWED"
    REFUSED = "REFUSED"
