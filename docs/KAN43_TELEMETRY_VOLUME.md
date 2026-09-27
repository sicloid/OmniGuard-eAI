# KAN-43 — telemetry byte volume: what is counted, and where

Owner: R3 (Gabriel). The method below was committed before the run that uses it
(`738b476`). The figures under "Results" come only from the two sealed runs in
`docs/evidence/KAN43_2026-09-23/`, and `verify.py` there re-derives every one of them
from the committed raw files.

The card asks for actual bytes per run and per unit time, with the JSON payload, the
UDS framing, MQTT and the total wire volume kept apart, and with duplicate/drop, spool
occupancy and delivery completeness beside them. It also says plainly that a
theoretical payload size is not a network cost. That sentence is the reason this
document exists: three of the four figures below are byte strings this host really
produced, one is derived from a protocol, and the fifth — the wire total — is counted
off the connection itself.

## The four boundaries

They carry four different documents. No one of them can stand in for another.

| Boundary | What is counted | How |
|---|---|---|
| `payload_json` | the 0.1.0 `TelemetryPayload` on its own | `len(canonical_bytes(payload))` |
| `uds_frame` | one gateway→host message, four-byte length prefix included | bytes the reader consumed off the socket |
| `mqtt_application` | envelope body + topic, as handed to the MQTT client | `len(topic.encode()) + len(body)` |
| `mqtt_publish_packet` | the PUBLISH packet MQTT 3.1.1 encodes for them | **derived** from the protocol |
| wire | TCP payload bytes on the broker connection, both directions | counted by a relay |

Two of these deserve their limits stated where the number is read, not in a footnote:

- **`payload_json` is never sent on its own.** It is nested verbatim inside the v2
  envelope. It is recorded so the schema's own cost can be separated from what
  wrapping and transporting it adds — not as a traffic figure.
- **`mqtt_application` is what the host offered the client.** It is not proof that the
  bytes left the host, for the same reason a local queue is not a broker
  acknowledgement (ADR-0003 §7). Only `broker_acknowledged` and the wire count say
  anything about that.

The UDS body is the six-field StateEvent message of ADR-0003 §2.1, and the MQTT body
is the envelope around the 0.1.0 payload. They are deliberately different documents,
which is exactly why the card asks for them separately: a single "telemetry byte"
figure would silently pick one of them.

## The wire count

`lab/mqtt_wire_counter.py` is a byte relay between the publisher and the broker. It
does not parse, re-buffer or modify anything, so its totals are the connection's own
bytes rather than a model of them: PUBLISH out, PUBACK and CONNACK in, and every
keepalive the client decided to send.

It counts **TCP payload bytes**. It does not count IP and TCP headers, retransmissions
or TLS record overhead, and the report says so in its own `not_counted` field. A
link-level figure needs a packet capture, and this card does not claim one.

`mark()` separates phases. The connection handshake costs its bytes once while PUBLISH
traffic repeats per event, so charging every event a share of the handshake would
overstate the per-event cost. Connect, publish and close phases are counted apart and
reported apart.

A mark is only exact at a protocol synchronisation point. The relay attributes bytes
to the segment that is current when it reads them, so a mark set with a packet in
flight could land it on either side. The relay counts before it forwards, so once the
client has seen CONNACK — or the PUBACK for the last PUBLISH — every byte of the phase
has been counted in both directions and nothing of the next has been sent. The sealed
run marks exactly there. The only traffic such a mark cannot pin down is what neither
side asked for, a keepalive PINGREQ/PINGRESP; it would show as a nonzero residue in
the reconciliation below rather than being folded into a per-event cost.

`relay_recv_calls` in the relay's report is how many `recv()` calls the relay made. It
is an artefact of the relay's own buffering — neither a packet count nor how the broker
saw the connection segmented — and nothing is divided by it.

`mqtt_publish_packet` stays labelled `derived` even where it matches the counted wire
exactly: a different broker, client or keepalive setting can move the wire figure, and
only the counter would notice.

`lab/telemetry_volume_probe.py` remains as an instrument check against a real broker. It
has no frozen manifest behind it, says so in its own output, and none of its numbers
are results.

## Per run and per unit time

A rate needs a denominator that is honest about what it counts, which is the mistake
KAN-51 had to correct mid-run. Two are reported, never mixed:

- **per run** — totals over one manifest run id, divided by the events that were
  actually acknowledged, not by the events the host hoped it had sent;
- **per unit time** — totals divided by the run's own measured span, taken from the
  `ExperimentManifest` window (`started_at_unix` to `closed_at_unix`), not from a
  wall-clock guess.

## Counters this card does not own

Duplicate, drop, spool occupancy and completeness already have owners, and they are
carried through unchanged rather than re-implemented:

| Figure | Owner |
|---|---|
| queue overflow, events dropped at the handoff | `telemetry/handoff.py` |
| spooled, drained, queued-unacked, dropped-unspoolable | `PublisherCounters` |
| spool occupancy and per-boot loss | `SpoolCounters`, `ScopeLoss` |
| stored rows, duplicates suppressed at `event_id` | `telemetry/consumer.py`, the events table |

Delivery completeness is the consumer's committed rows for the run id, not the
publisher's view of its own success. A missing counter is reported as missing and is
never averaged in as zero.

## How a run is sealed

The measurement is bound to one run through the KAN-42 `ExperimentManifest` (`/2`).
`lab/kan43_sealed_run.py` calls `freeze()` before the first byte moves; the sealed
`config` holds the event schedule, the policy block (`omniguard-policy-config/1`, the
Lead's N=2 and 300 s lease) and the SHA-256 of every file on the measured path, and the
figures are written into `measurements` at `close()`. There is no second spec file:
nothing here is selected by looking at the results.

The chain is the shipped one from the policy to the database. The real `DevicePolicy`
emits the StateEvents from scripted detections — byte volume depends on the events,
not on how a model scored a window — and the real `GatewayEventBridge` writes them to
the socket one connection per event. Delivery completeness is the consumer's committed
rows for the run id, exported from PostgreSQL after the run.

## Results

Two sealed runs, 23 September 2026, Docker Desktop Linux engine, Compose broker and
database. Each is 20 quarantine cycles (60 StateEvents) handed to the bridge at once.

| | run 1 (`listen(1)`) | run 2 (current code) |
|---|---:|---:|
| produced by the policy | 60 | 60 |
| delivered over the UDS | 47 | 60 |
| **lost at the UDS, counted** | **13** | 0 |
| broker acknowledged | 47 | 60 |
| committed rows (unique `event_id`, sequence 1..N) | 47 | 60 |
| manifest window | 2.898 s | 2.878 s |

**Run 1 found a loss.** `telemetry/uds.py` listened with a backlog of 1 while the gateway
connects once per event; on Linux a `connect()` to a full AF_UNIX backlog fails at once
with `EAGAIN`. The bridge counted 13 failures, the UDS reconciliation shows the same
13 frames missing (−2,162 bytes), and nothing downstream claimed them. The backlog is
now 64 with a regression test; run 2 is the same schedule on the fixed code. Run 1 is
kept, not replaced. A burst larger than the backlog still loses events at this
boundary, counted the same way.

Bytes per acknowledged event, run 2:

| Boundary | Bytes / event | min–max |
|---|---:|---:|
| `uds_frame` | 172.03 | 159–187 |
| `payload_json` (never sent alone) | 303.03 | 290–318 |
| `mqtt_application` | 501.88 | 489–517 |
| `mqtt_publish_packet` (derived) | 508.88 | 496–524 |
| wire to broker, publish phase (counted) | 508.88 | — |
| wire from broker, publish phase (counted) | 4.00 | — |

The connection handshake is 91 bytes out and 4 in, paid once per connection and kept
out of the per-event figures; closing is one 2-byte DISCONNECT.

Reconciliation, both runs: the publish phase to the broker counted **exactly** the
derived PUBLISH total (30,533 = 30,533 in run 2), the broker returned exactly 4 bytes
per acknowledged event, and in run 2 the adapter counted exactly the bytes the gateway
wrote (10,322 = 10,322). No keepalive landed in either publish phase.

Per unit time, over the manifest window, run 2: 3,586.9 B/s at the UDS and 10,727.2 B/s
on the wire in both directions. **These are burst rates** — the whole schedule is
handed over at once — and are not a deployment load; a deployment's rate is these
per-event costs times its own event rate.

One event costs 172 bytes at the socket and 509 on the wire: the UDS carries only the
six-field StateEvent, MQTT carries the 0.1.0 payload inside a versioned envelope, under
a topic, in a PUBLISH packet. A single "telemetry byte" figure would have silently
picked one of these and been wrong about the others by up to 3×.

## Limits

- One Docker Desktop host (x86_64), not a Pi; the Pi's figures belong to KAN-46/53.
- TCP payload bytes only: no IP/TCP headers, retransmissions or TLS.
- One device and one policy schedule. Event sizes vary with the reason string and the
  float representation of timestamps (the 159–187 byte spread at the UDS), not with
  the schedule's length.
- R1 provenance is `not_supplied`: no dataset or model is read.
- Owner review of the runs and this document is still open.
