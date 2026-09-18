"""Containment-leakage accounting with explicit timing uncertainty.

This module correlates three independent facts from the same Linux boot:

1. a replay/source t0 *submission interval*;
2. an enforcer call interval from apply-begin to successful return/readback;
3. sink-observed delivered packets with their actual IPv4 L3 length.

Neither interval is collapsed to a magic instant. Packets observed inside t0 or apply
intervals are reported as uncertainty buckets. Packets observed after apply ACK are
kept separate because they can be in-flight traffic or evidence of a bypass; they are
not silently counted as pre-containment leakage.

The types here are measurement artefacts, not runtime wire contracts.
"""

from dataclasses import asdict, dataclass
from enum import StrEnum


class LeakageStatus(StrEnum):
    COMPLETE = "COMPLETE"
    CENSORED = "CENSORED"


@dataclass(frozen=True)
class MonotonicInterval:
    boot_id: str
    begin_ns: int
    end_ns: int
    meaning: str

    def __post_init__(self) -> None:
        if not isinstance(self.boot_id, str) or not self.boot_id.strip():
            raise ValueError("boot_id must be nonempty text")
        if type(self.begin_ns) is not int or type(self.end_ns) is not int:
            raise ValueError("monotonic interval bounds must be integer nanoseconds")
        if self.begin_ns < 0 or self.end_ns < self.begin_ns:
            raise ValueError("monotonic interval must be nonnegative and ordered")
        if not isinstance(self.meaning, str) or not self.meaning.strip():
            raise ValueError("interval meaning must be nonempty text")


@dataclass(frozen=True)
class SinkDelivery:
    boot_id: str
    observed_ns: int
    l3_bytes: int

    def __post_init__(self) -> None:
        if not isinstance(self.boot_id, str) or not self.boot_id.strip():
            raise ValueError("boot_id must be nonempty text")
        if type(self.observed_ns) is not int or self.observed_ns < 0:
            raise ValueError("observed_ns must be a nonnegative integer")
        if type(self.l3_bytes) is not int or self.l3_bytes < 1:
            raise ValueError("l3_bytes must be a positive integer")


@dataclass(frozen=True)
class LeakageBucket:
    packets: int = 0
    l3_bytes: int = 0

    def __post_init__(self) -> None:
        if type(self.packets) is not int or self.packets < 0:
            raise ValueError("packets must be a nonnegative integer")
        if type(self.l3_bytes) is not int or self.l3_bytes < 0:
            raise ValueError("l3_bytes must be a nonnegative integer")

    def add(self, delivery: SinkDelivery) -> "LeakageBucket":
        return LeakageBucket(self.packets + 1, self.l3_bytes + delivery.l3_bytes)

    def __add__(self, other):
        if not isinstance(other, LeakageBucket):
            return NotImplemented
        return LeakageBucket(self.packets + other.packets, self.l3_bytes + other.l3_bytes)


@dataclass(frozen=True)
class LeakageSummary:
    status: LeakageStatus
    censor_reason: str | None
    before_t0: LeakageBucket
    t0_uncertain: LeakageBucket
    definite_pre_apply: LeakageBucket
    apply_uncertain: LeakageBucket
    post_ack: LeakageBucket
    uncontained_after_t0: LeakageBucket
    observed_after_t0: LeakageBucket
    lower_bound: LeakageBucket | None
    upper_bound: LeakageBucket | None

    def to_dict(self) -> dict:
        return asdict(self)


def summarize_leakage(
    t0: MonotonicInterval,
    apply: MonotonicInterval | None,
    deliveries,
    *,
    sink_complete: bool,
    censor_reason: str | None = None,
) -> LeakageSummary:
    """Classify sink deliveries without pretending uncertain boundaries are exact.

    A COMPLETE run gets leakage bounds:
    - lower bound: packets definitely after t0 submission and before apply began;
    - upper bound: lower + packets inside the t0 interval + packets inside apply.

    Post-ACK deliveries are never folded into either bound. They remain explicit
    evidence of in-flight traffic or a possible enforcement bypass.

    If containment was not observed, the sink was incomplete, or the caller gives a
    censor reason (timeout/miss/etc.), bounds are None. Observed traffic is still kept.
    """
    if not isinstance(t0, MonotonicInterval):
        raise TypeError("t0 must be a MonotonicInterval")
    if apply is not None:
        if not isinstance(apply, MonotonicInterval):
            raise TypeError("apply must be a MonotonicInterval or None")
        if apply.boot_id != t0.boot_id:
            raise ValueError("t0 and apply intervals come from different boots")
        if apply.begin_ns < t0.begin_ns:
            raise ValueError("apply interval begins before t0")
    if not isinstance(sink_complete, bool):
        raise TypeError("sink_complete must be bool")
    if censor_reason is not None and (
        not isinstance(censor_reason, str) or not censor_reason.strip()
    ):
        raise ValueError("censor_reason must be nonempty text when supplied")

    before_t0 = LeakageBucket()
    t0_uncertain = LeakageBucket()
    definite = LeakageBucket()
    apply_uncertain = LeakageBucket()
    post_ack = LeakageBucket()
    uncontained = LeakageBucket()
    observed_after_t0 = LeakageBucket()

    for delivery in deliveries:
        if not isinstance(delivery, SinkDelivery):
            raise TypeError("deliveries must contain SinkDelivery values")
        if delivery.boot_id != t0.boot_id:
            raise ValueError("sink delivery comes from a different boot")
        timestamp = delivery.observed_ns
        if timestamp < t0.begin_ns:
            before_t0 = before_t0.add(delivery)
            continue
        if timestamp <= t0.end_ns:
            t0_uncertain = t0_uncertain.add(delivery)
            continue

        observed_after_t0 = observed_after_t0.add(delivery)
        if apply is None:
            uncontained = uncontained.add(delivery)
        elif timestamp < apply.begin_ns:
            definite = definite.add(delivery)
        elif timestamp <= apply.end_ns:
            apply_uncertain = apply_uncertain.add(delivery)
        else:
            post_ack = post_ack.add(delivery)

    reason = censor_reason
    if not sink_complete:
        reason = reason or "sink_incomplete"
    if apply is None:
        reason = reason or "no_containment_ack"

    if reason is None:
        status = LeakageStatus.COMPLETE
        lower = definite
        upper = t0_uncertain + definite + apply_uncertain
    else:
        status = LeakageStatus.CENSORED
        lower = upper = None

    return LeakageSummary(
        status=status,
        censor_reason=reason,
        before_t0=before_t0,
        t0_uncertain=t0_uncertain,
        definite_pre_apply=definite,
        apply_uncertain=apply_uncertain,
        post_ack=post_ack,
        uncontained_after_t0=uncontained,
        observed_after_t0=observed_after_t0,
        lower_bound=lower,
        upper_bound=upper,
    )
