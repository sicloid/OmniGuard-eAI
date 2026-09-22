# ADR-0004 — Eğitim ve değerlendirme veri kaynağı

Tarih: 2026-09-14. Durum: **PROPOSED**. Yazar: Onur/R1.
İnceleme: R2/Lead Şükrü, R3 Gabriel. KAN-13 kapanışının istediği veri kaynağı
kararının kaydıdır. Bu ADR kabul edilene kadar [G1 tercihi](../G1_REVIEW.md)
("CICIoT2023 primary, IoT-23 secondary") resmî olarak geçerli kalır; hiçbir kod
veya rapor bu ADR'yi onaylanmış varsaymaz.

**14 Eylül 2026 inceleme durumu:** Şükrü (Lead/R2) PR #26 yorumunda IoT-23'ün birincil
geliştirme/eğitim kaynağı olması **yönünü** destekledi. Bu destek ADR'nin bütününü
kabul etmez. UNSW-IoTraffic'in indirilmesine/benimsenmesine, ortak yön semantiğine
ve manifest incelemesine onay vermez. Aynı incelemenin istediği düzeltmeler
Karar 2, 4 ve 7'ye işlendi.

## Problem

G1'de CICIoT2023 birincil, IoT-23 ikincil kaynak seçildi. İki gözlem bu seçimi
sorguluyor:

1. **CICIoT2023 erişilemiyor ve topolojisi denetlenmedi.** İndirme sunucusu
   `cicresearch.ca` TLS bağlantısını kapatıyor: 11-12 Eylül'de terminal, sandbox dışı
   ve tarayıcıdan, 14 Eylül 10:28 UTC'de yeniden denendi
   (`curl: (35) SSL_ERROR_SYSCALL`). UNB saldırganların ağdaki IoT cihazları olduğunu ve
   yine IoT cihazlarını hedeflediğini yazıyor. Bu, ev gateway'inde trafiğin LOCAL
   kalabileceğine dair bir **topoloji riskidir**; her capture'ın LOCAL olduğunu
   kanıtlamaz. Capture noktası, alt ağlar, yön ve etiketler denetlenmeden bir şey
   söylenemez.
2. **IoT-23 EGRESS ağırlıklı, ama benign tarafı dar.** Altı capture
   [denetlendi](../../data/DATASET_AUDIT.md); üç malware capture'ında IP
   paketlerinin %79-%94'ü EGRESS. Benign tarafta IoT-23 yalnız üç honeypot senaryosu
   yayınlıyor (Philips Hue, Amazon Echo, Somfy kapı kilidi). KAN-18 gerçek
   baseline'ında pencere FPR'si, eğitimde hangi benign capture'ın olduğuna göre
   0,0001 ile 0,80 arasında değişti (`docs/KAN18_BASELINE.md`).

Veri kaynağı değişikliği sessiz bir kod değişikliği olmamalı
([REVIEW_RESOLUTION, R1 kararları](../architecture/REVIEW_RESOLUTION_2026-09-12.md));
bu ADR onu kaydeder.

## Kapsam

Kapsamda: pencerelerin hangi capture'lardan geleceği, lisans ve atıf, EGRESS yön
semantiğinin veri tarafı, pencere etiket kuralı, geliştirme / holdout / dış test
ayrımı, benign kapsam açığının nasıl kapatılacağı ve bilinen karıştırıcılar.

Kapsam dışı: özellik kataloğunun içeriği (KAN-15), eşik/N/lease değerlerinin seçimi
(KAN-19, KAN-51), holdout katmanlarının yöntem ayrıntısı (KAN-21), canlı lab
capture'ı (G8).

## Önerilen kararlar

### 1. IoT-23 birincil geliştirme ve eğitim kaynağı olur

- Kaynak: Garcia, Parmisano, Erquiaga (2020), *IoT-23: A labeled dataset with
  malicious and benign IoT network traffic*, v1.0.0, Zenodo,
  doi:10.5281/zenodo.4743746. Lisans: **CC BY 4.0**. Atıf rapor ve sunumda zorunlu.
- Geliştirme verisi audit raporundaki altı senaryodur ve SHA-256 ile sabitlenir.
  Senaryo eklemek manifest değişikliğidir ve yeni pack hash'i üretir.
- Pack commit'lenmiş koddan yeniden üretilir (`data/samplepack`). Eğitim koşusu,
  pencere dosyası manifestteki `windows_sha256` ile eşleşmedikçe başlamaz.

### 2. CICIoT2023 yalnız koşullu dış aktarım testi olur

CICIoT2023 birincil kaynak olmaktan çıkar ve yalnız KAN-23 dış aktarım testi adayı
olarak kalır. **İç, dokunulmamış IoT-23 holdout'unun (Karar 7) yerine geçmez.**

Dış testten önce, erişim sağlanırsa:

1. Capture noktası, alt ağlar, saldırgan/hedef kimliği, yön ve etiket çözünürlüğü
   `data/audit.py` ile denetlenir ve raporlanır.
2. Özellikler ham PCAP'ten, geliştirme verisiyle **aynı extractor ve aynı katalog
   sürümüyle** çıkarılır; veri setinin hazır CSV özellikleri kullanılmaz.
3. LOCAL trafik EGRESS'e çevrilmez. Yalnız denetimin EGRESS gösterdiği capture'lar
   teste girer.

Dış test donmuş model, özellik, eşik politikası ve N ile bir kez skorlanır. CICIoT2023
sonuçlarına göre hiçbir parametre ayarlanmaz.

### 3. EGRESS özellikleri için ortak dışlama politikası

Multicast (`224.0.0.0/4`, `ff00::/8`), sınırlı broadcast (`255.255.255.255`) ve
link-local (`169.254.0.0/16`, `fe80::/10`) hedefler EGRESS sayılmaz. Ölçülen etki:
Honeypot-4-1'in 13.194 "EGRESS" paketinin 9.048'i SSDP multicast'ti; kural
uygulandıktan sonra 4.146 paket kaldı.

- Kural offline pack'te uygulanıyor. **R2 canlı kaynak adaptörü aynı kuralı
  uygulamadıkça** offline eğitim ile canlı çıkarım farklı pencereler görür. İki
  tarafın eşitlik testi KAN-15 kapanış şartıdır.
- Alt ağ broadcast'i (örn. `192.168.1.255`) bugünkü dışlama listesinde yok. LAN
  maskesine bağlı olduğu için R2 ile birlikte karar verilir.
- Bu ortak yön semantiği ayrı ve açık bir incelemedir; birincil kaynak yönünün
  desteklenmesi onu kapatmaz.

### 4. Pencere etiket kuralı

Manifestteki `label_rule` sabitlenir: pencerede Malicious akışla eşleşen en az bir
EGRESS paketi varsa **malicious**; yoksa eşleşmeyen veya çelişkili paket varsa
**unknown**; yalnız bütün paketler Benign akışla eşleşirse **benign**. Eşleştirme
yön duyarsız 5'li ve ±1 sn toleransla yapılır. Unknown pencereler eğitim ve
değerlendirmeden dışlanır, sayıları raporlanır (bugün 29). Unknown asla benign
sayılmaz.

Honeypot-7-1'in `conn.log.labeled` dosyası yayın sunucusunda yok. Bu yüzden 9.770
benign penceresinin etiketi ölçülmüş değil, **veri seti açıklamasından varsayılmıştır**
(`label_source: declared`).

**7-1'siz duyarlılık tekrarı bugün yapılamaz.** 7-1 çıkınca benign tarafta iki parent
grup kalır; `model/split.py` ve `model/holdout.py` sınıf başına üç grup ister. Kural:

- Tekrar, denetlenmiş en az bir ek benign parent grup gelene kadar (örn. Karar 5'teki
  kaynak onaylanırsa) veya iki grupla çalışan, **koşudan önce yazılıp sabitlenmiş**
  ayrı bir değerlendirme protokolüne kadar bekler.
- Grup şartını aşmak için tek bir parent capture asla bölünmez. Bu, 7-1'in
  `Somfy-0N` klasörlerinde kaçınılan sızıntının aynısı olurdu.
- O zamana kadar 7-1'i eğitim, doğrulama veya testte kullanan her sonuç (KAN-18,
  KAN-19, KAN-21 dahil) "7-1 etiketi varsayılmış" notuyla raporlanır.

### 5. Benign kapsam açığı: ikinci, yalnız-benign kaynak adayı

Ölçüm: IoT-23'ün benign tarafı üç cihaz ve 13.620 penceredir (2.831 / 1.019 /
9.770); bunun 9.770'i etiketi varsayılan 7-1'dir. Altı grupla her ayrıma sınıf
başına tek capture düşer ve KAN-18'deki FPR savrulması buradan gelir. Bağımsız bir
kaynak da aynı darlığı not ediyor: UNSW-IoTraffic tanımlayıcısı IoT-23 için
"fewer than 2,000 benign flows" diyor; bizim ölçümümüz 4-1'de 452, 5-1'de 1.374
akış.

**Karar:** Yalnız IoT-23 ile tespit kalitesi iddiası (G5) kurulmaz. İkinci kaynak
adayı **UNSW-IoTraffic**'tir: Wannigama, Sivanathan, Habibi Gharakheili (2025),
Dryad, doi:10.5061/dryad.w0vt4b94b. **İndirilmesi ve benimsenmesi ayrı, açık bir
ekip onayı ister;** birincil kaynak yönünün desteklenmesi bu onayı vermez.

- **Neden uygun:** Paketler ev tipi bir gateway'in (TP-Link Archer C7, OpenWrt)
  **LAN tarafında, NAT öncesinde** yakalanmış, cihazlar WAN üzerinden internete
  çıkıyor. Bu bizim capture noktamız ve EGRESS tanımımızla aynı geometridir.
  27 cihaz; MAC ile filtrelenmiş cihaz başına bir PCAP; 2016-09-22 ile 2017-04-13
  arası; ham başlıklar dahil 26,9 GB PCAP.
- **Lisans:** Dryad yayınlarını CC0 1.0 ile yayımlar; atıf yine yapılır.
- **Grup tanımı:** bir cihaz bir gruptur; aynı cihazın günleri ayrı grup sayılmaz.
- **Sınır:** "benign" ölçülmüş değil, varsayımdır. Veri setinde saldırı trafiği
  bildirilmiyor, ama etkileşim veya olay için ground-truth etiketi de yok. Pencereler
  `label_source: declared` olarak kaydedilir.

Onay gelirse, kabul için gereken ölçümler (`pcaps.zip` 13,92 GB):

1. `data/audit.py` ile her UNSW cihazının EGRESS payı ve multicast etkisi; cihaz
   eşlemesi MAC adresinden.
2. Cihazların holdout'a ayrılması, herhangi bir UNSW penceresi okunmadan önce yapılır
   (Karar 7).
3. **Kaynak kısayolu testi:** benign eğitim yalnız UNSW'nin geliştirme cihazlarından,
   benign değerlendirme IoT-23 honeypot'larında yapılır. IoT-23 benign FPR'si UNSW
   benign FPR'sinden belirgin yüksekse model davranışı değil "hangi laboratuvar"
   bilgisini öğreniyordur; sonuç böyle raporlanır.
4. FPR ve recall kaynak başına ve capture başına raporlanır; birleşik tek bir FPR
   verilmez.

### 6. Bilinen karıştırıcılar

Rapor ve sunumda açıkça yazılır:

- **Cihaz türü:** IoT-23 malware senaryoları Raspberry Pi üzerinde çalıştırılmış;
  benign senaryolar gerçek tüketici cihazlarından. Model "kötü davranış" yerine
  "Raspberry Pi mi" öğrenebilir. İkinci benign kaynak bunu çözmez; KAN-20 ablasyonu
  ve özelliklerde cihaz kimliği sızıntısı kontrolü ile ölçülür.
- **Dönem ve ortam:** UNSW 2016-17 Sidney, IoT-23 2018-19 Prag. DNS çözücü, bulut
  uç noktaları ve protokol payları ortamı ele verebilir.
- **Varsayılan etiketler:** 7-1 ve UNSW'nin tamamı.
- **Genelleme:** Sonuçlar bu capture'lar için geçerlidir; genel ev ağı iddiası
  kurulmaz.

### 7. Değerlendirme ayrımı

Dört veri rolü ayrı tutulur ve her sonuç hangi rolden geldiğini söyler.

**a. Geliştirme verisi — altı denetlenmiş capture.** Eğitim, doğrulama, eşik seçimi
(KAN-19), aile holdout katmanları (KAN-21), ablasyon (KAN-20) ve N taraması bu veride
yapılır. Eşik yalnız doğrulamada seçilir. KAN-18 bu captureların hepsini doğrulama,
KAN-21 hepsini bir katmanda test tarafında kullandı. Bu yüzden altı capture'ın
hiçbiri artık "dokunulmamış" değildir ve bunlardan çıkan her sonuç **geliştirme
sonucudur**.

**b. İç, dokunulmamış IoT-23 holdout'u — malware tarafı.** IoT-23'ün kullanılmayan 17
malware senaryosundan, bu ADR'de önceden sabitlenen kuralla seçilir. Seçim yalnız
yayımlanan meta veriye (aile, PCAP boyutu) dayanır, hiçbir model skoruna değil:

- Bir **görülmüş aile** capture'ı: Mirai'nin 34-1 dışındaki senaryolarından en küçük
  yayımlanmış PCAP.
- İki **görülmemiş aile** capture'ı: şu sıradaki ilk iki aileden, ailenin en küçük
  yayımlanmış PCAP'i: Torii, Okiru, Gagfyt, Kenjiro, IRCBot, Linux.Hajime,
  Hide and Seek, Trojan. İndirme ekibin veri limitini aşarsa sıradaki aileye geçilir.
  Linux.Mirai (7-1) Mirai ile ayrışmadığı için görülmemiş aile sayılmaz.
- Senaryo kimlikleri ve URL'ler indirmeden **önce** bir holdout manifestine commit'lenir;
  SHA-256'lar indirmeden hemen sonra aynı manifeste eklenir.

Holdout için **izin verilenler:** hash, `data/audit.py` yön/etiket denetimi ve donmuş
builder ile pack üretimi. **Yasak olanlar:** bu capture'larla eğitim, doğrulama, eşik,
N, lease veya özellik seçimi; ve dondurmadan önce herhangi bir model skoru üretmek.

Skorlamadan önce şunlar kaydedilip hash'lenir: `feature_schema_version`,
`model_sha256`, `model.meta.json` hash'i, eşik politikası dosyasının hash'i, N ve
lease değerleri, geliştirme pack'inin `windows_sha256`'i. Holdout **bir kez** skorlanır
ve sonuç ne olursa olsun raporlanır. Sonrasında ayar yapılırsa bu holdout "tüketilmiş"
sayılır; yeni bir iddia için yeni, dokunulmamış capture'lar gerekir.

**Kayıt durumu (21 Eylül 2026).** KAN-19'da dondurulan beş kalem kayıtlı; N ve lease
KAN-51'de ölçülüyor ve **henüz tamamlanmadı**:

| Kalem | Değer | Durum |
|---|---|---|
| `feature_schema_version` | `features-1` | Kayıtlı (KAN-15/16) |
| `model_sha256` | `d30725a9e913a5f1d4c652796e7a6a15dcd00cc482ef162f5a387fa18b57de6b` | Kayıtlı (KAN-19) |
| `model.meta.json` | `917504c156951eee6d4438409c4529ad309d90b67a6e53a0ed2a5040f0f200ad` | Kayıtlı (KAN-19) |
| `threshold.policy.json` | `4a9491b5ce0be6a5225ce8f0e0b4d72022e67a62ba38c6cf62aeb051acc7bcdb` (eşik 0,9798815486832) | Kayıtlı (KAN-19) |
| Geliştirme pack'i `windows_sha256` | `4b97fb954270a2727544724aa331d20354f9e10f6aa5d1bbbf62a5f3c40c6625` | Kayıtlı (KAN-14) |
| **N** | **2** | Lead'in geçici validation seçimi (20 Eylül, [PR #44'te birinci elden](https://github.com/sicloid/OmniGuard-eAI/pull/44)) |
| **lease** | — | **Onaylanmadı.** Düzeltilmiş KAN-51 sonucu review bekliyor |

İlk KAN-51 koşusu 30 saniyelik lease önermişti; R3 review'u bu sonucu taşıyan iki hata
buldu (kapsama, aralık örtüşmesi yerine toplam karşılaştırıyordu; lease süresi sessizlik
sırasında bitmiyordu). Lead bu nedenle 30 saniyelik öneriyi geri çekti. Nihai N/lease
çifti, düzeltilmiş sonuç review edildikten sonra Lead tarafından bu PR'da birinci
elden kaydedilecek. **O zamana kadar holdout mühürlü kalır.**

**c. İç holdout — benign tarafı: bugün yok.** IoT-23 yalnız üç benign senaryo yayınlıyor
ve üçü de geliştirme verisinde. Dokunulmamış benign FPR IoT-23'ten ölçülemez. İki yol
var, ikisi de ayrı onay ister:

- UNSW onaylanırsa: herhangi bir UNSW penceresi okunmadan önce cihazlar
  `sha256("adr-0004-holdout:" + cihaz_adı)` sırasına dizilir, ilk üçte biri (27'den 9
  cihaz) holdout'a ayrılır ve geliştirmede asla kullanılmaz.
- Veya G8 lab'ında önceden tanımlanmış bir benign capture protokolü.

O zamana kadar holdout raporu yalnız malware recall'unu verir ve "dokunulmamış benign
FPR: ölçülmedi" diye yazar. Enfekte capture içindeki benign pencerelerin oranı benign
cihaz FPR'si yerine kullanılmaz.

**d. Dış aktarım testi — CICIoT2023 (KAN-23).** Karar 2'deki koşullarla, iç holdout'tan
ayrı raporlanır; yerine geçmez.

## Değerlendirilen alternatifler

- **CICIoT2023 birincil kalsın:** erişilemiyor ve açıklaması LOCAL topoloji riski
  taşıyor. Reddedildi; koşullu dış test adayı olarak kaldı (Karar 2).
- **CICIoT2023 iç test ayrımının yerine geçsin:** farklı topoloji ve etiket sürecinden
  gelen bir veri seti, iç genelleme ile dış aktarımı karıştırır. Reddedildi.
- **LOCAL saldırıları EGRESS'e dönüştüren lab-only replay:** mümkün, ama bir
  laboratuvar dönüşümüdür; manifestte beyan edilmeli ve doğal WAN genellemesi iddiası
  taşımaz. Kaynak erişilemediği için bugün uygulanamaz. Ertelendi.
- **Kendi cihazlarımızdan doğal gateway capture'ı:** benign için en gerçekçi kaynak,
  ama birkaç cihazla ve kısa süreyle sınırlı, kişisel trafik içerir. G8 lab ve
  KAN-51/52 canlı doğrulamasında kullanılır; bugün eğitim kaynağı değil.
- **7-1'siz tekrar için bir benign capture'ı zaman dilimlerine bölmek:** aynı cihazı
  eğitim ve teste taşır. Reddedildi (Karar 4).
- **Malware capture'larındaki Benign akışlar:** pack'te zaten var (3-1'de 4, 8-1'de
  1.036, 34-1'de 930 pencere), ama enfekte cihazın kendisinden geliyor ve grup
  ayrımı onları malware grubuyla birlikte tutuyor. Ayrı benign kapsamı sayılmaz.
- **CIC-YNU-IoTMal 2026:** benign kısmı LLM ile üretilmiş olarak açıklanıyor
  ([REVIEW_2026](../architecture/REVIEW_2026.md)). Benign kaynak olarak reddedildi.
- **Diğer yalnız-benign setler (YourThings, Mon(IoT)r):** denetlenmedi. UNSW
  seçildi, çünkü capture noktası ve cihaz başına PCAP yapısı tanımlayıcısında
  belgelenmiş.

## Onaylanırsa yapılacaklar

1. KAN-14: manifestteki `license` yer tutucusu CC BY 4.0 ve DOI ile değiştirilir;
   pack hash'i yenilenir.
2. R1: Karar 7b'deki kuralla holdout senaryoları seçilir, kimlikleri indirmeden önce
   manifeste commit'lenir; indirme, hash ve denetim yapılır, skorlama yapılmaz.
3. R2: canlı adaptörde EGRESS dışlama eşitliği ve alt ağ broadcast kararı (KAN-15).
4. UNSW-IoTraffic için ayrı ekip kararı. Onaylanırsa R1 cihaz holdout ayrımını (Karar
   7c) veri okunmadan yapar, sonra indirme, denetim ve kısayol testi.
5. `docs/G1_REVIEW.md` ve `docs/STATUS.md` kaynak satırları bu ADR'ye bağlanır.
6. KAN-57 metodoloji dokümanı değerlendirme ayrımı ve karıştırıcılar bölümlerini
   buradan alır.

## Kaynaklar

Erişim tarihi 2026-09-14.

- [IoT-23, Zenodo kaydı ve lisansı](https://zenodo.org/records/4743746)
- [IoT-23, Stratosphere Lab sayfası ve senaryo/aile tablosu](https://www.stratosphereips.org/datasets-iot23)
- [UNSW-IoTraffic, Dryad](https://datadryad.org/dataset/doi:10.5061/dryad.w0vt4b94b)
- [UNSW-IoTraffic tanımlayıcısı](https://www2.ee.unsw.edu.au/~hhabibi/pubs/jrnl/25unsw-iotraffic.pdf)
- [Dryad yayın ve CC0 politikası](https://datadryad.org/publication_policy)
- [UNB CICIoT2023](https://www.unb.ca/cic/datasets/iotdataset-2023.html)

## Ekip review

- [ ] R1 Onur: yazar.
- [ ] R2/Lead Şükrü: 14 Eylül'de birincil kaynak yönünü destekledi (PR #26 yorumu).
      Açık kalanlar: ADR'nin bütünü, değerlendirme ayrımı (Karar 7), EGRESS
      dışlamalarının canlı adaptörle eşitliği, UNSW indirmesi/benimsenmesi.
- [ ] R3 Gabriel: ExperimentManifest veri bölümünde kaynak, lisans, atıf ve holdout
      manifestinin taşınması.

İmzalar gerçek inceleme sonrası işaretlenir. Bu ADR onaylanana kadar veri
kaynağı değişikliği yapılmış sayılmaz; mevcut pack, KAN-18 ve KAN-21 sonuçları "IoT-23
önerisi altında geliştirme sonucu" olarak anılır.

### 14 Eylül — Karar 3 kapsamındaki R2/R3 inceleme düzeltmesi

PR #29, ortak dışlama kuralını normalizer ve pack için eşitler. Tüm multicast
özelliklerden politika gereği dışlanır; fiziksel link sınırı iddiası kurulmaz.
Alt ağ broadcast adresi yapılandırılmış LAN üyeliğiyle LOCAL olur; /31, /32 ve
IPv6 için broadcast türetilmez. features-1 offline değerleri değişmediğinden korunur.
KAN-33/G8 bu sınıflandırmadan bağımsız kaçış ölçer; eksik kapsam ölçülmedi olarak
raporlanır. Bu açıklama diğer ADR kararlarını veya UNSW indirmesini onaylamaz.
