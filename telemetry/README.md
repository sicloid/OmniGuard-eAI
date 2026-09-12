# R3 — Gabriel

Develop with `stubs.fake_telemetry.fake_telemetry()` and `core.schema.TelemetryPayload`.
Real gateway events cross a Unix socket; do not add a lab Internet route.

## Transport contract

[ADR-0003](../docs/adr/0003-telemetry-framing.md) defines framing, identity,
topic, QoS, spool and ACK semantics. It is **PROPOSED**: the modules here follow
it, but the contract is not team-approved. Nothing is added to the frozen `0.1.0`
payload: the ordering metadata a consumer needs rides in a separately versioned
envelope that nests the 0.1.0 document verbatim, published to
`omniguard/state/v2/<device_id>`. The `v1` topic keeps its exact old meaning, as
ADR-0002 asks. See ADR-0003 sections 5.1 and 5.2.

| Module | Responsibility |
|---|---|
| `canonical.py` | one deterministic JSON encoding, used on the wire and for `event_id` |
| `framing.py` | four-byte length prefix, `MAX_FRAME` checked before the body is read |
| `identity.py` | producer/boot/sequence, `device_id` rules, UUID5 `event_id` |
| `envelope.py` | versioned transport envelope, ordering key, boot/clock ledger |
| `spool.py` | byte and age bounds, journalled oldest-first eviction, per-boot drop counters |
| `publisher.py` | topic, QoS 1, injected transport, spool fallback and drain |
| `handoff.py` | bounded non-blocking queue; the worker owns the transport and spool |

A transport reports an `Acknowledgement`, never `None`: `QUEUED` means the client
took the bytes, `ACKED` means the broker sent PUBACK, and only `ACKED` sets
`broker_ack`. A queued message keeps its spool entry, because a local queue does
not show that anything left this host. See ADR-0003 section 7.1.

`publisher.py` is worker-side code and makes no non-blocking promise: it calls
the broker and the disk on the calling thread. Enforcement talks to `handoff.py`
instead, whose `submit()` only does a bounded `put_nowait`. A full queue returns
`OVERFLOWED` rather than waiting, and a stalled transport or a failing disk holds
or fails the worker alone. See ADR-0003 section 9.

The transport is injected so the fault matrix runs as unit tests. Those tests are
not delivery evidence; the real broker and database path is proved on Compose
under KAN-50. Remaining work: UDS host adapter (KAN-38), database schema and
migrations (KAN-39), consumer (KAN-40), dashboard (KAN-41).

## V3 design follow-up

V3: StateEvent karar bilgisidir; applied firewall state veya anomaly score
alanlarını ondan uydurmayın. Ek versioned envelope, sequence/dedup, bounded spool
ve crash/retry semantiği [ADR-0002 önerisindedir](../docs/adr/0002-bounded-containment.md).
Docker lab ile UDS dosya görünürlüğü ayrı mount/permission tasarımı gerektirir.
