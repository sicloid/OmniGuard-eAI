# KAN-28: bounded five-second device windows

`gateway.windows.TumblingWindows` buffers immutable PacketTuple references by
device in half-open, epoch-aligned `[start, start+5)` intervals. All directions
are preserved; the shared extractor selects its approved input scope. It performs
no feature extraction, inference, policy or I/O. `PacketWindow` is an in-memory
buffer result, not a new wire envelope or proof of healthy capture.

## Integration

Use ordered UTC event time in both PCAP and live paths. Start at an aligned
boundary; explicitly discard the capture's initial partial interval. The runtime
composition uses the same pure extractor as the offline path:

```python
from gateway.pipeline import WindowFeaturePipeline

pipeline = WindowFeaturePipeline(start=0)  # real runs use their aligned UTC start
while running:
    for vector in pipeline.capture_once(capture):
        consume_feature_vector(vector)
```

`capture_once` advances on an actual packet's ordered kernel UTC timestamp before
buffering that packet. Capture exceptions invalidate and discard the entire active
interval. A timeout or filtered frame returns no vector and does not advance time.
Call `pipeline.advance(watermark)` only for a separately established trusted
event-time watermark.

On live idle ticks, call `advance` only when the capture path guarantees all earlier
packets have been delivered or reports its loss. A wall-clock reading alone is
not a capture watermark. Never advance past queued earlier packets. Monotonic
performance durations must not be used as UTC packet timestamps. There is no
hidden clock, queue, reorder buffer or thread.

EOF does not complete the last partial interval; no `flush` pads it into a full
window. A trusted observation watermark at an exact end closes that interval.
A long gap emits only actual buffered windows; it does not iterate across missing
seconds/devices or synthesize zeros. Absence is not benign evidence. Downstream
policy must reset streaks on gaps/errors once KAN-30 is implemented.

## Failure and bounds

Defaults: 64 active devices, 2,048 packets/device, 32,768 total buffered packets.
These are configurable software limits, not measured optimal hardware budgets.
Closed output is owned by the caller, which must also bound its output queue.

- Late/out-of-order packets, backward watermark and invalid clock values are errors.
- Capacity overflow raises WindowCapacityError and discards the entire active
  interval, including other devices; no truncated feature input escapes.
- `WindowFeaturePipeline.capture_once` automatically invalidates on capture errors.
  Direct users of `TumblingWindows` must call `invalidate(reason)` themselves.
  Continuing to add during that interval raises WindowError. Advancing to the next
  interval permits recovery.
- The caller must record errors/invalid_reason before recovery clears the reason.
  This is local diagnostics; versioned ObservationHealth remains follow-up contract work.
- A late packet cannot amend already returned windows. The runtime must record
  the late event and invalidate policy evidence rather than claiming complete capture.
- Adding a next-interval packet without advancing raises a usage error without
  consuming it; the caller can close/process the old interval and retry that packet.

Only active buffers are retained: device churn across intervals does not grow
an identity/history dictionary. Empty intervals do not create model inputs.

## Evidence and scope

Ten tests cover exact boundaries, per-device partition, long gaps, incomplete EOF,
explicit loss/recovery, all three capacity bounds, backward/late input, closed
history, equal timestamps/directions and invalid clock/configuration inputs.
Four pipeline tests cover capture/extractor parity, idle/non-EGRESS behavior,
capture-failure invalidation/recovery and independent device vectors.

`bash lab/run_live_docker.sh` adds a real AF_PACKET → PacketTuple → window →
FeatureVector check in an isolated namespace. Four packets cross an epoch boundary;
the first completed window must contain the first three packets, produce `pkt_count=3`
and `l3_bytes_sum=180`, and report zero socket drops. The existing overflow oracle
continues to prove that detected capture loss fails explicitly.

This implements packet-driven window/extractor composition without a wire change.
It does not complete KAN-28's live idle/stale acceptance: after a packet at 101 and
only idle reads, a packet at 1000 can still return the old [100,105) vector without
a stale indication. Safe source-supported idle progress, explicit stale/gap handoff,
startup partial-window handling and shutdown loss propagation need implementation
and fault evidence. The current lab oracle closes using another packet; it does not
prove idle closure. N policy itself remains KAN-30.
