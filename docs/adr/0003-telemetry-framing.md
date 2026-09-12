# ADR-0003 — UDS çerçeveleme, telemetri kimliği ve MQTT topic sözleşmesi

Tarih: 2026-09-12. Durum: **PROPOSED**. Yazar: Gabriel/R3.
İnceleme: R1 Onur, R2/Lead Şükrü. [ADR-0002](0002-bounded-containment.md) ile
birlikte incelenir. Mevcut `0.1.0` wire sözleşmesi genişletilmez; bu ADR yalnız
mevcut `TelemetryPayload`'in nasil tasinacagini tanimlar.

## Problem

`StateEvent` gateway'de üretiliyor; UDS → MQTT → PostgreSQL → Grafana zinciri
R3'te. Bugün çerçeveleme, olay kimliği, sıralama, spool davranışı ve ACK'in ne
anlattığı tanımsız. Tanımsız bırakılırsa dört somut arıza çıkar:

1. QoS1 duplicate teslimi veritabanında çift satıra dönüşür.
2. Yeniden başlatma sonrası eski bir olay yeni cihaz durumunu geri alabilir.
3. Sınırsız kuyruk veya spool belleği ya da diski tüketir.
4. Telemetri yazımı kritik yolu bekletir ve enforcement'i geciktirir.

## Kapsam

Kapsamda: UDS çerçeveleme, canonical serialization, `event_id` türetimi,
producer/boot/sequence kimliği, MQTT topic/QoS/retain, sınırlı spool ve eviction,
ACK anlamı, consumer dedup ilkesi.

Kapsam dışı: ADR-0002'nin önerdiği yeni kayıt türleri (ObservationHealth,
EnforcementResult, DetectionRecord, HealthRecord). Onlar ayrı ekip onayı ve sürüm
migration'i ister. Veritabanı şeması KAN-39, consumer KAN-40, dashboard KAN-41.

## Kararlar

### 1. Canonical serialization

`TelemetryPayload.to_dict()` çıktısı tek bir biçimde kodlanır:
`sort_keys=True`, `separators=(",", ":")`, `ensure_ascii=False`,
`allow_nan=False`, UTF-8. Aynı biçim hem wire'da hem `event_id` türetiminde
kullanılır; iki yerde farklı kodlama kullanmak kimliği platforma bağımlı yapardı.

### 2. UDS çerçeveleme

- Her mesaj: **4 bayt big-endian işaretsiz uzunluk + gövde**.
- `MAX_FRAME = 65536` bayt. Bildirilen uzunluk bunu aşarsa gövde **okunmadan**
  reddedilir, bağlantı kapatılır, sayaç artar. Sınır kontrolü veri okunmadan
  yapıldığı için uydurma bir uzunluk bellek ayırtamaz.
- Eksik veya kısmi çerçeve hatadır. Yarım bir kayıt asla işlenmez.
- Yazma timeout'ludur ve bloklamaz; timeout drop sayacına yazılır.
- Socket dosyası `0600`, yalnız sahibine açık.
- **Peer credentials:** Linux'ta `SO_PEERCRED` ile uid/gid doğrulanır.
  Windows `AF_UNIX` destekler ama `SO_PEERCRED` sağlamaz; bu kontrol geliştirme
  makinesinde (Windows) çalıştırılamaz ve testi Linux'a işaretlidir. Bilinen
  sınırlama olarak kayda geçer, "doğrulandı" diye raporlanmaz.
- Docker lab ile socket görünürlüğü ayrı mount ve izin tasarımıdır; KAN-50 kapsamı.

### 3. Producer kimliği ve sıralama

| Alan | Kaynak | Ömür |
|---|---|---|
| `producer_id` | konfigürasyon | kurulum boyunca sabit |
| `boot_id` | süreç başlangıcında UUID4 | tek çalışma |
| `sequence` | 1'den artan tamsayı | boot içinde, atlamasız |
| `boot_started_at` | süreç başlangıcı UTC Unix saniye | tek çalışma |

`(producer_id, boot_id, sequence)` bir olayı global olarak tanımlar. Yeniden
başlatmada `boot_id` değişir ve `sequence` 1'e döner; eski sıra yeni boot'a
karışmaz.

`boot_started_at` gereklidir çünkü **sequence tek başına boot'lar arasında
karşılaştırılamaz**: iki farklı boot'un 5 numaralı olayları arasında sıra
kurulamaz. Consumer sırayı `(boot_started_at, sequence)` ile belirler ve aynı
cihaz için daha eski bir olayın daha yeni durumu ezmesine izin vermez.

### 4. `event_id` türetimi

```
event_id = uuid5(
    OMNIGUARD_TELEMETRY_NAMESPACE,
    canonical({producer_id, boot_id, sequence, device_id,
               previous_state, new_state, timestamp, expires_at, reason}),
)
```

- **Retry'da değişmez:** aynı girdiler her zaman aynı kimliği verir. `SCHEMA.md`
  içindeki "producer must preserve event_id across retries" şartı böyle karşılanır.
- **Aynı timestamp'li iki farklı olay çakışmaz:** `sequence` ayırır.
- Retry anında yeni saat okuması veya yeni rastgele kimlik üretmek yasaktır.
- `OMNIGUARD_TELEMETRY_NAMESPACE` kodda sabit bir UUID'dir. Değiştirilmesi bütün
  geçmiş kimlikleri değiştirir ve ayrı bir ADR gerektirir.

**Kabul edilen sınır:** `sequence` spool'a yazılmadan önce süreç çökerse, yeniden
üretilen olay yeni bir `sequence` ve dolayısıyla yeni bir `event_id` alır; bu
veritabanında duplicate demektir. Bu pencere kapatılmıyor, **ölçülüyor**: KAN-38
testi crash'i tam bu noktada tetikler, KAN-50 G10 sonucunda duplicate sayısı
raporlanır. "Exactly once" iddia edilmez.

### 5. MQTT topic, QoS ve retain

- Topic: **`omniguard/state/v1/<device_id>`**
- `v1` topic sürümüdür. ADR-0002'nin yeni kayıt türleri onaylanırsa kendi
  topic'lerini alır (`omniguard/enforcement/v1/...`); mevcut state topic'i
  değişmez ve eski consumer bozulmaz.
- `device_id` karakter kuralı: `[A-Za-z0-9._-]{1,64}`. `/`, `+`, `#` ve boşluk
  yasaktır; topic yapısını veya wildcard semantiğini bozarlar. Uymayan
  `device_id` **publish edilmez**, hata sayacı artar ve olay spool'a alınmaz.
- **QoS 1**, `retain=false`. Bu bir olay akışıdır, anlık durum aynası değildir;
  retain edilmiş bir StateEvent yeni abonelere bayat durumu gerçekmiş gibi
  gösterirdi.
- Mevcut ACL (`topic readwrite omniguard/#`) bu şemayı zaten kapsar ve değişmez.

### 6. Sınırlı spool

- Konum konfigürasyondan gelir; repoya veya `platform/.secrets` altına yazılmaz.
- Limitler: `max_bytes` ve `max_age_seconds`.
- Dolduğunda **oldest-first** eviction. Yazma atomiktir (geçici dosya ve rename),
  yarım kayıt bırakmaz.
- Kalıcı sayaçlar: düşen olay sayısı, düşme nedeni (bytes veya age) ve **atılan
  sequence aralığı**. Sayaçlar süreç yeniden başlasa da korunur.
- Bu sayaçlar G10 completeness sonucuna doğrudan girer. Eksik kayıt "kayıp yok"
  diye sunulmaz; yeniden bağlanmak kaybın olmadığı anlamına gelmez.
- **Enforcement asla beklemez.** Kuyruk veya spool doluysa olay düşer ve sayaç
  artar; publish yolu kritik yolu bloklamaz. ADR-0002'nin "telemetry loss cannot
  block enforcement or release" değişmezi budur.

### 7. ACK'in anlamı

İki ayrı olgu, asla tek alanda birleştirilmez:

| Olgu | Ne kanıtlar |
|---|---|
| `broker_ack` | MQTT PUBACK alındı (QoS1). Broker mesajı kabul etti. |
| `db_commit` | Consumer transaction'i commit etti. Kayıt kalıcı. |

Broker ACK'i veritabanı kaydını **garanti etmez**. G10 completeness ölçümü
`db_commit` üzerinden yapılır; `broker_ack` yalnız teslim yolunu gözlemlemek içindir.

### 8. Consumer dedup ilkesi

`event_id` üzerinde UNIQUE constraint ve `INSERT ... ON CONFLICT DO NOTHING`.
Çakışma bir hata değil, QoS1'in beklenen davranışıdır; sayaçla raporlanır.
Şema ve migration detayı KAN-39, consumer uygulaması KAN-40 kapsamındadır.

## KAN-38 kapsamında test edilecekler

1. Aynı olayın yeniden teslimi aynı `event_id` değerini üretir.
2. Aynı `timestamp` taşıyan iki farklı olay farklı `event_id` alır.
3. Canonical serialization platformdan bağımsız olarak aynı baytları verir.
4. `MAX_FRAME` aşımı gövde okunmadan reddedilir ve sayaç artar.
5. Kısmi çerçeve hata verir; yarım kayıt işlenmez.
6. Spool byte ve age sınırında oldest-first eviction; drop sayısı, nedeni ve
   atılan sequence aralığı doğru kaydedilir.
7. Spool yazımı öncesi crash yeniden teslimde duplicate üretir. Bu testin amacı
   sınırı **belgelemektir**; geçmesi sorunun çözüldüğü anlamına gelmez.
8. Kural dışı `device_id` publish edilmez.
9. Broker kapalıyken publish enforcement yolunu bloklamaz.
10. Yukarıdakiler enjekte edilebilir sahte transport ile koşar. Gerçek broker ve
    veritabanı teslim kanıtı ayrıdır, KAN-50'de Compose üzerinde alınır; unit
    test onun yerine geçmez.

## Değerlendirilen alternatifler

- **NDJSON çerçeveleme:** gözle okunması kolay, ama sınır kontrolü satır
  taraması gerektiriyor ve bounded frame garantisi zayıf. Reddedildi.
- **Tek topic (`omniguard/state/v1`):** basit, ama cihaz bazlı ACL ve seçici
  abonelik imkânsız hale geliyor. Reddedildi.
- **Rastgele UUID4 artı spool'da saklama:** spool yazımı öncesi crash'te yeni
  kimlik üretir, yani deterministik türetmeden kesinlikle daha kötü. Reddedildi.
- **QoS 2:** broker maliyeti yüksek ve uygulama seviyesinde dedup yine gerekli.
  Reddedildi.
- **Exactly-once teslim iddiası:** yapılmıyor. At-least-once artı idempotent kayıt.

## Ekip review

- [ ] R1 Onur: kimlik ve sıra alanlarının ölçüm ile model bağlamına uyumu.
- [ ] R2/Lead Şükrü: producer tarafında sequence/boot üretimi, kritik yolu
      bloklamama garantisi, socket izinleri ve lab görünürlüğü.
- [ ] R3 Gabriel: yazar.

İmzalar bu doküman yazıldığı için doldurulmaz; gerçek inceleme sonrası işaretlenir.
Bu ADR onaylanana kadar `telemetry/` altında yalnız bu sözleşmeye uyan kod yazılır
ve `0.1.0` wire sözleşmesi genişletilmez.
