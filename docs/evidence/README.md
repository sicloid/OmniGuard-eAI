# G8 evidence index

[`G8_2026-09-20.json`](G8_2026-09-20.json) indexes two runs from a clean
checkout of PR #41: orderly controller completion and a separate SIGKILL run.
The exact original KAN-19 model and prepared IoT-23 validation slice stayed
outside Git and were mounted read-only. The index records their SHA-256 pins,
the run-code commit, the later validator-only commit, each validator result and
SHA-256 hashes of the local raw logs. The raw logs themselves are **not** in Git;
hashes let a reviewer verify matching files if they receive the evidence bundle
or rerun the commands in [the runbook](../G8_RUNBOOK.md).

The normal validator's `not_yet_proven` list is scoped to that one run. The
separate SIGKILL entry supplies the kernel-TTL observation; neither entry
supplies an independent owner review. This index is development-validation
integration evidence for N=1 and a six-second lease, not an unseen-data FPR,
Raspberry Pi performance result or a G13 frozen metric set.
