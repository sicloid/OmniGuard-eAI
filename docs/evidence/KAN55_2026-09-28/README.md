# KAN-55 clean-archive reproduction evidence — 28 September 2026

The repository was exported with `git archive` from commit
`4abf34a94855c1b9e6532cbf4de660479333b929` into a new temporary directory.
No untracked model, PCAP, generated artifact or source-worktree file was copied.

Inside that archive:

- Ruff passed;
- 688 tests passed with three declared platform-absence skips; and
- `./demo.sh evidence` verified the sealed G10 fallback.

The combined output is `clean-archive.log`, SHA-256
`b6bb46298aa6e1651cd6e2f214144799ef2df70255b4abaccf42873297722603`.
This proves the checked-in unprivileged suite and evidence fallback do not depend
on ignored local files. The privileged live demo has separate KAN-58 evidence;
external model/PCAP reruns still require their declared hash-pinned inputs.
