# KAN-7 / KAN-8 — Ekip karar ve inceleme paketi

Durum: 2026-09-10 tarihinde Şükrü, bu oturumda Onur, Gabriel ve kendisinin
mevcut mimari ve sözleşmeleri onayladığını açıkça doğruladı. PR #1 birleştirildi.
Bu kayıt kullanıcının ekip onayı beyanıdır; ayrıca toplantı yapıldığı iddia edilmez.

## Kayıtlı proje tercihleri

V2 belgeleri ve kullanıcının son rol doğrulaması esas alınmıştır:

- Şükrü: Lead/R2. Onur: R1/ML. Gabriel: R3/platform ve telemetri.
- Yerel RF; CICIoT2023 primary, IoT-23 secondary; capture-aware split, validation-only threshold.
- Tek saf extractor; EGRESS primary; L3 byte semantiği; device_id ML girdisi değil.
- 5 saniye tumbling baseline; model yalnız DetectionResult üretir.
- İzole A→B→C netns; host firewall değişmez; Tailscale yalnız management.
- Mosquitto/PostgreSQL/Grafana ve UDS bridge; managed cloud bağımlılığı yok.
- G8 gerçek sink stop/restore; G10 gerçek event zinciri; Pi development blocker değil.

## İncelenecek somut dosyalar

| İnceleyen | Dosyalar | Beklenen karar |
|---|---|---|
| Onur | core/schema.py, SCHEMA.md, sources/packets.py | FeatureVector/model alanları; IP/port metadata; fragmentlerin feature hesabındaki politikası |
| Gabriel | TelemetryPayload, StateEvent, SCHEMA.md | Event kimliği, retry/dedup ve UDS/MQTT framing için sonraki ADR kapsamı |
| Şükrü | lab/*.sh, lab/ruleset.nft, sources/* | İzolasyon, namespace sahipliği, conntrack sırası, LAN/device mapping ve parser hata politikası |

## Onaylanan kararlar

1. UTC Unix zamanları, half-open epoch-aligned pencereler ve nullable port/MAC semantiği kabul edildi.
2. LOCAL cihaz kimliği gönderen LAN cihazıdır; INGRESS kimliği alıcı LAN cihazıdır.
3. Eksik device mapping sessiz yeni kimlik üretmez: sayaçla filtrelenir. Bozuk/truncated IP hata verir.
4. PCAP adapterı klasik PCAP destekler; PCAPNG açıkça reddedilir. IPv6 jumbogram yok.
5. Feature catalog Onur'un ayrı görevidir; stub feature'ları üretim kataloğu değildir.
6. Lab ilk sürüm IPv4-only ve sabit adreslidir. Genel runtime enforcement KAN-31 kapsamındadır.

## Onay kaydı (yalnız gerçek inceleme sonrası doldurulur)

| Rol | Karar | Tarih / kanıt |
|---|---|---|
| R1 Onur (@pondilungs) | Onaylandı (PR #4 doğrudan R1 incelemesi) | 2026-09-11, [PR #4 R1 incelemesi](https://github.com/sicloid/OmniGuard-eAI/pull/4#pullrequestreview-5180898909); GitHub durumu COMMENTED; 10 Eylül Lead beyanını doğruluyor |
| R2/Lead Şükrü (@sicloid) | Onaylandı | 2026-09-10, doğrudan kullanıcı onayı; PR #1 merge |
| R3 Gabriel (@Gabi8347) | Onaylandı (inceleme metninde açık kabul) | 2026-09-10, [PR #2 inceleme eki](https://github.com/user-attachments/files/32051716/pr2review.md); GitHub review durumu COMMENTED |

KAN-7 için karar/onay kaydı tamamlandı. KAN-8 kapsamında ADR-0001 kabul edildi ve
sözleşme sürümü alan/semantik değişmeden `0.1.0` olarak sabitlendi. Stub özellikleri
gerçek özellik kataloğu değildir; model/telemetri uygulama görevleri ayrı kalır.

Gabriel ve Onur'un doğrudan incelemeleri önceki Lead beyanını doğrular.
KAN-7/KAN-8 geçmiş kapanışları ve wire 0.1.0 korunur. V3 için yeni ekip incelemesi gerekir.
