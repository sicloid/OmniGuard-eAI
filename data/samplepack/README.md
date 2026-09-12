# R1 — Onur

Create a reproducible sample-pack builder with source capture, label, processing
and SHA-256 manifest. Keep large data outside Git. Tiny deterministic test fixtures
belong in tests/fixtures; sample packs are integration data, not the full dataset.

## V3 design follow-up

V3 audit: PCAP dosya adı yerine original parent capture/session gruplarıyla split;
cihaz/yön/zaman etiket eşlemesi, exclusions, dönüşüm ve SHA-256 manifesti.
Sentetik fixture araştırma benign tabanı değildir. [Plan](../../docs/architecture/EXECUTION_V3.md).
