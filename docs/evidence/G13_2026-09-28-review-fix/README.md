# G13 review-fix result freeze

This immutable manifest supersedes the earlier G13 inventory for the final PR
review. It pins 363 files from Git commit
`7cffa00327df5a229fa85d24ebb393502495e57d`, including the review-complete
KAN-45 cgroup evidence and KAN-47 localhost comparison. The original freeze is
retained unchanged as audit history.

Verify before the demo or release:

```sh
python -m measure.result_freeze verify \
  --root . docs/evidence/G13_2026-09-28-review-fix/result-freeze.json
(cd docs/evidence/G13_2026-09-28-review-fix && \
  sha256sum -c result-freeze.json.sha256)
```

Manifest SHA-256:
`7c2103bc806735dbf79e8bc800b6838285dc08d70398e012199d0f04cb212f8a`.
