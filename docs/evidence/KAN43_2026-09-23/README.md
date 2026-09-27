# KAN-43 sealed telemetry-volume runs — 23 September 2026

Run `python docs/evidence/KAN43_2026-09-23/verify.py` from the repository root. It
checks every file here against `SHA256SUMS`, re-derives each figure in
`docs/KAN43_TELEMETRY_VOLUME.md` from the frozen manifests, reconciles every boundary
against the next, and joins the consumer's committed rows to the publisher's count.

## What ran

`lab/kan43_sealed_run.py`, in `lab/Dockerfile.kan43` (Python 3.14.7, the project's
hash-locked `requirements.lock`) on the Compose `omniguard_telemetry` network, against
the Compose Mosquitto and PostgreSQL. The `ExperimentManifest` (`/2`) was frozen before
the first byte moved; its sealed `config` holds the schedule, the policy block and the
SHA-256 of all fifteen files on the measured path.

    DevicePolicy -> GatewayEventBridge -> UnixSocketTransport -> socket
      -> CountingAdapter -> TelemetryHandoff -> TelemetryPublisher
      -> CountingTransport(PahoTransport) -> lab/mqtt_wire_counter.py -> Mosquitto
      -> platform/consume.py (host, own persistent client id) -> PostgreSQL

Detections are scripted — 20 quarantine cycles, seed 43, the Lead's frozen N=2 and
300 s lease — because byte volume depends on the StateEvents the real policy emits, not
on how a model scored a window. The whole schedule is handed to the bridge at once, so
the run is a burst: its bytes-per-second are the rate of this run, not a deployment
load.

## The two runs

| | `run1-listen1` | `run2-listen64` |
|---|---:|---:|
| run id | `kan43-1c4e0a5e…` | `kan43-55eb885e…` |
| code | `telemetry/uds.py` at `listen(1)` | current checkout |
| events produced by the policy | 60 | 60 |
| delivered over the UDS | 47 | 60 |
| lost at the UDS, counted by the bridge | **13** (`EAGAIN`) | 0 |
| PUBACK | 47 | 60 |
| committed rows | 47 | 60 |

**Run 1 found a real loss.** The host adapter listened with a backlog of 1 while the
gateway opens one connection per event; on Linux a `connect()` to a full AF_UNIX
backlog with a timeout set fails immediately with `EAGAIN` instead of waiting. Thirteen
of sixty events never reached the host. The loss was counted where it happened —
bridge `failures=13`, UDS residue −2,162 bytes — and nothing downstream claimed them.
The fix (`LISTEN_BACKLOG = 64`) and a regression test that fails at a backlog of 1 are
in the same PR; run 2 is the same sealed schedule on the fixed code. Run 1 is kept
rather than replaced: it is the card's first sealed run, and discarding it for a
cleaner one would be selecting on the result.

A burst larger than the backlog still loses events at this boundary, counted the same
way; the gateway bridge does not retry.

## What is not in these files

- **Run 1's consumer was restarted twice.** The first consumer was started in the
  background with block-buffered output, so the wait for its readiness line only
  returned when it exited at its 240 s timeout — the run was published while it was
  offline, and its persistent session queued the messages. `consumer-2.log` stored 47
  and hit its 60 s timeout; `consumer-3.log` found nothing left. The broker session was
  then read once without acknowledging: `session_present=True`, zero messages held.
  All 47 events that reached the host are in `db-events.jsonl`. Run 2's consumer was
  started unbuffered and was online before publishing began.
- **Consumer logs** were written by Windows Python with CRLF and are committed with LF;
  their content is unchanged. The manifests and row exports were produced with LF.
- **Two wiring checks** of two cycles each were made before run 1 and discarded: the
  first failed inside the schedule generator (non-consecutive windows never reached N),
  the second completed. Neither is a result and neither was selected from.
- **Not counted:** IP/TCP headers, retransmissions, TLS. `mqtt_publish_packet` is
  derived; the wire figure beside it is counted. R1 provenance is `not_supplied` —
  nothing reads a dataset or a model. This is one Docker Desktop host, not a Pi.
