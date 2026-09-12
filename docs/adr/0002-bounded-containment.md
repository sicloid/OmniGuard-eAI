# ADR-0002 — Gözlem sağlığı, uygulama kanıtı ve süreli karantina

Tarih: 2026-09-10. Durum: **PROPOSED**. Sahipler: Şükrü/R2, Onur/R1,
Gabriel/R3. Bu oturum V3 doküman incelemesini yetkilendirir; daha önceki V2 ekip
onayı yeni wire sözleşmelerinin onayı değildir. Runtime kodu değiştirilmedi.

## Problem

Mevcut StateEvent politika geçişini anlatır. nft komutu başarısız olsa bile
QUARANTINED kararı oluşabilir. TelemetryPayload'da application result, skor,
health veya sıralama yoktur. Capture drop ve süreç çökmesi de tanımlanmamıştır.
Bu boşluklar UI'ın gerçekte olmayan korumayı göstermesine veya sınırsız bloklara
neden olabilir. Mevcut lab smoke bu genel runtime semantiğini uygulamıyor.

## Önerilen karar

Mevcut beş `0.1.0` envelope korunur. Aşağıdaki kayıtlar ayrıca versioned olur;
kesin JSON alanları, enum isimleri ve framing tasarımı bu ADR'nin kod-review
uygulamasında sabitlenir. Bu tablolar bugün yüklenebilir bir schema değildir.

| Önerilen kayıt | Üreten / tüketen | Gerekli içerik |
|---|---|---|
| ObservationHealth | source/window → policy/measure | source/run id, window aralığı, input/emitted/drop/overflow sayıları, saat kalitesi, kullanılabilirlik gerekçesi; ölçülemeyen sayaç null, sıfır değil |
| EnforcementResult | enforcer → runtime/telemetry | decision_id, device/binding version, action, applied/failed/reconciled sonucu, namespace identity, monotonic begin/ack, actual lease expiry, sanitized hata |
| DetectionRecord | runtime wrapper → telemetry | özgün DetectionResult, decision/window/run ilişkisi; `model_version`, `model_sha256`, `feature_schema_version`, `policy_version` bağlamı |
| HealthRecord | service → telemetry | observation/enforcement/exporter durumu; DeviceState'e yeni enum eklemeden ayrı sağlık durumu |
| ExperimentManifest | harness → audit/evaluate | code/env/artifact/policy/split hash, capture parent groups, time mapping, run hardware, resource budget ve kapsam |

`decision_id` policy/runtime tarafından bir kez atanır; enforcer aynı kimliği
sonuçta döndürür. Telemetry `event_id` ilk kayıt oluşturulurken atanır ve retry'da
korunur. Retry sırasında yeni saat okunarak kimlik türetilmez. Özgün olayın sabit
alanlarından UUID5 türetimi KAN-38 için geçerli bir adaydır; yalnız
`run_id|device_id|timestamp|previous_state|new_state` farklı olayları ayırt etmeyi
garanti etmez. Canonical serialization, producer/boot/sequence kapsamı, timestamp
precision ve aynı zamanlı farklı olay testi ADR'de tanımlanmalı. Kimlik/sequence
atama ile durable spool yazımı arasındaki crash/re-delivery aralığı da test edilir;
aynı olay aynı kimliği, farklı olay farklı kimliği korur. Sequence aynı producer boot/run
kapsamında sıralanır; restart sonrasında eski sıra yeni boot'a karıştırılmaz.

0.1.0 TelemetryPayload, DetectionRecord veya EnforcementResult taşıyormuş gibi
genişletilemez. Öneri: event türü başına ayrı versioned envelope/topic; eski
state topic'i korunur. Alternatif tek yeni envelope ancak consumer migration
ve geriye uyumluluk planıyla kabul edilir. Henüz topic isimleri freeze edilmedi.

## Fault / recovery kararları

R3 incelemesi sonrası spool önerisi: byte/age sınırında en eski tamamlanmış
kaydı atomik olarak çıkar; taşan tek frame'i kısmen yazma. Drop nedeni, sayısı ve
kapsadığı sequence aralığı kaydedilir. Restart sonrası sayaç kaybolup completeness
yeniden başarılı görünmez. Düşen kayıt varsa o run'ın G10 completeness'i eksiktir;
DB ACK ile spool teslim/çıkarma sırası KAN-38'de kesinleştirilir.

| Olay | Beklenen politika / kanıt |
|---|---|
| nft uygulaması başarısız | StateEvent karar olarak kaydolabilir; applied state güncellenmez. Hata gösterilir; başarı eventi uydurulmaz |
| Yanıt öncesi enforcer crash | Sonuç unknown kabul edilir, kernel readback ile uzlaştırılır; kör tekrar veya yeni sonsuz lease yok |
| Runtime/enforcer crash | Kernel timed set, son lease sonunda kural eşleşmesini sona erdirir; release için çalışan Python timer gerekmez |
| Restart | Binding/policy/artifact uyumu ve kernel lease'ler okunur; stale kimlikle blok yeniden kurulmaz; uzlaştırma kaydı oluşturulur |
| Capture stale/drop/overflow | Etkilenen pencere yeni karantina kararında kullanılmaz; seri kesilir. Attack evasion/kaçış maliyeti ayrıca raporlanır |
| Model uyumsuz/bozuk | İnference başlatılmaz; otomatik yeni blok yok; health hatası ve release yolu kullanılabilir kalır |
| MQTT/Postgres/Grafana kapalı | Core containment sürer; bounded spool/drop sayacı. Telemetry completeness ayrı başarısız olabilir |
| Aynı karar tekrar gelir | İdempotent işlem; yeni expiry ile yeniden başlatılmaz |
| Lease biter / manual release | Egress açılır; normal policy durumu enfeksiyonsuzluk iddiası değildir; geçmiş incident korunur |

Önerilen hata tercihi kullanılabilirlik lehine sınırlı fail-open'dır. Bu bütün
evlere veya güvenlik-kritik IoT cihazlarına uygunluk iddiası değildir. Bilerek capture
kaybı yaratan saldırgan otomatik korumayı azaltabilir; bounded queue ve sağlık metriği
bu saldırı yüzeyini görünür kılar, tek başına çözmez. Farklı tercihler ayrı threat model ister.

## Kabul için gereken deneyler

1. Gerçek modelle G8: baseline/sink stop/release; önceden kurulmuş TCP ve UDP;
   drop öncesi capture; flow offload yok; namespace/host izolasyonu.
2. Apply öncesi/sonrası crash, runtime kill, kernel timeout, double request,
   değiştirilmiş binding, restart readback ve manual release.
3. Capture loss, stale/gap/empty window, kuyruk taşması ve clock-step testleri;
   NORMAL sınıfı ile observation unavailable ayrımı.
4. MQTT down/full spool/DB retry/duplicate/out-of-order: G8 etkilenmez; G10
   completeness, event correlation ve applied-state doğruluğu ayrı sonuç verir.
5. Freeze edilmiş v1 için regression; yeni envelope rejection ve migration testleri.

## Alternatifler

- StateEvent'i başarı saymak: yanlış pozitif uygulama kanıtı; reddedildi.
- Her şeyi v1 reason string'ine koymak: gizli şema ve uyumsuz consumer; reddedildi.
- Tüm gateway'i root model süreci yapmak: yetki alanı gereksiz geniş; önerilmiyor.
- Sadece user-space timer: süreç çökünce erişim kurtarma belirsiz; önerilmiyor.
- LLM veya telemetry tarafından doğrudan kural üretmek: deneyin kontrolünü ve
  deterministik karar yetkisini bozuyor; kapsam dışı.

## Ekip review listesi

- [x] R1: health/feature uygunluğu, invalid pencere ve model bağlamı (PR #4, 11 Eylül; tasarım yönü kabulü).
- [ ] R2: karar/uygulama ayrımı, TTL/episode sınırı, restart, namespace yetkisi.
- [ ] R3: envelope/topic migration, correlation/order, spool/DB dedup ve UI.
- [ ] Lead: somut policy parametreleri ve minimum G8/G10 kabul matrisi.

İmzalar bu doküman yazıldığı için doldurulmaz. KAN-63 ekip incelemesini izler;
mevcut kartlara önerilen kabul ölçütleri eklendi. Takvim ve sahipler korunur.
Gabriel’in KAN-38 UDS/framing ADR’siyle birlikte kayıt/topic migration kararı alınır.

12 Eylül inceleme yanıtları: [karar ve takip kaydı](../architecture/REVIEW_RESOLUTION_2026-09-12.md).
R1/R3 tasarım incelemesi yeni wire formatının onayı değildir; ADR PROPOSED kalır.
