# Reproduce the OmniGuard prototype (KAN-55)

This is the entry point for a clean checkout. Each command below has a narrower
meaning than a passed G8/G10 gate. Record the Git commit and actual environment
with every run; never substitute a synthetic fixture for a real-data result.

## 1. Checkout and locked environment

Use the repository's `.python-version` reference (3.14.7) and a fresh virtual
environment. On CachyOS, `uv python install 3.14.7` and
`uv venv --python 3.14.7 --seed .venv` avoid changing system Python. Then:

```sh
git rev-parse HEAD
.venv/bin/python --version
.venv/bin/python -m pip install --require-hashes -r requirements-ml.lock
.venv/bin/python -m pip install -e . --no-deps --no-build-isolation
.venv/bin/python -m pip check
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

The core-only install may use `requirements.lock`; model training and the real RF
path require `requirements-ml.lock`. See [the environment contract](ENVIRONMENT.md).
Test counts vary by commit and platform; skipped Linux-only tests on Windows do
not prove the Linux socket path.

## 2. Data, labels and split

The current development experiments use the audited IoT-23 captures listed in
[KAN-13's audit](../data/DATASET_AUDIT.md). The wider source policy in
[ADR-0004](adr/0004-dataset-source.md) is a separate decision; do not infer that
every CICIoT2023 capture is LOCAL from its description. Neither captures nor the
large sample pack are in Git. Verify source hashes against the audit, then run:

```sh
.venv/bin/python -m data.samplepack.iot23 \
  --captures ~/omniguard-data/iot23 \
  --out ~/omniguard-data/samplepack
sha256sum ~/omniguard-data/samplepack/windows.jsonl
```

The original KAN-18/19/21 pack has `windows_sha256`
`4b97fb954270a2727544724aa331d20354f9e10f6aa5d1bbbf62a5f3c40c6625`.
The later v2 pack records `window-label-1`; it does **not** rewrite the original
pin. Do not call a newly produced pack equivalent until its manifest, capture
set, transformations, label rule, exclusions and SHA-256 match. See
[sample-pack rules](../data/samplepack/README.md) and
[feature catalogue](../data/FEATURE_CATALOG.md).

## 3. Training and validation-only policy

Run only against the matching audited pack. Outputs live outside Git and each
runner refuses to overwrite a prior run directory. The test split is not used
for threshold selection; preserve failed/no-threshold results.

```sh
.venv/bin/python -m model.baseline_run \
  --pack ~/omniguard-data/samplepack/windows.jsonl \
  --out ~/omniguard-data/runs/kan18 --seeds 1,2,3 --bootstrap 300
.venv/bin/python -m model.policy_run \
  --pack ~/omniguard-data/samplepack/windows.jsonl \
  --out ~/omniguard-data/runs/kan19
```

The full procedures and measured limits are [KAN-18](KAN18_BASELINE.md),
[KAN-19](KAN19_POLICY.md), [KAN-20](KAN20_ABLATION.md) and
[KAN-21](KAN21_HOLDOUT.md). The frozen KAN-19 model hash is
`d30725a9e913a5f1d4c652796e7a6a15dcd00cc482ef162f5a387fa18b57de6b`;
its metadata hash is
`917504c156951eee6d4438409c4529ad309d90b67a6e53a0ed2a5040f0f200ad`.
`model.joblib` stays outside Git. Its hash, not just matching metadata text,
must be verified before loading it.

## 4. Isolated Linux traffic lab

On the dedicated amd64 Linux Docker host, from the repository root:

```sh
bash lab/run_docker.sh
bash lab/run_live_docker.sh
bash lab/run_replay_docker.sh
```

These runners use disposable network-none containers. The A→B→C namespaces and
nftables table exist only inside them; they do not mount the host Docker socket
or advertise lab routes. The replay runner uses a benign prepared oracle; for
real input follow [the replay/provenance contract](../lab/REPLAY.md). Results are
retained in ignored `artifacts/`. The lab commands prove their own network,
capture and replay mechanics, not a real-model G8 gate.

## 5. Platform and telemetry

On Linux with Docker Compose, from the repository root:

```sh
python3 platform/init_secrets.py
docker compose -f platform/compose.yaml up -d --wait --wait-timeout 180
python3 platform/migrate.py
python3 platform/provision_roles.py
python3 platform/smoke.py
docker compose -f platform/compose.yaml ps
```

The initializer writes ignored credentials; never put them in Git or logs. The
consumer command and database semantics are in [the platform runbook](../platform/README.md).
KAN-41's provisioned Grafana dashboard is merged. `provision_roles.py` sets and
verifies separate consumer and read-only credentials after migration; without it
the datasource cannot authenticate. To populate the dashboard with clearly
labelled fabricated records, run one `platform/consume.py` process and then
`platform/seed_demo.py` as shown in [the platform runbook](../platform/README.md).
Service health, MQTT pub/sub and those fabricated records do not prove that a
real gateway StateEvent reached UDS→MQTT→PostgreSQL→Grafana. KAN-50 G10
acceptance remains separate.

## 6. G8 core gate

The real-core candidate is [PR #41](https://github.com/sicloid/OmniGuard-eAI/pull/41).
Its `bash lab/run_g8_synthetic_docker.sh` uses a clearly labelled **synthetic**
Random Forest and proves TCP/UDP wiring, not G8. The real gate requires the exact
frozen `model.joblib`, an audited/prepared capture, replay/t0, independent sink
stop and release restore for TCP/UDP, local service control, and a process-kill/
kernel-TTL run with telemetry off. Until those artifacts and peer review exist,
report `G8: not passed`. KAN-35 laptop demo depends on this gate.

## 7. G10 and results freeze

KAN-50 requires one **real** gateway StateEvent through UDS, MQTT, PostgreSQL and
Grafana, including duplicate/outage/recovery and completeness evidence. Compose
smoke or a stub event is insufficient. KAN-54 freezes the exact commit, artifact,
environment, feature/threshold/N/lease policy, split and run hashes, plus failed
runs and clock/hardware mapping. KAN-52's measured FPR/containment plot is still
a prerequisite. Until the corresponding Jira acceptance evidence exists, report
`G10/G13: not passed/frozen`.

## 8. Pi path and laptop fallback

Pi 5/ARM64 results require runs on the actual Pi with OS, Python, package/image
digests, load, temperature/throttling, route and time mapping recorded. Tailscale
is private management only; it must not advertise the isolated lab subnets.
macOS ARM64 or an aarch64 wheel existing does not validate the Pi. When the Pi is
unavailable, use the laptop-only path after G8 and label results `Linux x86_64`;
never copy a laptop number into the Pi column. KAN-44/46/53 remain open until
hardware evidence is recorded.

For the live demonstration order and cleanup, see [the demo runbook](DEMO_RUNBOOK.md).
