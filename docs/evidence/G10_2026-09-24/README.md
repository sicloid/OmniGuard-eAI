# G10 gate run (KAN-50) — 24 September 2026

Recompute from the repository root:

    python platform/g10_report.py docs/evidence/G10_2026-09-24
    (cd docs/evidence/G10_2026-09-24 && sha256sum -c SHA256SUMS)

The first rebuilds `g10-report.json` from the raw files and exits nonzero on any
failed check; the second pins every raw file. `commit` records `b528f07`;
`worktree-status` is empty — the run used committed code only.

## What ran

`bash platform/run_g10.sh MODEL_DIR PREPARED_DIR OUT_DIR` on Windows 11 with
Docker Desktop's Linux engine and the Compose stack (Mosquitto 2.0.22,
PostgreSQL 17.6, Grafana 12.1.1), migrated and role-provisioned. The event source
is the real G8 lab: the pinned KAN-19 RF (`model.joblib` `d30725a9…57de6b`,
`model.meta.json` `917504c1…f200ad`) scoring the IoT-23 8-1 slice
(`prepared.pcap` `fc4aa4b9…ac917ee`, `provenance.json` `f3336d1a…fbde12`), N=1 and a
6 s lease as `lab/container_g8_iot23_probe.sh` declares. Model and capture stay
outside Git.

    G8 lab (og-b netns, --network none)
      DevicePolicy → StateEnforcementController → NftEnforcer   (decision, kernel)
      GatewayEventBridge → Unix socket in a shared Docker volume
    host container (platform/g10_host.py)
      UnixSocketAdapter (SO_PEERCRED) → TelemetryHandoff → TelemetryPublisher → Mosquitto
    platform/consume.py → PostgreSQL events → Grafana datasource query

## Result

| Scenario | Decided | UDS | PUBACK | Rows | Grafana | Lost |
|---|---:|---:|---:|---:|---:|---:|
| `normal` | 2 | 2 | 2 | 2 | 2 | 0 |
| `duplicate` | 2 | 2 | 2 | 2 | 2 | 0 |
| `outage` | 2 | 2 | 2 (after drain) | 2 | 2 | 0 |

All 69 checks in `g10-report.json` pass. In every scenario:

- **Decision ↔ application.** `NORMAL→QUARANTINED` is paired with kernel `APPLIED`
  and active readback; `QUARANTINED→NORMAL` with `ALREADY_RELEASED` or `RELEASED`
  and inactive readback. Each receipt follows its decision by about 0.1 ms on the
  lab's monotonic clock. During the block, the independent TCP and UDP sinks
  received 0 packets; kernel capture drops 0.
- **Decision ↔ telemetry ↔ dashboard.** Each committed row carries the gateway's
  six StateEvent fields exactly, under the event_id the host acknowledged, and
  Grafana's datasource returns the same event_ids in sequence order. The host
  adapter saw the lab's process as a `VERIFIED` peer.
- **Duplicate:** one acknowledged envelope was published again byte for byte; the
  broker acknowledged it, the consumer counted `redelivered: 1`, and no row was added.
- **Outage:** Mosquitto was stopped before the G8 run; the host spooled both events
  (`published: 0, spooled: 2`). After the broker returned, a new host process
  drained both under their original event_ids; the spool ended empty with no
  recorded loss. The consumer's persistent session received them on reconnect.

`ingest_minus_event_wall_seconds` in the report is the consumer's commit time minus
the gateway's event timestamp — two unaligned wall clocks, not a latency. It is
about 0.15–0.25 s when the broker is up and about 30 s in the outage scenario,
which is the time the broker was down.

## Limits

- **Pairing basis.** Decision, receipt and row are joined by order and exact field
  equality within one run. The 0.1.0 schema has no shared durable
  decision/application key; the report names this rather than inventing one.
- **Scale.** Two events per scenario — what one N=1 quarantine episode produces on
  this slice. The burst behaviour of the gateway→host socket is covered by the
  KAN-43 sealed runs (`docs/evidence/KAN43_2026-09-23/`), not here.
- **Host.** One Windows machine with Docker Desktop, not the Pi, and not a
  deployment: the lab and the host share one kernel through a volume-mounted
  socket.
- **Consumer logs** were written by Windows Python with CRLF and are committed
  with LF; their content is unchanged. Every other file is byte-for-byte as the run
  wrote it.
- **Earlier attempts** are kept outside Git and are not selected from:
  a development run of the same three scenarios on uncommitted runner code
  (passed; not evidence, the tree was dirty), one aborted at copying the G8 output
  (a path bug in the script, fixed before commit), and one that stopped before
  publishing anything because the Compose stack was down.
- This is the owner's run; independent review is still required.
