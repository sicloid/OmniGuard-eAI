# G15 release readiness (KAN-60)

Status at 28 September 2026: **technical candidate accepted; team rehearsal
still required before tagging**. PR #57 merged as `b76426c` and PR #58 merged
as `ff18170`. Onur and Gabriel approved the final work, hosted CI is green, and
the integrated Linux suite passed 701 tests with three platform skips. Do not
create the release tag until KAN-59 records the actual three-person rehearsal.

| Gate | Required evidence | Current state |
|---|---|---|
| G8 / KAN-49 | Real pinned RF and audited development capture through extractor, policy and nftables; independent TCP/UDP sink stop, restore and SIGKILL/kernel expiry | Accepted at the [bounded development-validation scope](G8_RUNBOOK.md); PR #41 merged. |
| G10 / KAN-50 | Real StateEvent through UDS, MQTT, PostgreSQL and Grafana, plus decision/application correlation, dedup, outage recovery and completeness/loss report | Accepted at the bounded local scope. Sealed normal, duplicate and broker-outage/recovery evidence is under `docs/evidence/G10_2026-09-24/`. |
| G13 / KAN-54 | Exact frozen result set with run IDs, hashes, data role, failed/censored attempts, declared N/lease and plots | Accepted. The final 437-file inventory pins commit `83ae2873…` and manifest SHA-256 `70a5a7dc…3926`; earlier freezes remain as audit history. |
| Pi / KAN-53/KAN-66 | Separate ARM64 evidence with environment and load; no laptop number copied into Pi results | Functional ARM64 lab retained with invalid timing. A later one-hour fresh-benign Pi capture completed with no throttle bits and is used only for functional/generalisation evidence, not performance. |
| Reproduction / KAN-55 | Clean checkout from locked environment through data, training, lab, platform, G8/G10 and fallback | Accepted in PR #57. [`REPRODUCE.md`](REPRODUCE.md) and `./demo.sh evidence` bind the final evidence checks. |
| Demo / KAN-58 | Pi path, laptop fallback, fault handling and cleanup | Accepted. The Linux/Docker rehearsal, cleanup and sealed fallback log are under `docs/evidence/KAN58_2026-09-28/`. |
| Team / KAN-59 | Şükrü, Onur and Gabriel each explain every contract and trade-off; date, gaps and reviewed runs recorded | Script and individual preparation exist; actual three-person rehearsal record is the sole open release gate. |

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
