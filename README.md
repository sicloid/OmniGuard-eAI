# OmniGuard eAI

Payload-independent IoT malware detection and reversible outbound containment
research prototype. Local Random Forest inference, isolated Linux namespaces,
nftables/conntrack, and self-hosted Mosquitto → PostgreSQL → Grafana telemetry.
No managed cloud service is required. Raspberry Pi 5 is a later shared integration
and ARM64 validation target; laptop development remains possible.

## Current implementation

Initial G1 foundation: five validated draft runtime contracts, three deterministic
stubs, unit tests, Windows/Linux CI definition and versioned planning documents.
Real capture, feature extraction, model training, containment and telemetry services
are not implemented yet. G5/G8/G10 are **not passed**.

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

Linux (same reference interpreter):

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
| R1 | core/features.py, model/, dataset/sample pack | Onur; GitHub handle pending |
| R3 | platform/, telemetry/, measure/ | Gabriel (@Gabi8347) |

Gabriel's GitHub access (@Gabi8347) was verified. Onur is joining later. AI work
supports human module owners; every change still needs owner review.

Next: review [SCHEMA.md](SCHEMA.md) and [ADR-0001](docs/adr/0001-foundation.md),
then R1 feature catalog/data audit, R2 isolated A→B→C Linux lab, R3 pinned platform
dependencies and Compose smoke test. Full roadmap: [development status](docs/STATUS.md).

## Engineering rules

Use short-lived feature branches and a reviewed PR. Main must stay runnable.
Contract changes require ADR and team approval. Keep datasets, credentials and
model binaries out of Git. Lab traffic stays isolated; Tailscale is management
only; enforcement belongs inside the gateway namespace and never flushes host rules.
Privileged integration tests run only on the dedicated Linux lab host.

The `platform/` directory will contain deployment configuration, not a Python
package: do not add `platform/__init__.py` and shadow the standard library.
