# Jira Kanban planı — 10 Eylül 2026

Linux devamı: aşağıdaki ilk durum özeti Windows bootstrap anına aittir. Güncel
çalışma ve kanıtlar: [STATUS.md](STATUS.md), [LINUX_VALIDATION.md](LINUX_VALIDATION.md).
Onur artık GitHub @pondilungs ile ekipte; PR #1 birleştirildi.

Güncel durum Jira'dan tekrar okunarak doğrulandı:

- Tamamlandı: KAN-7, KAN-8, KAN-11, KAN-24, KAN-25, KAN-26.
- İncelemede: yeni Compose/Mosquitto uygulamaları KAN-36/KAN-37; Gabriel review.
- Önceki tamamlanan KAN-12/KAN-61/KAN-62 değiştirilmedi.
- [PR #2](https://github.com/sicloid/OmniGuard-eAI/pull/2): Linux doğrulaması,
  platform kurulumu, ekip/sözleşme kayıtları. Windows/Linux/platform CI başarılı.

## İlk bootstrap durum kaydı (tarihsel)


Kullanıcı isteğiyle KAN board üzerinde 6 epik, V2 kaynağındaki 54 görev, 1 yerel bootstrap görevi ve 1 şema uygulama alt görevi oluşturuldu. Toplam 62 kart. Tüm atamalar/epik ilişkileri/ana görev hedef tarihleri Jira'dan tekrar okunarak doğrulandı.

Roller: Şükrü Lead/R2; Onur R1/ML; Gabriel R3/platform. G1=10 Eylül, G15=30 Eylül; hafta sonları hariç. Tarihler planlama hedefidir. Onur'un fiili başlangıcı gecikirse R1 hedefleri yeniden planlanır.

Etiketler: `bu-hafta` = G1/G2'de başlayan işler; `hafta-1` = G1–G5 (10–16 Eylül); `hafta-2` = G6–G10; `hafta-3` = G11–G15; `stretch` = opsiyonel. Kişi başına bir büyük iş Devam ediyor. Bağımlılıklar kart açıklamalarındadır; Jira issue-link ilişkileri kurulmadı.

Tamamlandı: KAN-12 deterministik stublar, KAN-61 yerel repo/bootstrap, KAN-62 taslak şema uygulaması ve yerel testleri. Kanıt: a122400, 9 test, Ruff ve smoke. GitHub push/review/hosted CI veya gerçek G8/G10 tamamlanması anlamına gelmez.

Devam ediyor: KAN-8 sözleşme inceleme/freeze; ekip onayı eksik. Diğer 58 kart Yapılacaklar (6 epik dahil).

## Kart eşlemesi

| Kart | Görev | Sorumlu | Hedef |
|---|---|---|---|
| KAN-7 | G1 mimari toplantısı ve kararların onaylanması | Şükrü | 2026-09-10 |
| KAN-8 | Veri sözleşmelerinin gözden geçirilmesi ve sürümün sabitlenmesi | Şükrü | 2026-09-11 |
| KAN-9 | Model artifact sözleşmesi ve uyumluluk kontrolü | Onur | 2026-09-11 |
| KAN-10 | Python ve tüm bağımlılıkların sürümlerini sabitleme | Gabriel | 2026-09-11 |
| KAN-11 | GitHub CI çalıştırılması ve CODEOWNERS incelemesi | Şükrü | 2026-09-11 |
| KAN-12 | Deterministik geliştirme stubları | Şükrü | 2026-09-10 |
| KAN-13 | CICIoT2023 veri seti denetimi | Onur | 2026-09-11 |
| KAN-14 | Tekrarlanabilir fixture ve sample pack üreticisi | Onur | 2026-09-14 |
| KAN-15 | Özellik kataloğu v1 | Onur | 2026-09-11 |
| KAN-16 | Ortak saf özellik çıkarıcı | Onur | 2026-09-15 |
| KAN-17 | Capture-aware eğitim/doğrulama/test ayrımı | Onur | 2026-09-15 |
| KAN-18 | İlk Random Forest modeli ve metrikler | Onur | 2026-09-16 |
| KAN-19 | Yalnız doğrulama verisiyle eşik kalibrasyonu | Onur | 2026-09-17 |
| KAN-20 | Özellik ablasyonu ve hesaplama maliyeti | Onur | 2026-09-18 |
| KAN-21 | Görülmemiş veri holdout deneyi | Onur | 2026-09-24 |
| KAN-22 | Isolation Forest deneyi [stretch] | Onur | 2026-09-25 |
| KAN-23 | CICIoT2023 → IoT-23 aktarım deneyi [stretch] | Onur | 2026-09-25 |
| KAN-24 | İzole A → B → C network namespace laboratuvarı | Şükrü | 2026-09-10 |
| KAN-25 | nftables güvenliği ve conntrack bypass testi | Şükrü | 2026-09-11 |
| KAN-26 | PCAP → PacketTuple adapterı | Şükrü | 2026-09-14 |
| KAN-27 | Canlı trafik → PacketTuple adapterı | Şükrü | 2026-09-15 |
| KAN-28 | Cihaz başına 5 saniyelik tumbling pencereler | Şükrü | 2026-09-15 |
| KAN-29 | Modelden bağımsız detector arayüzü | Şükrü | 2026-09-16 |
| KAN-30 | N anomalili state machine ve süreli serbest bırakma | Şükrü | 2026-09-17 |
| KAN-31 | Gerçek quarantine ve release uygulaması | Şükrü | 2026-09-17 |
| KAN-32 | Tekrarlanabilir replay harness ve t0 işaretçisi | Şükrü | 2026-09-18 |
| KAN-33 | Containment leakage paket/byte sayacı | Şükrü | 2026-09-18 |
| KAN-34 | Gateway → host Unix socket olay köprüsü | Şükrü | 2026-09-21 |
| KAN-35 | Yalnız laptop ile çalışan core demo | Şükrü | 2026-09-29 |
| KAN-36 | Docker Compose platform iskeleti | Gabriel | 2026-09-11 |
| KAN-37 | Mosquitto yapılandırması ve pub/sub testi | Gabriel | 2026-09-14 |
| KAN-38 | StateEvent → TelemetryPayload/MQTT adapterı | Gabriel | 2026-09-14 |
| KAN-39 | PostgreSQL şeması ve başlangıç migration'ı | Gabriel | 2026-09-15 |
| KAN-40 | MQTT → PostgreSQL telemetry consumer | Gabriel | 2026-09-15 |
| KAN-41 | Sahte verili Grafana dashboard | Gabriel | 2026-09-16 |
| KAN-42 | CPU/RAM/gecikme ölçüm harness'ı | Gabriel | 2026-09-17 |
| KAN-43 | Telemetri byte hacmi ölçümü | Gabriel | 2026-09-17 |
| KAN-44 | Pi5 ve Tailscale management kurulumu | Gabriel | 2026-09-17 |
| KAN-45 | Kontrollü hesaplama bütçesi benchmark'ı | Gabriel | 2026-09-25 |
| KAN-46 | Pi ölçümünde yük ve throttling kontrolü | Gabriel | 2026-09-24 |
| KAN-47 | FastAPI uzak inference karşılaştırması [stretch] | Gabriel | 2026-09-25 |
| KAN-48 | Stub tabanlı state/enforcement uçtan uca test | Şükrü | 2026-09-16 |
| KAN-49 | G8 — Gerçek trafik kısıtlama kapısı | Şükrü | 2026-09-21 |
| KAN-50 | G10 — Telemetri ve gözlemlenebilirlik kapısı | Gabriel | 2026-09-23 |
| KAN-51 | N / FPR / gecikme deneyi | Onur | 2026-09-24 |
| KAN-52 | FPR / Containment Leakage ana deneyi | Onur | 2026-09-28 |
| KAN-53 | Raspberry Pi ARM64 doğrulaması | Gabriel | 2026-09-25 |
| KAN-54 | G13 — Ölçüm sonuçlarını sabitleme | Şükrü | 2026-09-28 |
| KAN-55 | Uçtan uca tekrarlanabilir README | Şükrü | 2026-09-28 |
| KAN-56 | Runtime ve network plane mimari diyagramları | Gabriel | 2026-09-25 |
| KAN-57 | Metodoloji ve sınırlamalar dokümanı | Onur | 2026-09-28 |
| KAN-58 | Demo runbook ve temizleme adımları | Şükrü | 2026-09-29 |
| KAN-59 | Ekip içi bilgi aktarımı ve Q&A provası | Şükrü | 2026-09-30 |
| KAN-60 | G15 — Son sürüm ve demo yayını | Şükrü | 2026-09-30 |

