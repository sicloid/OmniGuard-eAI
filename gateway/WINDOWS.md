# KAN-28: bounded five-second device windows

`gateway.windows.TumblingWindows` buffers immutable PacketTuple references by
device in half-open, epoch-aligned `[start, start+5)` intervals. All directions
are preserved; the shared extractor selects its approved input scope. It performs
no feature extraction, inference, policy or I/O. `PacketWindow` is an in-memory
buffer result, not a new wire envelope or proof of healthy capture.

## Integration

Use ordered UTC event time in both PCAP and live paths. Start at an aligned
boundary; explicitly discard the capture's initial partial interval. For each
packet, **process returned closed windows before adding the packet**:

```python
from gateway.windows import TumblingWindows

windows = TumblingWindows(start=0)  # real runs use their aligned UTC start
for packet in ordered_packets:
    for closed in windows.advance(packet.timestamp):
        consume_packet_window(closed)  # future R1 extractor integration
    windows.add(packet)
```

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
- Capture errors/drops must call `invalidate(reason)`. Continuing to add during
  that interval raises WindowError. Advancing to the next interval permits recovery.
- The caller must record errors/invalid_reason before recovery clears the reason.
  This is local diagnostics; versioned ObservationHealth remains KAN-63 review work.
- A late packet cannot amend already returned windows. The runtime must record
  the late event and invalidate policy evidence rather than claiming complete capture.
- Adding a next-interval packet without advancing raises a usage error without
  consuming it; the caller can close/process the old interval and retry that packet.

Only active buffers are retained: device churn across intervals does not grow
an identity/history dictionary. Empty intervals do not create model inputs.

## Evidence and remaining integration

Ten tests cover exact boundaries, per-device partition, long gaps, incomplete EOF,
explicit loss/recovery, all three capacity bounds, backward/late input, closed
history, equal timestamps/directions and invalid clock/configuration inputs.
Run `.venv/bin/python -m unittest discover -s tests -p test_windows.py -v`.

This implements the KAN-28 buffering/boundary component. Live watermark/health
integration needs KAN-27 and the reviewed KAN-63 record design; N-reset belongs to
KAN-30. Real extractor parity and G8 require the R1 implementation. These are not
claimed complete by the buffer tests. Owner review is required before closure.
