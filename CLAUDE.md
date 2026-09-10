# CLAUDE.md

Read [AGENTS.md](AGENTS.md) first; it is the common agent instruction source.
[AI_SYSTEM_PROMPT.md](AI_SYSTEM_PROMPT.md) supplies the shared project context.
Do not maintain a conflicting copy of those rules here.

## Read order and evidence

Follow AGENTS.md, then README.md, docs/STATUS.md, SCHEMA.md, accepted ADRs,
ARCHITECTURE.md and docs/architecture/EXECUTION_V3.md, then the module README.
V3 and ADR-0002 are proposals pending KAN-63 team review. Current wire contracts
remain 0.1.0; older team approval does not approve new envelopes.
Onur’s existing approval is Lead-reported; direct R1 evidence is tracked in KAN-63.
Gabriel explicitly accepted existing contracts in his PR #2 review text.

## Operational reminders

- Use a feature branch and reviewed PR; never commit or push directly to main.
- CODEOWNERS defines roles. Declare cross-owner changes in the PR; tests do not replace review.
- No managed-cloud dependency in the runtime. Historical/cloud comparisons are documentation.
- No datasets, PCAPs, credentials or model binaries in Git.
- Lab traffic stays isolated; do not flush host firewall rules. Tailscale is management only.
- Synthetic fixtures validate software, not ML effectiveness or real G8/G10 gates.
- Never create platform/__init__.py: it would shadow Python’s standard library.
- UTC event timestamps and monotonic durations are distinct clock domains.
- Follow WIP=1, preserve Jira owners/dates, and record real evidence before closure.

## Validation

From the repository root, using the development environment:

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

For platform changes, run `python3 platform/smoke.py` against the running Compose
stack without Python optimization. Service smoke is not G10. Privileged namespace
tests belong only on the dedicated isolated Linux lab host, never shared CI.
