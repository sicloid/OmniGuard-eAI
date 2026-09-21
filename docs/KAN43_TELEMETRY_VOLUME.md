# KAN-43 — telemetry byte volume: what is counted, and where

Owner: R3 (Gabriel). **Method only. No measured figures are recorded here yet** — this
document fixes what will be counted before the run that counts it, and the run itself
is listed under "What is still missing" at the end.

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
overstate the per-event cost. Connect and publish phases are counted apart and
reported apart.

### The derived figure, checked against the wire

`lab/telemetry_volume_probe.py` publishes real events through the relay to a real
broker so the derived PUBLISH size can be held against the socket. It is an
instrument check and says so in its own output — there is no frozen manifest behind
it, so **it is not the card's measurement run** and none of its numbers are results.

On 21 September 2026, 20 events on the Compose broker: 11,176 bytes derived against
**11,178 bytes counted** leaving the host in the publish phase. The two-byte
difference is the DISCONNECT packet, which is sent after the mark and is not part of
any event. PUBACKs came back at exactly 4 bytes each, and the connection handshake
cost 91 bytes out and 4 in — paid once, and kept out of the per-event figure.

So `mqtt_publish_packet` is a derivation that has been shown to match the wire rather
than an estimate standing in for it. It stays labelled `derived` regardless: the next
run's broker, client or keepalive settings can move the wire figure, and only the
counter would notice.

### The whole chain, including the socket Windows cannot open

`lab/Dockerfile.kan43` builds the probe's environment from the project's own
hash-checked `requirements.lock`, and `--uds` drives the real chain instead of calling
the publisher directly: the gateway's part writes framed StateEvents to a Unix socket,
`CountingAdapter` reads them, the bounded handoff carries them to the worker, and the
worker publishes. The UDS boundary is the one CPython cannot open on Windows, so its
figure is measured in a container rather than estimated on the development machine.

Same day, 20 events, Linux container on the Compose network, all four boundaries
observed and `not_observed` empty:

| Boundary | Bytes per event |
|---|---:|
| `uds_frame` | 185.30 |
| `payload_json` | 317.30 |
| `mqtt_application` | 551.85 |
| `mqtt_publish_packet` (derived) | 558.85 |
| wire, counted | 558.95 |

The producer wrote **3,706 bytes** to the socket and the adapter counted **3,706** —
the two sides were measured independently and agree exactly. 20 of 20 events were
acknowledged and delivered to a subscriber, the handoff processed 20 with no overflow,
and the peer was `VERIFIED` through real `SO_PEERCRED`.

The spread is the point of the card. One event costs 185 bytes at the socket and 559
on the wire: the UDS boundary carries only the six-field StateEvent, while MQTT
carries the 0.1.0 payload inside a versioned envelope, under a topic, in a PUBLISH
packet. A single "telemetry byte" figure would have silently picked one of these and
been wrong about the other three by up to 3×.

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

The measurement is bound to one run through the KAN-42 `ExperimentManifest`, which is
the mechanism this repository already uses to declare a run before it happens:
`freeze()` seals the configuration and provenance before the first byte moves, the
volume summary is written into `measurements` at `close()`, and a run that dies leaves
an `incomplete` manifest rather than none. There is no second spec file for this card:
nothing here is selected by looking at the results, so there is no choice that needs
to be pre-committed beyond the sealed run itself.

**Format `/2` is required** — `ObservedFromR2` and the at-close observation phase.
That contract arrives with PR #43, so the sealed run cannot be performed before it
merges.

## What is still missing

1. **The real run.** Compose broker, the real publisher and consumer, the relay in
   between, a frozen manifest, and the resulting figures published here. No synthetic
   or stub output substitutes for it.
2. **The manifest binding**, once `/2` is on `main`.
3. **Owner review** of the run and this document.

Until all three exist, this card is a method and a set of instruments, and it says so.
