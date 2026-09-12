# Review and integration evidence — 12 September 2026

All twelve previously open PRs (#4–#15) were reviewed and merged. Merge order
preserved the live/replay and model training/calibration dependencies. Conflicts
in status/module documentation retained both components' content. No force push
or direct commit to main was used.

## Corrections made during review

- PR #4: R1/R3 responses, PowerShell and PR/Jira rules, direct G1 evidence,
  identity/spool/migration/provisioning decisions, manifest ownership and attack matrix.
- PR #10: macOS coverage, explicit pip pin, reproducible core/ML hash locks and
  hosted ML imports. R1's sklearn 1.8.0/numpy 2.5.3 versions are preserved.
- PR #11: deployment must pin both model and exact metadata bytes. Modified
  threshold/feature metadata cannot reuse a valid model hash. File/load errors
  stay in the ArtifactError boundary; SCHEMA describes the artifact fields.
- PR #14: real RF round-trip supplies the independently retained metadata pin.
- PR #15: selection only accepts validation; loaded policies cannot bypass
  provenance, threshold/metrics/objective/budget checks. Duplicate/nonfinite JSON
  and malformed documents are rejected consistently.

## Executed evidence

CachyOS x86_64, project Python **3.14.7**. The OS interpreter remains 3.14.6.
The prior project venv is retained outside Git for rollback; it was not erased.

- Fresh full-ML `pip --require-hashes` install, followed by editable installation
  with `--no-deps --no-build-isolation`, and `pip check`: pass.
- Final combined main runtime: **129 tests in 1.114 s, zero skips**, Ruff check
  and format check pass. RF save/load tests use actual locked ML libraries.
- Live Docker probe: baseline and release sent/capture/sink = 100/100/100;
  quarantine = 100/100/0; forced overflow detected 9,991 socket drops. Cleanup passes.
- Docker replay: two independent runs each sent/capture/sink = 100/100/100;
  unique run IDs, reference timestamps, host refusal and cleanup pass.
- Existing Compose stack: PostgreSQL SELECT 1, MQTT QoS1 pub/sub, anonymous and
  unauthorized-topic rejection, Grafana health/admin login pass. Existing secrets
  and volumes are preserved.

Raw logs are retained locally outside Git in the sibling `review-audit/` directory:
`final-main-tests.log`, `project-venv-install.log`, `platform-smoke.log`,
`live-integration.log`, `replay-integration.log`. Detailed network artifacts are
in the sibling `review-integration/artifacts/live-capture.JgTu4HI2` and
`review-integration/artifacts/replay.aR6QrQl9`. These paths identify local evidence;
they are not public download links and no raw PCAP/secret/model is committed.

Hosted checks on the reviewed heads also passed:

- [PR #10 Linux/Windows/macOS and platform](https://github.com/sicloid/OmniGuard-eAI/actions/runs/34662610785)
- [PR #11 integrated checks](https://github.com/sicloid/OmniGuard-eAI/actions/runs/34662757889)
- [PR #14 integrated checks](https://github.com/sicloid/OmniGuard-eAI/actions/runs/34662830069)
- [PR #15 integrated checks](https://github.com/sicloid/OmniGuard-eAI/actions/runs/34662850943)

These prove software behavior and the stated lab/service observations. They do
not prove real dataset/model effectiveness, production isolation, Linux ARM64/Pi
support or **G5/G8/G10**. Those gates remain unpassed.

## Approval and Jira record

R1/R3 written architecture reviews are in PR #4. For R2 PRs #5–#8, Şükrü explicitly
reported team review/approval in this session; that was recorded as user-reported
approval, not a fabricated GitHub reviewer vote. Other authors' PRs received the
Lead code review and approval after checks and corrections.

KAN-10/27/29/32 moved to Tamamlandı with acceptance evidence. KAN-63 also
moved to Tamamlandı after correcting the interpretation of the PR #4 approval. KAN-9/15/16/17/18/19/28
retain their real-data, catalogue or runtime integration acceptance requirements;
KAN-38 retains its own concrete framing/topic/ACK work; Gabriel explicitly made
those follow-ups non-blocking for the architecture review. Their code may be
merged while their broader acceptance remains open. Owners and dates did not change.
See [current status](STATUS.md) and [review decisions](architecture/REVIEW_RESOLUTION_2026-09-12.md).
