# G8 evidence index

[`G8_2026-09-20.json`](G8_2026-09-20.json) indexes two runs from a clean
checkout of PR #41: orderly controller completion and a separate SIGKILL run.
The exact original KAN-19 model and prepared IoT-23 validation slice stayed
outside Git and were mounted read-only. The index records their SHA-256 pins,
the run-code commit, the later validator-only commit, each validator result and
SHA-256 hashes of the raw logs. The small, payload-free source/sink, controller,
kernel and replay-manifest logs are committed unchanged under
[`G8_2026-09-20_raw/`](G8_2026-09-20_raw/); the model and PCAP bytes are **not**.
From the repository root, a reviewer can rerun both validators directly:

```sh
python3 -m lab.g8_iot23_validate docs/evidence/G8_2026-09-20_raw/orderly
python3 -m lab.g8_iot23_kill_validate docs/evidence/G8_2026-09-20_raw/sigkill
```

The index hashes allow exact-byte checks on this bundle or on an independent
rerun using [the runbook](../G8_RUNBOOK.md). A copied bundle is reviewable
evidence, not an independent rerun or independent owner approval.

The normal validator's `not_yet_proven` list is scoped to that one run. The
separate SIGKILL entry supplies the kernel-TTL observation; neither entry
supplies an independent owner review. This index is development-validation
integration evidence for N=1 and a six-second lease, not an unseen-data FPR,
Raspberry Pi performance result or a G13 frozen metric set.
