# R1 — Onur

Create a reproducible sample-pack builder with source capture, label, processing
and SHA-256 manifest. Keep large data outside Git. Tiny deterministic test fixtures
belong in tests/fixtures; sample packs are integration data, not the full dataset.

## V3 design follow-up

V3 audit: PCAP dosya adı yerine original parent capture/session gruplarıyla split;
cihaz/yön/zaman etiket eşlemesi, exclusions, dönüşüm ve SHA-256 manifesti.
Sentetik fixture araştırma benign tabanı değildir. [Plan](../../docs/architecture/EXECUTION_V3.md).

## Manifest versions

`manifest.json` version 2 adds `manifest_version` and `label_rule_version`
(`data/samplepack/build.py`). `label_rule_version` names the window-labelling rule, so
an experiment manifest (KAN-42) can cite which rule produced a pack's labels. The
current rule is `window-label-1`. Its version must change whenever the rule text, the
label vocabulary or the flow matching changes meaning, and a test enforces that for
the text and vocabulary.

Version-1 manifests have neither field. They stay exactly as KAN-18, KAN-19 and
KAN-21 pinned them and are never rewritten. `model.baseline_run.verify_pack` accepts
both versions and reports a version-1 pack's label rule version as `None`: missing,
not guessed.
