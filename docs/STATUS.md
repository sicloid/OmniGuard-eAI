# Development status — 2026-09-10

## Evidence and scope

- Read seven supplied V2 documents and the latest three turns of
  `ChatGPT Plus Tanıtımı`; self-hosted revision supersedes older Huawei cloud plans.
- Cloned `sicloid/OmniGuard-eAI`: repository was empty. Verified collaborators
  sicloid and Gabi8347. No pre-existing contracts or source code to preserve.
- Jira connector is reachable. `text ~ "OmniGuard"` and `project = KAN` returned
  no visible issues; this is not proof that no issues exist elsewhere. No issue
  IDs, completed tasks, assignments or workflow transitions have been invented.
- Project discovery subsequently confirmed `KAN` is named `OMNIGUARD eAI`, with
  `totalIssueCount: 0` reported by Jira. The supplied backlog is currently a plan,
  not populated Jira cards in this connected project.
- Docker CLI exists, but Docker Desktop Linux engine was unavailable during setup.
- User confirmed: Sukru = Lead/R2, Onur = R1/ML, Gabriel = R3/platform and telemetry.

## This branch

`feat/foundation-contracts`: draft contracts, deterministic stubs, safe local tests,
CI definition, ownership fallback, original planning documents and developer setup.
The full Jira backlog was populated and assigned at the user's request; see
JIRA_PLAN.md. The subsequent R2 week-one work and existing foundation are now
published for review in [draft PR #1](https://github.com/sicloid/OmniGuard-eAI/pull/1).
Main is an empty review base; no application code has been merged.

## Remaining sequence

1. G1/G2: team contract review, role assignment, complete environment lock,
   model artifact compatibility implementation, feature catalog, dataset audit,
   Linux lab isolation, platform Compose smoke test.
2. G3–G5: same pure extractor for offline/live inputs, adapters, capture-aware
   split, RF baseline, telemetry consumer, initial dashboards and measurements.
3. G6–G8: R2 state machine/enforcement, conntrack regression, replay/leakage;
   prove sink stop and release restore with the real model and no telemetry dependency.
4. G10: real StateEvent → UDS → MQTT → PostgreSQL → Grafana.
5. G11–G15: validation-only threshold experiments, N/FPR/leakage measurements,
   separate ARM64 validation, results freeze and reproducible laptop fallback demo.

Acceptance still pending: G1 approval, model artifact compatibility, platform
smoke, G5, G8, G10, G13 and G15. Synthetic fixtures do not satisfy these gates.

## Local verification

Editable package install succeeded in a fresh Python 3.14.7 virtual environment.
Nine unit tests, Ruff lint/format and deterministic smoke passed on Windows.
GitHub Actions workflow is defined, but no hosted CI run or Linux execution is
claimed. ML and platform dependencies remain outside this foundation validation.

The paragraph above records the initial foundation snapshot. For the subsequent
PCAP adapter, Linux lab scripts and hosted CI evidence, see [WEEK_ONE_R2.md](WEEK_ONE_R2.md).
