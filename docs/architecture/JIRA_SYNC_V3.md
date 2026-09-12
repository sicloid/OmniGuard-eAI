# V3 plan değişikliği ve inceleme kaydı — 10 Eylül 2026

## İnceleme kapsamı

Yeni [KAN-63](https://sicloid.atlassian.net/browse/KAN-63), ADR-0002 ve V3 kayıt/policy
önerilerinin ekip incelemesini izler. Şükrü accountable; R1/R2/R3 kararları gerekir.
Sözleşme değiştiren işler bu karara bağlıdır; mevcut bağımsız işler ilerleyebilir.
Mevcut kartların sahipleri, tarihleri ve durumları değiştirilmez. Eski açıklamalar
geçmiş kanıt olarak korunur; yeni tarihli V3 bölümü güncel öneriyi açıklar.

## Güncellenen kabul ölçütleri

| Kartlar | Değişiklik |
|---|---|
| KAN-8 | Gabriel'in doğrudan PR inceleme kaynağı; Onur için Lead beyanı ile doğrudan kayıt ayrımı |
| KAN-9/10 | Güvenilir artifact/env manifesti; x86/ARM doğrulama ayrımı |
| KAN-13/14/15 | Capture/yön/etiket audit; parent capture manifest; gerçek feature kataloğu |
| KAN-16/17/18 | Ortak extractor parity; grouped split/train-only fit; rate-rule baseline |
| KAN-19/20/21 | Validation-only policy seçimi; 8 adaylık başlangıç matrisi; transfer test ayrımı |
| KAN-27/28/29 | Drop öncesi capture, bounded queue/health, invalid pencere; yetkisiz model |
| KAN-30/31 | N/gap/stale davranışı; kernel TTL, episode sınırı, crash/reconcile ve uygulama kanıtı |
| KAN-32/33/34 | Saat alanları, ACK/leakage/miss; sınırlı UDS izin/framing |
| KAN-38/39/40/41 | Gabriel ADR koordinasyonu; sürümlü kayıtlar; dedup/recovery; dürüst dashboard |
| KAN-42/43 | Bileşen kaynak maliyeti ve gerçek telemetry hacmi/kayıp |
| KAN-48/49/50 | Stub fault ile gerçek G8/G10 ayrımı; gerçek RF ve arıza/recovery kanıtı |
| KAN-51/52 | False quarantine/device-hour, benign kesinti ve grouped belirsizlik |
| KAN-54/55/56/58 | Tekrarlanabilir freeze/demo; sınırları açık rapor ve diyagram |

Toplam 35 mevcut kartın açıklamasına V3 bölümü ve `architecture-v3` etiketi eklendi;
KAN-63 tek yeni inceleme kartıdır. KAN-36/KAN-37 zaten Tamamlandı; yeniden kapatılmaz.

## Gabriel'in PR #2 incelemesinin karşılığı

[PR #2](https://github.com/sicloid/OmniGuard-eAI/pull/2) birleşti.
[İnceleme eki](https://github.com/user-attachments/files/32051716/pr2review.md)
mevcut sözleşmeleri açıkça kabul ediyor; GitHub review durumu **COMMENTED**.
Bu yüzden formal APPROVED review varmış gibi raporlanmaz.

- G1 tablosu Gabriel'in doğrudan kaynağına bağlandı; soru kalan karar cümlesi düzeltildi.
- Onur için önceki Lead onay beyanı korundu; doğrudan R1 kayıt takibi KAN-63'e taşındı.
- `python -O` artık smoke başlamadan hata verir; optimizasyonda sahte PASS regresyon testi eklendi.
- Mosquitto negatif PUBACK metnine bağımlılık ve local-dev secret izinleri belgelendi.
- Compose JSON/JSONL Windows uyarlaması Gabriel'in kendi takip işi olarak kaldı.
- Gabriel'in sıradaki KAN-38 UDS/framing ADR'si V3 kayıt önerileriyle koordine edilir.

## Ekibe gönderilebilecek mesaj

“PR #2 birleşti; Linux/Docker altyapı kontrolleri tamam. V3 mimari önerisini KAN-63
ve mimari PR'ında incelemeye açtım; görev sahiplerini ve tarihleri değiştirmedim.
Onur tarafında önce veri yönü/etiket audit'i, ortak extractor parity ve capture bazlı
split; bende gözlem kaybı/N davranışı, süreli kernel karantinası ve gerçek uygulama
kanıtı; Gabriel tarafında KAN-38 ADR'siyle uyumlu sürümlü kayıtlar, dedup/recovery ve
dashboard ayrımı netleşti. Deneylere benign kesinti, false quarantine/device-hour ve
miss/timeout ölçümleri eklendi. Yeni sözleşmeler ekip incelemesinden sonra uygulanacak;
G8/G10 henüz geçilmedi. Onur'un mevcut sözleşmeler için doğrudan inceleme kaydını da
KAN-63'te tamamlayalım.”

Doğrulama: 35 kart yeniden okundu; V3 metinleri/etiketleri eşleşiyor, mevcut
assignee/duedate/status değerleri korunuyor. 22 birim test, Ruff lint/format ve
çalışan Compose smoke geçti. Yerel önceki Jira kayıtları ignored artifacts altında tutulur.
