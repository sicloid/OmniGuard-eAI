# KAN-49 — real core gate runbook

The gate is **not passed** by unit tests, the stub enforcer probe, or the
synthetic RF wiring smoke. It needs the independently pinned KAN-19 IoT-23
`model.joblib`, an audited/prepared traffic capture, and independent sink
stop/restore evidence. Neither file is committed to Git.

## Repeatable wiring smoke available now

Run on an amd64 Linux Docker host:

```sh
bash lab/run_g8_synthetic_docker.sh
```

The script builds the hash-locked Python 3.14.7 image, creates only the owned
`og-a`/`og-b`/`og-c` namespaces inside a network-none disposable container,
trains an explicitly named `SYNTHETIC-WIRING-NOT-G8` forest, and starts independent
TCP and UDP sink probes. It then runs the real AF_PACKET capture, shared
`extract_features`, pinned-artifact loader, RF, `DevicePolicy`, and `NftEnforcer`.
The validator checks that both sinks receive before quarantine, receive nothing
after in-flight drain and before kernel expiry, and receive again afterward. It
also requires no packet-socket drops and a clear kernel readback. Ignored
`artifacts/g8-synthetic.*` contains `core.jsonl`, sink logs, pin hashes, and the
validation summary. The model is synthetic, so this is wiring evidence only.

Linux AF_PACKET can deliver closely spaced frames out of kernel timestamp order.
The G8 path uses `BoundedReorderCapture` with original timestamps, a 2 ms event-time
reorder bound and a 256-packet heap. A packet behind an already emitted timestamp
or idle watermark, heap overflow, socket loss, or clock drift invalidates the
observation; none becomes a benign classification. `LiveCapture` keeps strict
ordering by default for other consumers.

## Real artifact and evidence requirements

The frozen deployment pins for `model/frozen/kan19-seed1/model.meta.json` are:

```text
model.joblib SHA-256:    d30725a9e913a5f1d4c652796e7a6a15dcd00cc482ef162f5a387fa18b57de6b
model.meta.json SHA-256: 917504c156951eee6d4438409c4529ad309d90b67a6e53a0ed2a5040f0f200ad
```

The two hashes must come from trusted deployment configuration, not from files
being loaded. The exact `model.joblib` bytes and `model.meta.json` must be in one
read-only artifact directory. `load_pinned_rf_detector` checks both hashes, the
frozen 0.1.0 schema, `features-1` order and Python/sklearn/numpy versions before
joblib deserialization. Never substitute a newly trained model under these pins.

For a manual isolated run, build `lab/Dockerfile.g8` and create a network-none
container with `NET_ADMIN`, `NET_RAW`, `SYS_ADMIN`, the same two security options
as `lab/run_g8_synthetic_docker.sh`, and **read-only** mounts for the trusted
artifact and audited prepared PCAP/provenance. Do not mount the Docker socket,
use the host network, add default routes, or replay on a public interface. Inside
the container, `lab/setup_netns.sh` creates the owned topology. Start an
independent TCP and UDP sink in `og-c`, benign local service probes in `og-a`,
then invoke the core in `og-b`:

```sh
ip netns exec og-b python -m lab.g8_core \
  --artifact-dir /opt/g8-model \
  --model-sha256 d30725a9e913a5f1d4c652796e7a6a15dcd00cc482ef162f5a387fa18b57de6b \
  --metadata-sha256 917504c156951eee6d4438409c4529ad309d90b67a6e53a0ed2a5040f0f200ad \
  --n 2 --lease-seconds 10 --seconds 40
```

The core emits JSON lines with `mono_ns`, detection, StateEvent and kernel
readback. It reconciles a lingering block at startup and releases an active
episode on orderly shutdown. A forced kill cannot run `finally`; the nftables
per-element timeout must then release the device independently. Capture
failure, artifact mismatch, zero complete windows, and unverified namespace
identity fail the run.

Prepare/replay the audited dataset as described in [lab/REPLAY.md](../lab/REPLAY.md)
and [ADR-0004](adr/0004-dataset-source.md). The PCAP must pass the existing
fixed-lab provenance/IP/MTU checks; do not relabel a synthetic probe as IoT-23.
Record the parent capture hash, preparation commands, labels/exclusions, replay
manifest/t0, frozen model hashes, chosen N/lease, core log and independent
TCP/UDP sink logs in one run directory. Correlate by same-container monotonic
clock; a send return or a StateEvent alone is not a sink-stop observation.

## Gate decision

Mark KAN-49 Done only when a repeatable run with the **real pinned model** shows
traffic → shared extractor → RF → state → nftables readback → independent
TCP **and** UDP sink stop → release restore, with telemetry/cloud off, no packet
loss, and local service behavior recorded. Repeat a process-kill run and prove
kernel TTL restores traffic without the controller. Report a non-detection or
false quarantine as a result, not as a passed gate. Keep KAN-35/KAN-60 and the
final release blocked until this evidence exists and another owner reviews it.
