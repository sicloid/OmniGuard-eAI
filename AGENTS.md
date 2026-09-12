# OmniGuard repository instructions

## Start from verified context

Read `AI_SYSTEM_PROMPT.md`, `docs/STATUS.md`, `ARCHITECTURE.md`, `SCHEMA.md`, and
relevant accepted ADRs. Read the owning module README and actual code before edits.
The current runtime wire version is 0.1.0. `docs/adr/0001-foundation.md` records
V2 team approval; ADR-0002 and the V3 runtime additions are proposals, not implemented
or automatically approved by that earlier decision.

User instructions define the task. For repository facts, code/tests/run evidence
establish what works; SCHEMA and accepted ADRs define approved contracts. V3 is
the current design review for future work. `docs/planning/*_V2.md` is historical
source material, not current completion evidence or a mandate to recreate files.
Do not repeat outdated onboarding, Windows-blocker or cloud-only assumptions.

## Ownership and scope

- Onur `@pondilungs`: `core/features.py`, `model/`, data audit/sample generation.
- Şükrü `@sicloid`: lead, `sources/`, `gateway/`, `lab/`, integration.
- Gabriel `@Gabi8347`: `platform/`, `telemetry/`, `measure/`.
- Shared contracts/ADRs: coordinate all affected owners; see `.github/CODEOWNERS`.

Use a focused feature branch and a reviewable PR. A related follow-up can use a
stacked PR when its predecessor is not merged; disclose the base dependency.
Do authorized preparatory work and routine reversible fixes autonomously. Record
new contract/policy proposals in an ADR and preserve the existing runtime until
required team review is resolved; do not invent approvals or ask again for approvals
already explicitly provided. Do not silently change Jira deadlines/assignees.

Fill every section of `.github/pull_request_template.md`. Include the Jira key in
the branch, commit and PR. PR opened → İncelemede; acceptance evidence and owner
review complete → Tamamlandı. Code merged is not proof that a data or runtime
integration gate passed. Record user-reported approval separately from GitHub reviews.

## Architecture invariants

- Local inference; telemetry loss cannot block enforcement or release.
- Same pure extractor offline/live. It does no capture, ML fitting, firewall or I/O.
- Never train on ready-made CSV features that the live extractor cannot reproduce.
- Audit topology/direction/label resolution before claiming egress dataset coverage.
- EGRESS/INGRESS/LOCAL and L3 byte semantics follow SCHEMA, not ad hoc adapter rules.
- Device identity, labels, file names and capture IDs are not ML inputs.
- Keep train/validation/test parent capture groups disjoint; all fitting train-only.
  Threshold/policy selection uses validation; final test does not tune the system.
- Missing/stale/dropped observation is not evidence of benign traffic.
- StateEvent is a policy transition; require separate application/sink evidence.
- Runtime lease/health/result additions need the ADR-0002 contract review first.
- No LLM-to-shell/firewall path or automatic retraining from quarantined traffic.
- Payload-independent features do not imply that capture never buffers payload.

## Network and data safety

Use only owned gateway namespaces/tables; no host ruleset or conntrack flush.
No lab Internet/default route, Tailscale lab subnet advertisement, Docker socket
mount, or replay to public destinations. Capture/enforcer privileges belong in
small reviewed helpers, not the model or telemetry process. Dedicated lab only
for privileged integration; never generic shared privileged CI.

Keep datasets, binaries, credentials, private chat attachments and raw captures out
of Git. Existing `.secrets/` and volumes are preserved across restarts. Never add
`platform/__init__.py` (it shadows Python's stdlib module).

## Verification and reporting

For application changes: use `.venv/bin/python -m unittest discover -s tests -v`,
`.venv/bin/ruff check .`, `.venv/bin/ruff format --check .` as appropriate.
Windows PowerShell equivalents: `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`,
`.\.venv\Scripts\ruff.exe check .`, `.\.venv\Scripts\ruff.exe format --check .`.
For interpreter and dependency installation, use the platform-specific commands in
README.md and the hash lock once KAN-10 lands. Linux availability does not remove
Windows support; never replace the OS Python to satisfy the project interpreter pin.
Linux lab: `bash lab/run_docker.sh`; retain generated evidence and report limits.
Platform: `python3 platform/smoke.py` against initialized Compose services.
For documentation-only work, check links/status consistency/diff; do not add tests
that merely restate prose or rerun privileged integrations without a reason.

Report implemented, measured, approved and proposed separately. A UI state, stub,
service health, architecture drawing or old CI result is not G8/G10 proof.
Record timeout/miss/invalid runs as well as successes. Keep x86/Pi results separate.
Use a bounded local action and ask for genuinely missing external facts only;
do not treat a stale historical checklist as a fresh permission gate.
