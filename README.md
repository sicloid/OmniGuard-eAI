# OmniGuard eAI

Payload-independent IoT malware detection and reversible outbound containment
research prototype. Local Random Forest inference, isolated Linux namespaces,
nftables/conntrack, and self-hosted Mosquitto → PostgreSQL → Grafana telemetry.
No managed cloud service is required. Raspberry Pi 5 is a later shared integration
and ARM64 validation target; laptop development remains possible.

## Architecture and contributor context

Read the [V3 architecture](ARCHITECTURE.md), [2026 review](docs/architecture/REVIEW_2026.md),
[execution map](docs/architecture/EXECUTION_V3.md), and [AI context](AI_SYSTEM_PROMPT.md).
V3 separates observation health, policy decisions, application evidence and bounded
release. These additions are proposals; the approved runtime contracts remain 0.1.0.
Original V2 planning files are retained as historical sources.

## Current implementation

G1 contracts are team-approved and frozen as `0.1.0`. The repository includes
the real IoT-23 data audit, pinned RF artifact loader, live capture/window/policy pipeline,
runtime nftables enforcer, UDS/MQTT/DB adapters and Grafana dashboard. The
real-model G8 orderly and process-kill runs passed their bounded local
sink/kernel checks on Linux; Gabriel independently approved the exact head,
PR #41 merged, and KAN-49 is complete. A separate local integration
run on 20 September carried two actual G8 StateEvents through peer-verified
UDS, broker PUBACK, PostgreSQL and Grafana. Duplicate replay did not create a
second row, and a broker outage spooled two real events which were delivered
with unchanged IDs after restart. This run used a **local composite commit**
`ce5bdbf` of PR #41 and main, not a merged/reviewed G10 release. The frozen
model binary and capture remain outside Git. KAN-50 still needs
decision-to-application correlation, an end-to-end completeness/loss report,
and owner acceptance. G10 is not declared a closed gate.
See the [G8 runbook](docs/G8_RUNBOOK.md), [reproduction map](docs/REPRODUCE.md),
and [current status](docs/STATUS.md) for scope and remaining work.

## Run locally

Start with the [clean-checkout reproduction map](docs/REPRODUCE.md) for data,
training, lab, platform, G8/G10, Pi and laptop fallback. The
[demo runbook](docs/DEMO_RUNBOOK.md) gives the presentation order, failure rules
and cleanup steps; neither document turns a pending gate into a pass.

Reference interpreter: Python 3.14.7, pinned in `.python-version`. Dependencies
are hash-locked in [requirements.lock](requirements.lock). ML development uses
[requirements-ml.lock](requirements-ml.lock), which includes the base lock; details and the
regeneration procedure are in [environment notes](docs/ENVIRONMENT.md).
Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock
.\.venv\Scripts\python.exe -m pip install -e . --no-deps --no-build-isolation
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\python.exe -m stubs
```

For ML work replace `requirements.lock` with `requirements-ml.lock` in the install
command. CI installs the ML lock so RF tests cannot be skipped due to missing ML packages.

Linux / macOS (Python 3.14.7 or a newer 3.14.x; CI reference 3.14.7):

Use a project interpreter on CachyOS: with `uv` installed, run `uv python install 3.14.7`
and `uv venv --python 3.14.7 --seed .venv`. Activate `.venv` for project commands;
the system `/usr/bin/python` is managed by the OS and need not change.
The `python3` command below must otherwise already resolve to the required version.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.lock
.venv/bin/python -m pip install -e . --no-deps --no-build-isolation
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python -m stubs
```

The smoke command prints fixed model scores and independently scripted telemetry
events. It requires no root, Docker, dataset, network or credentials. It is not an
end-to-end detection pipeline. Do not cite its output as research measurements.

## Ownership and next work

| Role | Scope | Confirmed person |
|---|---|---|
| Lead + R2 | contracts coordination, sources/, gateway/, lab/ | Şükrü (@sicloid); user states security ownership |
| R1 | core/features.py, model/, dataset/sample pack | Onur (@pondilungs) |
| R3 | platform/, telemetry/, measure/ | Gabriel (@Gabi8347) |

All three collaborators were verified on 2026-09-10. AI work
supports human module owners; every change still needs owner review.

Next: G10 correlation/completeness evidence,
Pi ARM64 measurements, measurement freeze, team rehearsal and final release.
Full roadmap: [development status](docs/STATUS.md).

Docker lab and platform (from the repository root):

```sh
bash lab/run_docker.sh
python3 platform/init_secrets.py
docker compose -f platform/compose.yaml up -d --wait
python3 platform/smoke.py
```

Grafana: [localhost:3000](http://127.0.0.1:3000), user `admin`; password in
`platform/.secrets/grafana_password`. Access/shutdown: [platform runbook](platform/README.md).
Network-test logs: `artifacts/linux-lab.*`; [Linux evidence](docs/LINUX_VALIDATION.md).
For the real core gate, use the [G8 runbook](docs/G8_RUNBOOK.md); the synthetic
TCP/UDP RF wiring smoke is `bash lab/run_g8_synthetic_docker.sh` and is not G8 proof.

## Engineering rules

Use short-lived feature branches and a reviewed PR. Main must stay runnable.
Contract changes require ADR and team approval. Keep datasets, credentials and
model binaries out of Git. Lab traffic stays isolated; Tailscale is management
only; enforcement belongs inside the gateway namespace and never flushes host rules.
Privileged integration tests run only on the dedicated Linux lab host.

The `platform/` directory will contain deployment configuration, not a Python
package: do not add `platform/__init__.py` and shadow the standard library.

R2 commands and limitations: [PCAP adapter](sources/README.md),
[Linux lab](lab/README.md). Team review checklist: [G1 review](docs/G1_REVIEW.md).
