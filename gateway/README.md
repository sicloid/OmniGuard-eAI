# R2 — Şükrü

Next: per-device 5-second tumbling windows, detector interface, configurable N
state machine, reversible nftables enforcement and conntrack regression test.
Use `stubs.fake_features` and `stubs.fake_detector` to develop independently.
Enforce only in the gateway namespace. Sink stop and restore are required evidence.

## V3 design follow-up

V3 tasarım notu: karar/uygulama ayrımı, bounded kernel lease, restart uzlaştırması,
N=1/gap semantiği ve observation health için [mimariyi](../ARCHITECTURE.md) ve
[önerilen ADR-0002](../docs/adr/0002-bounded-containment.md) okuyun. Yeni kayıtlar
henüz onaylı 0.1.0 sözleşmesinin parçası değildir.
