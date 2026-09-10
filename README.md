# OmniGuard eAI

Payload-independent IoT malware detection and reversible outbound containment
research prototype. Local Random Forest inference, isolated Linux namespaces,
nftables/conntrack, and self-hosted Mosquitto → PostgreSQL → Grafana telemetry.
No managed cloud service is required. Raspberry Pi 5 is a later shared integration
and ARM64 validation target; laptop development remains possible.

## Current implementation

G1 contracts are team-approved and frozen as `0.1.0`; PR #1 is merged.
The PCAP adapter, deterministic stubs and 21 unit tests pass on Linux.
The isolated A→B→C lab passes real UDP quarantine/conntrack/release checks.
Mosquitto, PostgreSQL and Grafana run in Compose with health/authentication smoke
tests. Live capture, feature extraction, model training, runtime state/enforcement,
telemetry consumer and dashboards remain pending. G5/G8/G10 are **not passed**.

## Run locally

Reference interpreter: Python 3.14.7. Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\python.exe -m stubs
```

Linux (Python 3.14.x; CachyOS verified with 3.14.6, CI reference 3.14.7):

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
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

Next: R1 feature catalog/data audit/artifact compatibility; R2 live capture and
windowing; R3 telemetry adapter, database schema/consumer and dashboards.
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
