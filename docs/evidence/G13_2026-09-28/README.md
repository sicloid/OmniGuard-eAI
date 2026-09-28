# G13 final result freeze

`result-freeze.json` pins 356 files from Git commit
`17bd01098c312640eb182bdd052658007b8c8049`. It embeds the exact declaration
and records every selected path, byte length and SHA-256.

The frozen set includes all retained `docs/evidence` bundles, `model/frozen`,
the selected runtime profile and every top-level experiment specification. It
therefore retains failed, censored, rejected and adverse results alongside
successful runs. Raw datasets, PCAPs and model binaries remain outside Git and
are represented by their recorded hashes.

Verify before a demo or release:

```sh
python -m measure.result_freeze verify \
  --root . docs/evidence/G13_2026-09-28/result-freeze.json
(cd docs/evidence/G13_2026-09-28 && sha256sum -c result-freeze.json.sha256)
```

Manifest SHA-256:
`de37d7e18914adf929edf5dc9b1803667f599e4997e1f53f901a75ce35942aa6`.
