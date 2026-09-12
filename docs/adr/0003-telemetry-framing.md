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

- Topic: **`omniguard/state/v2/<device_id>`**
- `v2` topic sürümüdür ve bölüm 5.1'deki sarmalayıcı envelope'u taşır.
  **`omniguard/state/v1/` olduğu yerde durur**; anlamı değişmez, eski consumer
  bozulmaz. ADR-0002'nin yeni kayıt türleri onaylanırsa kendi topic'lerini alır
  (`omniguard/enforcement/v1/...`).
- `device_id` karakter kuralı: `[A-Za-z0-9._-]{1,64}`. `/`, `+`, `#` ve boşluk
  yasaktır; topic yapısını veya wildcard semantiğini bozarlar. Uymayan
  `device_id` **publish edilmez**, hata sayacı artar ve olay spool'a alınmaz.
- **QoS 1**, `retain=false`. Bu bir olay akışıdır, anlık durum aynası değildir;
  retain edilmiş bir StateEvent yeni abonelere bayat durumu gerçekmiş gibi
  gösterirdi.
- Mevcut ACL (`topic readwrite omniguard/#`) bu şemayı zaten kapsar ve değişmez.

#### 5.1 Sarmalayıcı taşıma envelope'u

`event_id` bir UUID5'tir: retry'da sabit kalır, ama **opaktır**. Consumer ondan
producer, boot veya sequence bilgisini geri çıkaramaz. Yalnız 0.1.0
`TelemetryPayload` yayınlandığında ADR-0002'nin "eski event yeni durumu geri
alamaz" kuralı uygulanamaz, çünkü wire'da hangi olayın daha eski olduğunu söyleyen
hiçbir şey yoktur.

Çözüm 0.1.0'a alan eklemek **değildir**. ADR-0002 bunu açıkça yasaklıyor ve
şunu öneriyor: *"event türü başına ayrı versioned envelope/topic; eski state
topic'i korunur."* Uygulanan tam olarak budur:

```json
{
  "envelope_version": "1",
  "producer": {"producer_id": "...", "boot_id": "...", "boot_started_at": 0.0},
  "sequence": 7,
  "payload": { ... 0.1.0 TelemetryPayload, harfi harfine ... }
}
```

- `payload` **aynen** nested edilir; 0.1.0 genişletilmez, tek bir alanı değişmez.
- Envelope kendi sürümünü taşır ve `v2` topic'ine gider. Bilinmeyen
  `envelope_version` **reddedilir**; tahmin edilerek okunmaz.
- Eksik alan da reddedilir. Bir consumer'ın review edilmediği bir sözleşmeyi
  sessizce yanlış okuması böyle başlar.

#### 5.2 Sıralama ve UTC saat politikası

Sıralama anahtarı: **`(boot_started_at, boot_id, sequence)`**.

- `sequence` her boot'ta 1'e döndüğü için tek başına boot'lar arası
  karşılaştırılamaz; `boot_started_at` öne geçer. ADR-0002: *"Sequence aynı
  producer boot/run kapsamında sıralanır; restart sonrasında eski sıra yeni
  boot'a karıştırılmaz."*
- `boot_id` **eşit** `boot_started_at` taşıyan iki boot'u ayırır. Bu, sıralamayı
  total ve her consumer'da aynı yapar; hangi boot'un gerçekten önce başladığına
  dair bir **iddia değildir**.
- `boot_started_at` bir UTC duvar saatidir ve o saatin zayıflıklarını miras alır.
  Aynı producer için daha önce görülmüş bir boot'tan **küçük veya eşit** başlangıç
  zamanı sunan yeni bir boot, saat geri gitmesi, kaba saat veya geri yüklenmiş
  yedek demektir. `BootLedger` bunu `UNORDERED` olarak **raporlar**; olgu diye
  geçiştirmez. Bu durumda ne yapılacağı KAN-40 kararıdır.
- Sıralama kapsamı boot'tur, `run_id` değil: `run_id` bir ölçüm kapsamıdır,
  süreç ömrü değil. `run_id` payload içinde aynen taşınmaya devam eder.

### 6. Sınırlı spool

- Konum konfigürasyondan gelir; repoya veya `platform/.secrets` altına yazılmaz.
- Limitler: `max_bytes` ve `max_age_seconds`.
- Dolduğunda **oldest-first** eviction. Yazma atomiktir (geçici dosya ve rename),
  yarım kayıt bırakmaz.
- Kalıcı sayaçlar: düşen olay sayısı, düşme nedeni (bytes veya age) ve **atılan
  sequence aralığı**. Sayaçlar süreç yeniden başlasa da korunur.

#### 6.1 Eviction bir transaction'dır

Silme ile kaybın kaydı **ayrılamaz**. Önce silip sonra sayaç yazmak, ikisi
arasındaki bir crash'te hem olayı hem olayın kanıtını yok eder; dizin "bekleyen
yok, kayıp yok" diye okunur. Bu, kaybı ölçmesi gereken G10 için sessiz bir
başarı raporudur.

Sıra:

1. **Journal**: eviction niyeti (`eviction_id`, dosya adı, neden, scope, sequence,
   boyut) kalıcı olarak yazılır.
2. Entry silinir.
3. Sayaçlar uygulanır ve kalıcı yazılır (`last_applied_eviction = eviction_id`).
4. Journal silinir.

Dizin her açıldığında journal okunur ve yarım kalan iş tamamlanır. `eviction_id`
zaten `last_applied_eviction`'a eşit veya ondan küçükse iş bitmiştir; replay
**idempotent**'tir, çift saymaz.

`os.replace` artı dosya `fsync`'i kullanılır; Linux'ta dizin girdisi de
`fsync`lenir. Windows'ta dizin handle'ı yoktur, orada garanti dosya bazındadır.
Dayanıklılık iddiası Linux lab host'unda ölçülür.

#### 6.2 Kayıp kimliği boot'a bağlıdır

`sequence` her boot'ta 1'e döndüğü için, tek başına bir sequence aralığı hangi
boot'a ait olduğu bilinmeden **anlamsızdır**. Her entry bu yüzden bir scope
token'ı taşır (producer_id + boot_id digest'i), `scopes.json` token'ı üreten
kimliğe geri çevirir ve kayıp **scope başına** raporlanır. Token, entry ona
referans vermeden önce kalıcı yazılır; aksi halde crash sonrası atılan bir
entry'nin üreticisi adlandırılamaz.
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

#### 7.1 Transport sözleşmesi

`broker_ack` üretilebilmesi için transport'un ne onayladığını **açıkça** söylemesi
gerekir. `Transport.publish` bu yüzden `None` değil, bir `Acknowledgement` döndürür:

| Değer | Anlamı | `broker_ack` |
|---|---|---|
| `QUEUED` | İstemci baytları aldı; broker henüz cevap vermedi. | `false` |
| `ACKED` | Bu mesaj için PUBACK alındı (QoS1). | `true` |

Kurallar:

- Dönüş değeri `Acknowledgement` değilse `TransportContractError` atılır. Eksik
  dönüş değeri teslim sayılmaz; bu bir bağlama hatasıdır, runtime arızası değil.
- `QUEUED` durumunda spool kaydı **silinmez** ve `drain` o kaydı bırakmaz. Yerel
  kuyruk, mesajın bu host'tan çıktığının kanıtı değildir.
- Bunun ürettiği tekrar QoS1'in beklenen davranışıdır ve bölüm 8'deki `event_id`
  dedup'ı tarafından temizlenir. Yeniden gönderilen baytlar değişmediği için
  kimlik de değişmez.
- PUBACK beklemek **worker'ın işidir**; producer'ın kritik yolunda beklenmez.
- Ne onaylanan ne de saklanabilen olay `dropped` olarak raporlanır ve sayaca
  yazılır. Kayıp, diğer tüm alanların boş olmasından **çıkarsanmaz**.

### 8. Consumer dedup ilkesi

`event_id` üzerinde UNIQUE constraint ve `INSERT ... ON CONFLICT DO NOTHING`.
Çakışma bir hata değil, QoS1'in beklenen davranışıdır; sayaçla raporlanır.
Şema ve migration detayı KAN-39, consumer uygulaması KAN-40 kapsamındadır.

### 9. Kritik yol izolasyonu

ADR-0002'nin "telemetry loss cannot block enforcement or release" değişmezi
**yapısal** olarak uygulanır, dokümanla değil.

`TelemetryPublisher` transport'a ve dosya sistemine konuşur; ikisi de takılabilir.
Bu yüzden publisher **worker tarafı koddur ve bloklamama sözü vermez**. Sınır
`telemetry/handoff.py` içindeki `TelemetryHandoff`'tadır:

- Producer yalnız `submit()` çağırır: sınırlı ve bloklamayan bir `put_nowait`,
  bir sayaç güncellemesi, dönüş. Producer thread'inde **ne broker ne disk** işi
  yapılır.
- Transport ve spool kuyruğun öbür tarafındaki worker'a aittir.
- Kuyruk **bilinçli olarak sınırlıdır**. Sınırsız kuyruk, broker kesintisini
  sınırsız bellek büyümesine çevirir; host'u daha yavaş kaybetmenin yoludur.
  Kuyruk doluyken olay sınırda düşer ve `OVERFLOWED` döner: kayıp gecikme olarak
  gizlenmez, sonuç olarak raporlanır.
- Worker hiçbir telemetri hatasını dışarı sızdırmaz. Takılmış transport yalnız
  worker'ı tutar; publisher'dan gelen istisna (disk hataları dahil) `worker_failures`
  ve `last_failure` olarak kaydedilir, worker çalışmaya devam eder.
- `stop()` takılmış bir worker'ı durduramadığında **False döner**. Temiz durduğu
  iddia edilmez.

Sayaç sınırı: overflow handoff'ta, eviction spool'da sayılır. G10 completeness
ikisini birden okur; biri sıfır diye kayıp yok denmez.

## KAN-38 kapsamında test edilecekler

1. Aynı olayın yeniden teslimi aynı `event_id` değerini üretir.
2. Aynı `timestamp` taşıyan iki farklı olay farklı `event_id` alır.
3. Canonical serialization platformdan bağımsız olarak aynı baytları verir.
4. `MAX_FRAME` aşımı gövde okunmadan reddedilir ve sayaç artar.
5. Kısmi çerçeve hata verir; yarım kayıt işlenmez.
6. Spool byte ve age sınırında oldest-first eviction; drop sayısı, nedeni ve
   atılan sequence aralığı doğru kaydedilir.
6.1 Eviction'ın üç sınırında enjekte edilmiş crash: journal yazıldı ama silinmedi,
   silindi ama sayaç yazılmadı, sayaç yazıldı ama journal temizlenmedi. Üçünde de
   dizin yeniden açıldığında kayıp **kayıtlıdır** ve replay çift saymaz.
6.2 İki farklı boot'un kaybı ayrı ayrı raporlanır; sequence aralığı boot'suz
   sunulmaz.
7. Spool yazımı öncesi **enjekte edilmiş** crash: dizin yeniden açıldığında kayıt
   yok ve kayıp sayaca da yazılmamıştır; yeniden başlayan producer aynı olayı
   farklı kimlikle üretir. Bu testin amacı sınırı **belgelemektir**; geçmesi
   sorunun çözüldüğü anlamına gelmez. Fault enjekte etmeyen bir test bu maddeyi
   karşılamaz.
7.1 0.1.0 payload envelope içinde **harfi harfine** taşınır; tek alanı değişmez.
7.2 Bilinmeyen `envelope_version` ve eksik alan reddedilir.
7.3 Sıralama **serialize edildikten sonra ve restart sonrasında** doğrulanır:
   wire'dan okunan envelope'lar karıştırılıp sıralandığında eski boot'un
   sequence 2'si yeni boot'un sequence 1'inden önce gelir.
7.4 Eşit `boot_started_at` deterministik olarak ayrılır; saat geri gitmesi ve
   eşit zaman `UNORDERED` olarak raporlanır.
8. Kural dışı `device_id` publish edilmez.
9. Broker kapalıyken publish enforcement yolunu bloklamaz.
9.1 Transport çağrısı içinde takılıyken `submit()` **anında** döner; kuyruk dolunca
   `OVERFLOWED` verir ve sayaç artar.
9.2 Yazmaları başarısız olan disk worker'ın içinde kalır: `submit()` istisna
   atmaz, hata `worker_failures`/`last_failure` olarak görünür. Aynı publisher
   doğrudan çağrıldığında istisnanın çağırana ulaştığı da test edilir; sınırın
   nerede olduğu böylece belgelenir.
9.3 Durdurulmuş handoff'a gönderim `REFUSED` döner, sessizce düşmez.
10. Yalnız kuyruğa alan transport (`QUEUED`) teslim sayılmaz: `broker_ack` false
    kalır, spool kaydı durur ve `drain` onu bırakmaz.
11. `Acknowledgement` döndürmeyen transport `TransportContractError` verir.
12. Ne onaylanan ne saklanabilen olay `dropped` olarak raporlanır.
13. Yukarıdakiler enjekte edilebilir sahte transport ile koşar. Gerçek broker ve
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
