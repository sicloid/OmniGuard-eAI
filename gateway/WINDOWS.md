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
try:
    while running:
        vectors = pipeline.capture_once(capture)
        observe_continuity(pipeline.status, pipeline.reset_generation)
        for vector in vectors:
            consume_feature_vector(vector)
finally:
    pipeline.close_capture(capture)
```

`capture_once` advances on an actual packet's ordered kernel UTC timestamp before
buffering that packet. Capture exceptions invalidate and discard the entire active
interval. `LiveCapture.read_progress` supplies idle progress only after a real
socket timeout and successful loss/clock checks. Filtered frames and legacy
`read()` returning None do not advance time. Call `pipeline.advance(watermark)`
only for separately established event-time progress.

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
Pipeline tests cover capture/extractor parity, idle/non-EGRESS behavior,
capture-failure invalidation/recovery, stale windows, startup, shutdown and devices.

`bash lab/run_live_docker.sh` adds a real AF_PACKET → PacketTuple → window →
FeatureVector check in an isolated namespace. Three packets are followed by silence;
the completed window must produce `pkt_count=3` and `l3_bytes_sum=180` with zero
socket drops. The overflow oracle now also verifies pipeline invalidation.

## Idle, freshness and policy handoff

The updated oracle sends only three packets and then stays silent. Socket timeout
progress closes the window without a fourth packet. The progress cutoff is sampled
before recvmsg and reduced by 100 ms; queued frames are consumed before an idle
cutoff is emitted. UTC/monotonic offset drift exceeding 100 ms or clock sampling
uncertainty above 10 ms fails the capture session. These conservative operational
bounds are not tuned model thresholds. Kernel timestamp ordering remains required;
late timestamps fail the session. NIC/upstream loss remains outside socket evidence.
Live packets older than one second or over 100 ms in the future are rejected.

The pipeline rejects windows closed more than `max_lateness` (default one second)
after their end. It skips packets preceding the configured aligned start only
during startup; subsequent late packets remain errors. On exit, callers use
`close_capture(capture)` to check final losses and discard partial EOF.

`status` and `reset_generation` are local diagnostics, not a new wire envelope.
The generation increases on invalid, stale and empty evidence; KAN-30 must observe
it even when no feature is returned and reset all affected streaks. Per-device gaps
must also be detected from consecutive FeatureVector window starts (a different
device's activity does not prove this device was observed). No unbounded device
history or output queue is added here. The N policy implementation remains KAN-30.
