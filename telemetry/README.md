# R3 — Gabriel

Develop with `stubs.fake_telemetry.fake_telemetry()` and `core.schema.TelemetryPayload`.
Real gateway events cross a Unix socket; do not add a lab Internet route.

## Transport contract

`mqtt.PahoTransport` now provides a Paho 2.1.0 MQTT 3.1.1 worker transport with
per-message PUBACK checking. Client authentication, bounded queues and network-loop
lifecycle are explicit in `lab/telemetry_probe.py`; use the handoff on the producer
path. Real broker and restart retry evidence is in
[KAN38_MQTT_VALIDATION](../docs/KAN38_MQTT_VALIDATION.md). This is not DB/G10 evidence.

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
| `uds.py` | gateway socket bridge: frame to validated 0.1.0 StateEvent, then to the sink |
| `consumer.py` | the receiving half: envelope to one idempotent PostgreSQL transaction, boot verdicts kept |

`consumer.py` decides; `platform/consume.py` wires it to the broker and to psql, the
same split `publisher.py` has with `mqtt.py`. Four properties are structural there:
redelivery is `ON CONFLICT (event_id) DO NOTHING` and is counted apart from a stored
event; a message is acknowledged only after its transaction commits, so a database
outage leaves the backlog with the broker instead of dropping it; the boot verdict is
remembered only once it is durable, never before; and the ledger is rebuilt from the
database at startup, so a restart cannot turn an `UNORDERED` boot into an `ORDERED` one
by forgetting it. The last of those is R1's acceptance condition on KAN-40.

A transport reports an `Acknowledgement`, never `None`: `QUEUED` means the client
took the bytes, `ACKED` means the broker sent PUBACK, and only `ACKED` sets
`broker_ack`. A queued message keeps its spool entry, because a local queue does
not show that anything left this host. See ADR-0003 section 7.1.

`publisher.py` is worker-side code and makes no non-blocking promise: it calls
the broker and the disk on the calling thread. Enforcement talks to `handoff.py`
instead, whose `submit()` only does a bounded `put_nowait`. A full queue returns
`OVERFLOWED` rather than waiting, and a stalled transport or a failing disk holds
or fails the worker alone. See ADR-0003 section 9.

`uds.py` splits on purpose. Its stream half — framing, decode, handing an event
to the sink — needs no socket and runs everywhere. Its socket half — bind, `0600`
mode, `SO_PEERCRED` — is Linux only: **CPython on Windows does not expose
`socket.AF_UNIX` at all**, measured on 3.14.7, so those tests skip here and a
skipped test is not a passing one. `peer_verification` reads `VERIFIED` only
where credentials were actually read, so no Windows run can be written up as
peer-verified.

The transport is injected so the fault matrix runs as unit tests. Those tests are
not delivery evidence; the real broker and database path is proved on Compose
under KAN-50.

No real MQTT client is vendored yet, so no delivery is claimed anywhere. Adding
one is R2's to do — it changes the locks, which R3 does not touch — and it must
go in `requirements-ml.lock`, the only lock CI installs. ADR-0003 section 7.2
records what the client has to be able to do, chiefly reporting PUBACK per
message so `ACKED` means something.

Remaining work: real StateEvent-to-MQTT delivery evidence and the Linux
peer-credential run (KAN-38), database schema and migrations (KAN-39), consumer
(KAN-40), dashboard (KAN-41).

## V3 design follow-up

V3: StateEvent karar bilgisidir; applied firewall state veya anomaly score
alanlarını ondan uydurmayın. Ek versioned envelope, sequence/dedup, bounded spool
ve crash/retry semantiği [ADR-0002 önerisindedir](../docs/adr/0002-bounded-containment.md).
Docker lab ile UDS dosya görünürlüğü ayrı mount/permission tasarımı gerektirir.
