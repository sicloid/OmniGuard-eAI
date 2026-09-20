# KAN-49 — real core gate runbook

The gate is **not passed** by unit tests, the stub enforcer probe, or the
synthetic RF wiring smoke. The exact KAN-19 `model.joblib` was supplied in
`omniguard-kan19-model.zip` outside Git and independently verified against the
frozen model/metadata SHA-256 pins. The audited IoT-23 8-1 parent capture is
also outside Git. The real-model integration and process-kill runs below cover
the remaining local kernel/sink requirements; independent team review remains
the Jira closing condition. These are integration tests on a **development
validation capture**, not unseen-data efficacy or deployment FPR evidence.

## Real-model IoT-23 Linux runs (19–20 September)

Use the locked ML virtual environment from [REPRODUCE.md](REPRODUCE.md) for the
preparation step: `lab.prepare_iot23_g8` imports `dpkt`, which is not guaranteed
to be installed in the system Python. Keep the original model and PCAP outside
Git. First check all model files against
the archive's `SHA256SUMS` and the project pins. Prepare the original audited 8-1
PCAP using the fixed selector; the script checks parent SHA-256
`80dcc260...` before writing anything. The resulting provenance lists the exact
parent packet indices, exclusions, 2018 capture timestamps, address rewrites
and prepared PCAP hash. The three selected packets are TCP SYNs without payload.
Both runners independently require prepared-PCAP SHA-256
`fc4aa4b9bbdc89a7845fa0fb8b0fd19ce13f71c82a25346e390ad7863ac917ee`
and provenance SHA-256
`f3336d1ade84a869db71c37573d5bc6b30898388e8a763997d530de2f8fbde12`.
No packet is sent to a public route: replay runs only in network-none Docker's
owned A→B→C namespaces.

```sh
.venv/bin/python -m lab.prepare_iot23_g8 \
  --parent ~/omniguard-data/iot23/CTU-IoT-Malware-Capture-8-1/2018-07-31-15-15-09-192.168.100.113.pcap \
  --out ~/omniguard-data/g8-prepared-8-1
bash lab/run_g8_iot23_docker.sh \
  ~/omniguard-data/omniguard-kan19-model ~/omniguard-data/g8-prepared-8-1
bash lab/run_g8_iot23_kill_docker.sh \
  ~/omniguard-data/omniguard-kan19-model ~/omniguard-data/g8-prepared-8-1
```

The orderly run loaded the **exact** frozen model, captured the replayed real
packets through AF_PACKET, extracted `features-1`, recorded an anomalous RF
decision and nftables `APPLIED`/release receipts, and observed independent
established TCP and UDP probe sinks. In the indexed 20 September run both sinks
had 20 pre-block deliveries and **zero** in the validated block interval,
despite 24 source attempts per protocol. Stable post-release deliveries were
292 TCP and 333 UDP. The og-a local loopback service answered 111 times during
the gateway block; capture reported zero kernel drops. The separate
SIGKILL run killed the Python controller after `APPLIED`: readback stayed active
after death, was active two seconds later, then cleared by the kernel timeout.
Both sinks had zero deliveries despite 12 source attempts per protocol in the
validated block interval, then 74 stable deliveries each after expiry; the
local service answered 35 times while blocked. Both runners
compared parent rules/routes before and after namespace teardown. Ignored raw
evidence is under `artifacts/g8-iot23.*` and `artifacts/g8-iot23-kill.*`.

The selected 8-1 capture belongs to the model's **validation**, so none of
these observations is a new accuracy estimate. The selector rewrites every
selected destination to the isolated sink, changing destination-diversity
features. It records that transformation rather than claiming feature parity
with the original pack. The independent TCP/UDP sink and local-control traffic
are generated lab probes, separate from the three replayed IoT-23 SYNs. `t0`
means first replay submission, not an externally audited attack start. The
G8 integration result is therefore bounded to this declared 0.1.0 lab profile;
KAN-52 and any external-validity claims still need separate evidence.

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

### 19 September reconstruction check

The development pack supplied as `omniguard-samplepack-v2.zip` contains the
byte-pinned `windows.jsonl` plus the original v1 manifest. All three archive
members passed its `SHA256SUMS`. Running `model.policy_run` with that v1 manifest,
the unchanged policy spec and Python 3.14.7 / scikit-learn 1.8.0 / NumPy 2.5.3
reproduced seed 1's validation threshold (0.9798815486832), recall and FPR,
but produced `model.joblib` SHA-256
`4b6b87dba1a48d450689bfb0ec1e6c2b4a71068150489604380c2759420d1591`
instead of the frozen `d30725a9...` pin. The regenerated threshold policy also
counts 146 rather than 143 candidates. Equal headline metrics do not make these
artifacts byte-identical; the regenerated model is **not** the frozen G8 model.
The original binary was subsequently supplied in `omniguard-kan19-model.zip`
and independently passed the frozen pin. Keep using those exact original bytes.

The independently downloaded original IoT-23 4-1 and 8-1 PCAPs matched the
parent hashes in `data/DATASET_AUDIT.md`. The 8-1 original was then prepared by
the explicit fixed selector above; neither the raw PCAP nor prepared PCAP is in Git.

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
  --n 1 --lease-seconds 6 --seconds 24
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
clock. The source-attempt logs must show packets attempted *during* the blocked
interval, while independent sink logs show zero delivery there; a silent sink
without source attempts proves nothing. Report both the first delivery after
the verified blocked interval (signed relative to release/readback, because
kernel TTL may restore traffic before controller readback) and the first delivery
strictly after release. Count stable post-release deliveries only after a 300 ms
margin, but do not apply that margin to the first-delivery latency. Also report
the reorder wrapper's inversion/heap counters.
These are integration observations, not model accuracy or external FPR.

The canonical 20 September run is indexed in
[`G8_2026-09-20.json`](evidence/G8_2026-09-20.json), including exact raw-log
hashes and validator outputs. In the orderly run, TCP and UDP each attempted
24 sends while blocked; both sinks recorded zero deliveries. Their first actual
deliveries strictly after controller release readback were 2.804225 s (TCP)
and 0.041042 s (UDP); UDP also resumed 0.009201 s *before* that readback as
the kernel lease expired. Stable post-release deliveries after the declared
300 ms margin were 292 TCP and 333 UDP. Kernel drops were 0, local service
succeeded 111 times, and the reorder wrapper reported 0 inversions with a
high-water mark of 4. In the SIGKILL run, each source attempted 12 sends while
the kernel element remained active after process death; both sinks recorded
zero deliveries and then 74 stable deliveries each after kernel TTL expiry.
The first deliveries strictly after the inactive readback were 0.019167 s
(TCP) and 0.022553 s (UDP); both protocols also delivered traffic before that
later readback, once the kernel TTL had expired. These
numbers describe one N=1, six-second-lease development validation run, not a
distribution or Raspberry Pi measurement. The synthetic wiring smoke separately
exercised 5 timestamp inversions (maximum 8.82 microseconds) and passed.

## Gate decision

Mark KAN-49 Done only when a repeatable run with the **real pinned model** shows
traffic → shared extractor → RF → state → nftables readback → independent
TCP **and** UDP sink stop → release restore, with telemetry/cloud off, no packet
loss, and local service behavior recorded. Repeat a process-kill run and prove
kernel TTL restores traffic without the controller. Report a non-detection or
false quarantine as a result, not as a passed gate. Keep KAN-35/KAN-60 and the
final release blocked until this evidence exists and another owner reviews it.
The two real-model Docker runs above provide the technical evidence for this
specific profile. KAN-49 remains **İncelemede** until that independent review
checks the code, provenance, run summaries and scoped claim.
The [clean-checkout evidence index](evidence/G8_2026-09-20.json) pins the
corresponding raw log hashes and validator outputs. Its small, payload-free
[log bundle](evidence/G8_2026-09-20_raw/) lets a reviewer rerun both validators
without committing the model or capture bytes.
