# G15 release readiness (KAN-60)

Status at 22 September 2026: **not ready to tag**. This file is the lead's
review checklist and current evidence map. It is not a release declaration.
Do not create a release tag by treating a missing gate as a warning.

| Gate | Required evidence | Current state |
|---|---|---|
| G8 / KAN-49 | Real pinned RF and audited development capture through extractor, policy and nftables; independent TCP/UDP sink stop, restore and SIGKILL/kernel expiry | Accepted at the [bounded development-validation scope](G8_RUNBOOK.md); PR #41 merged. |
| G10 / KAN-50 | Real StateEvent through UDS, MQTT, PostgreSQL and Grafana, plus decision/application correlation, dedup, outage recovery and completeness/loss report | Local partial integration evidence exists; owner-reviewed full G10 remains open. |
| G13 / KAN-54 | Exact frozen result set with run IDs, hashes, data role, failed/censored attempts, declared N/lease and plots | [Inventory](KAN54_FREEZE_INVENTORY.md) exists; KAN-52 headline experiment and other accepted measurements remain missing. |
| Pi / KAN-53 | Separate ARM64 evidence with environment and load; no laptop number copied into Pi results | [Real Pi lab](evidence/PI5_2026-09-22_constrained/README.md) passed functionally. Guard invalidated its timing; no accepted Pi performance estimate. |
| Reproduction / KAN-55 | Clean checkout from locked environment through data, training, lab, platform, G8/G10 and fallback | [Reproduction map](REPRODUCE.md) is in review; G10 steps must be updated when its gate passes. |
| Demo / KAN-58 | Pi path, laptop fallback, fault handling and cleanup | [Runbook](DEMO_RUNBOOK.md) is in review; keep missing gates visible in the demo. |
| Team / KAN-59 | Şükrü, Onur and Gabriel each explain every contract and trade-off; date, gaps and reviewed runs recorded | [Rehearsal script](TEAM_QA_REHEARSAL.md) prepared; actual three-person rehearsal has not been recorded. |

## When the prerequisites pass

1. Record a clean checkout of the exact candidate commit, Python and dependency
   lock versions, Docker image digests, model/data hashes, and the operating
   policy. Run the test, Ruff, lab and platform sequences in
   [REPRODUCE.md](REPRODUCE.md). Keep the raw output and exit codes.
2. Link the accepted G8 and G10 gate evidence and the G13 frozen manifest.
   Verify every hash against the actual files. Show censored and invalid runs
   alongside the accepted set; never silently drop them.
3. Perform the [demo](DEMO_RUNBOOK.md) and record its cleanup evidence.
   Record the actual team [Q&A rehearsal](TEAM_QA_REHEARSAL.md).
4. Obtain the owner reviews for the exact candidate. Only then create the
   release tag on that commit and record the tag target and SHA-256 of the
   release inventory in Jira KAN-60. If any prerequisite changes, repeat the
   affected checks on the new commit before tagging.

An optional Pi performance figure is omitted when its guard verdict is
`invalid`. The real ARM64 functional observation may still be presented with
its power, cooling and load limits. No 27 W supply is required by the project
contract; a power change cannot retroactively validate an earlier timing run.
