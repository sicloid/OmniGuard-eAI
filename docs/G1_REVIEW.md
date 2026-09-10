# KAN-7 / KAN-8 — Ekip karar ve inceleme paketi

Durum: uygulama ve teknik inceleme hazırlığı; toplantı veya ekip onayı gerçekleştiği iddia edilmez.

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

## Açık kararlar

1. UTC Unix zamanları, half-open epoch-aligned pencereler ve nullable port/MAC semantiği kabul mü?
2. LOCAL cihaz kimliği gönderen LAN cihazıdır; INGRESS kimliği alıcı LAN cihazıdır.
3. Eksik device mapping sessiz yeni kimlik üretmez: sayaçla filtrelenir. Bozuk/truncated IP hata verir.
4. PCAP adapterı klasik PCAP destekler; PCAPNG açıkça reddedilir. IPv6 jumbogram yok.
5. Feature catalog Onur'un ayrı görevidir; stub feature'ları üretim kataloğu değildir.
6. Lab ilk sürüm IPv4-only ve sabit adreslidir. Genel runtime enforcement KAN-31 kapsamındadır.

## Onay kaydı (yalnız gerçek inceleme sonrası doldurulur)

| Rol | Karar | Tarih / kanıt |
|---|---|---|
| R1 Onur | Bekliyor | — |
| R2/Lead Şükrü | Bekliyor | — |
| R3 Gabriel | Bekliyor | — |

KAN-7 karar/onay kaydı tamamlanınca; KAN-8 ADR onayı ve sürüm kararıyla kapanabilir.
AI tarafından testlerin geçmesi bu onayların yerine geçmez.
