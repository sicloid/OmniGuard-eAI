# G13 final integrated result freeze

This manifest is the final integrated inventory after PR #58 added the sealed
gateway-runtime compute-budget comparison. It supersedes both earlier G13
inventories while retaining them unchanged as audit history.

The manifest pins 437 evidence and model-specification files from Git commit
`83ae2873360955facc35f0c088993371796ea303`.

Verify before the demo or release:

```sh
python -m measure.result_freeze verify \
  --root . docs/evidence/G13_2026-09-28-final/result-freeze.json
(cd docs/evidence/G13_2026-09-28-final && \
  sha256sum -c result-freeze.json.sha256)
```

Manifest SHA-256:
`70a5a7dcd5b07676ee9de29ae430b4093df86d0d929312f259cf6230ecbc3926`.
