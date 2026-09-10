# CLAUDE.md

Working context for AI coding agents in this repository. Read this before editing.
`AI_SYSTEM_PROMPT.md` states the same intent for other assistants; keep both in sync.

## What this project is

Payload-independent IoT malware detection with reversible outbound containment.
Local Random Forest inference, isolated Linux network namespaces with
nftables/conntrack, and a self-hosted Mosquitto → PostgreSQL → Grafana telemetry
path. No managed cloud service is permitted anywhere in the design.

## Read before editing

1. `README.md` — current implementation state and run commands
2. `SCHEMA.md` — the five runtime contracts, frozen at `0.1.0`
3. `docs/STATUS.md` — what is done, what is pending, which gates are unpassed
4. `docs/adr/` — the ADR covering the area being touched
5. The `README.md` of the module directory being edited

## Ownership

`.github/CODEOWNERS` is authoritative. Summary:

| Role | Person | Directories |
|---|---|---|
| Lead / R2 | Şükrü (@sicloid) | `sources/`, `gateway/`, `lab/` |
| R1 / ML | Onur (@pondilungs) | `core/features.py`, `model/`, `data/` |
| R3 / platform | Gabriel (@Gabi8347) | `platform/`, `telemetry/`, `measure/` |

`core/schema.py`, `SCHEMA.md` and `docs/adr/` are co-owned by all three.

Do not edit another role's directory without stating it in the PR description.
Passing tests never substitute for owner review.

## Hard rules

- Short-lived feature branch plus a reviewed PR. **Never commit or push to `main`.**
- Branch from up-to-date `main`. Naming: `feat/KAN-<id>-<slug>`, `fix/...`, `docs/...`.
- `main` must stay runnable.
- Contract changes (`core/schema.py`, `SCHEMA.md`) require an ADR and team approval.
- Never commit datasets, credentials, `platform/.secrets/`, `*.pcap` or model binaries.
- Lab traffic stays isolated. Never flush host nftables rules. Enforcement belongs
  inside the gateway namespace. Tailscale is management access only.
- Privileged integration tests run only on the dedicated Linux lab host, never on
  shared CI runners.
- Report measured results honestly. Stub or synthetic output is never evidence.
  G5, G8 and G10 are **not passed**; do not write text implying otherwise.
- Fill in every section of `.github/pull_request_template.md`.

## Gotchas

- **Never create `platform/__init__.py`.** It shadows the standard-library
  `platform` module. That directory is deployment configuration, not a package.
- `SCHEMA_VERSION` is `0.1.0`. The old `0.1.0-draft` identifier is rejected on the
  wire; regenerate fixtures rather than loosening the check.
- Event timestamps are UTC Unix seconds. Runtime performance durations use a
  **separate monotonic clock** — never subtract values from different clock domains.
- `TelemetryPayload` carries no raw packet, IP, MAC or payload bytes.
- `event_id` must survive retries. The consumer deduplicates and rejects unknown
  `schema_version` values.
- Feature windows are half-open `[window_start, window_end)`, 5 seconds, epoch-aligned.
- `device_id` is an internal stable mapping, never an ML feature.
- Ports are null when unavailable (ICMP, noninitial fragments). Never guess one.
- `stub-0.1` features are synthetic integration data, not the production catalogue.

## Jira workflow

Project `KAN` (OMNIGUARD eAI) on `sicloid.atlassian.net`. One work-in-progress
card per person. Flow: open PR → card moves to **İncelemede** → acceptance
criteria and tests verified plus owner review → **Tamamlandı**. Reference the card
id in the branch name, commit message and PR description.

## Commands

Reference interpreter: Python 3.14.7.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
```

Platform stack, from the repository root (Docker required):

```sh
python3 platform/init_secrets.py
docker compose -f platform/compose.yaml up -d --wait
python3 platform/smoke.py
```

`platform/smoke.py` proves the services are up and authenticated. It is not the
G10 event-chain gate and must never be cited as one.
