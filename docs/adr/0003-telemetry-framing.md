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
- Socket `0600` olarak **umask ile yaratılır**. Önce bind edip sonra `chmod`
  yapmak, socket'in kısa bir süre herkese açık kaldığı bir pencere bırakır.
- Var olan yol bir socket değilse **silinmez**; adapter başlamayı reddeder.
  Bayat bir socket dosyası kaldırılır, gerçek bir dosya asla.
- **Peer credentials yalnız Linux'ta vardır.** Platform matrisi hosted CI'da
  ölçüldü (12 Eylül 2026):

  | Platform | `AF_UNIX` | `SO_PEERCRED` | Sonuç |
  |---|---|---|---|
  | Linux | var | var | Socket bağlanır, peer doğrulanır, `VERIFIED` |
  | macOS | var | **yok** | Socket bağlanır, peer **tanımlanamaz**, `UNAVAILABLE` |
  | Windows | **yok** | yok | Socket hiç bağlanamaz |

  macOS `LOCAL_PEERCRED`/`getpeereid` kullanır; `SO_PEERCRED` sunmaz. Yani
  bağlantı hizmet görürken peer kimliksiz kalır. Bu bilinçli olarak
  raporlanır: **yalnız Linux koşusu peer-verified diye yazılabilir.**
- Linux'ta `SO_PEERCRED` ile uid/gid doğrulanır.
  Windows'ta bu kontrol yapılamaz. **Düzeltme (12 Eylül 2026):** bu ADR daha
  önce "Windows `AF_UNIX` destekler" diyordu. İşletim sistemi için doğru, ama
  bizim yorumlayıcımız için değil: Windows üzerinde CPython `socket.AF_UNIX`
  sembolünü hiç sunmuyor (3.14.7 üzerinde ölçüldü). Yani socket yarısı
  geliştirme makinesinde **hiç çalıştırılamaz**, yalnız Linux'ta koşar.
- Bu yüzden adapter ikiye ayrılmıştır: socket gerektirmeyen **stream yarısı**
  (framing, decode, sink'e devir) her platformda test edilir; **socket yarısı**
  (bind, izin, peer credentials) Linux'a işaretlidir ve orada atlanan test
  "geçti" sayılmaz.
- `peer_verification` alanı yalnız kimlik bilgileri gerçekten okunup
  doğrulandığında `VERIFIED` olur; aksi halde `UNAVAILABLE`. `UNAVAILABLE`,
  `VERIFIED`'ın hafif hâli değildir: peer hakkında hiçbir iddia kurulamaz.
  `require_peer_credentials=True` iken platform destek vermiyorsa adapter
  **sesli biçimde başlamayı reddeder**.
- Docker lab ile socket görünürlüğü ayrı mount ve izin tasarımıdır; KAN-50 kapsamı.

#### 2.1 UDS mesaj gövdesi

Gövde, bölüm 1'deki canonical kodlamayla yazılmış bir **0.1.0 StateEvent
dokümanıdır** ve yalnız şu alanları taşır: `device_id`, `previous_state`,
`new_state`, `reason`, `timestamp`, `expires_at`.

- `event_id`, `run_id`, producer/boot/sequence ve envelope **host tarafında**
  atanır. Gateway'in gönderdiği hiçbir şey kimlik taşıdığı varsayımıyla
  kullanılmaz.
- **Bilinmeyen alan reddedilir, yok sayılmaz.** Fazladan bir anahtar,
  producer'ın bu consumer'ın review edilmediği bir sözleşmeyi konuştuğu
  anlamına gelir; sessizce atmak semantik değişikliğin fark edilmeden
  girmesinin yoludur.
- Eksik alan, tanınmayan enum değeri ve sözleşmeye uymayan değer de reddedilir.

#### 2.2 İki hata sınıfı ayrı tutulur

| Sınıf | Örnek | Davranış |
|---|---|---|
| **Framing** | Aşırı büyük uzunluk bildirimi, kesik gövde | Çerçeve sınırı kaybolmuştur; sonraki çerçevenin nerede başladığı bilinemez. **Bağlantı kapatılır.** Okumaya devam etmek tahmin yürütmek olur. |
| **İçerik** | JSON olmayan gövde, geçersiz StateEvent | Framing sağlamdır. Çerçeve sayılır ve reddedilir, **bağlantı açık kalır**; bir producer'ın tek bozuk mesajı arkasındakileri düşürmek için gerekçe değildir. |

Her reddin kendi sayacı vardır. Sink kuyruğu taşarsa bu da sınırda ayrıca
sayılır: okumaya devam eden bir alıcı, bir şeyin teslim edildiğinin kanıtı
değildir.

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

#### 7.2 Gerçek transport ve bekleyen bağımlılık (R2 notu)

**12 Eylül R2 uygulama güncellemesi:** aşağıdaki bekleyen bağımlılık notu
tarihseldir. `paho-mqtt==2.1.0` hem core hem ML input/hash lock'a eklendi.
`telemetry.mqtt.PahoTransport` worker tarafında mesajın `MQTTMessageInfo`
tamamlanmasını bekler; yalnız gerçek PUBACK `ACKED`, timeout `QUEUED` olur.
MQTT 3.1.1, QoS1 ve retain=false zorunludur. Client sahibi authentication,
bounded queue ve network-loop yaşam döngüsünü kurar; örnek `lab/telemetry_probe.py`.
Gerçek Linux Mosquitto teslim, disconnect/spool ve aynı bayt/kimlikle retry
doğrulandı: [kanıt](../KAN38_MQTT_VALIDATION.md). DB/G10 bundan ayrı kalır.
Bu kanıt ADR'nin R1 ekip onayını otomatik olarak sağlamaz; PROPOSED korunur.

**Kayda geçsin — 12 Eylül 2026.** KAN-38'in son eksiği gerçek StateEvent→MQTT
teslim kanıtıdır ve bunun için bir MQTT istemcisi gerekir. Şu an depoda yok:
`paho` kurulu değil, `requirements.lock` ve `requirements-ml.lock` içinde
geçmiyor.

**Lock'u R2 (Şükrü) üretir.** Kendi talebi üzerine buraya not düşülmüştür; R3
lock dosyalarına dokunmaz (CODEOWNERS: `*` → `@sicloid`).

Eklerken bilinmesi gerekenler:

- Paket `requirements-ml.lock` içine girmelidir. CI yalnız o dosyayı kurar
  (`pip install --require-hashes -r requirements-ml.lock`); `requirements.lock`
  hiç kurulmuyor, dolayısıyla oraya eklenen bir bağımlılık CI'da **import
  edilemez**.
- Hash doğrulamalı olmalı, mevcut `--generate-hashes` düzeniyle uyumlu.

Transport'un karşılaması gereken sözleşme bölüm 7.1'de tanımlıdır ve istemci
seçimi bunu **yapabilir olmalıdır**; ölçüt budur:

- İstemcinin yerel kuyruğa almayı başarıyla kabul etmesi `QUEUED` döndürür.
  Yayın çağrısının hatasız dönmesi tek başına `ACKED` **değildir**.
- `ACKED` yalnız o mesajın PUBACK'i alındıktan sonra döndürülür; istemci mesaj
  kimliği (mid) bazında yayın onayını raporlayabilmelidir.
- PUBACK bekleme worker thread'inde yapılır, producer'ın kritik yolunda asla;
  sınır `telemetry/handoff.py`'dir.
- İstemci mesajı kabul etmezse `TransportError` atılır ve publisher spool'lar.

Bu bağımlılık gelene kadar yalnız enjekte edilebilir sahte transport vardır ve o
**yalnız arıza davranışını** kanıtlar, teslimi değil. Hiçbir yerde teslim
iddiası yoktur.

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
5.1 Framing hatası bağlantıyı kapatır; içerik hatası kapatmaz ve arkadaki
   çerçeveler işlenmeye devam eder.
5.2 Bilinmeyen alan, eksik alan, tanınmayan enum ve sözleşme dışı değer
   reddedilir ve kendi sayacına yazılır.
5.3 Adapter kendi saatini okumaz; `clock` enjekte edilir ve test bunu doğrular.
5.4 Linux'a işaretli: socket `0600` yaratılır, socket olmayan bir yol silinmez,
   gerçek bir bağlantı üzerinden gelen çerçeve sink'e ulaşır ve
   `peer_verification` `VERIFIED` olur. Atlanan test geçmiş sayılmaz.
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

- [x] R1 Onur: kimlik ve sıra alanlarının ölçüm ile model bağlamına uyumu.
      13 Eylül 2026'da §5.1 ve §5.2 onaylandı. KAN-40 için iki şart (UNORDERED boot
      kaydının kalıcı olması, run_id ↔ boot_id eşlemesi) KAN-38 yorumunda.
- [ ] R2/Lead Şükrü: producer tarafında sequence/boot üretimi, kritik yolu
      bloklamama garantisi, socket izinleri ve lab görünürlüğü.
- [ ] R3 Gabriel: yazar.

İmzalar bu doküman yazıldığı için doldurulmaz; gerçek inceleme sonrası işaretlenir.
Bu ADR onaylanana kadar `telemetry/` altında yalnız bu sözleşmeye uyan kod yazılır
ve `0.1.0` wire sözleşmesi genişletilmez.
