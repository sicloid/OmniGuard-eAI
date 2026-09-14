# ADR-0004 — Eğitim ve değerlendirme veri kaynağı

Tarih: 2026-09-14. Durum: **PROPOSED**. Yazar: Onur/R1.
İnceleme: R2/Lead Şükrü, R3 Gabriel. KAN-13 kapanışının istediği veri kaynağı
kararının kaydıdır. Bu ADR kabul edilene kadar [G1 tercihi](../G1_REVIEW.md)
("CICIoT2023 primary, IoT-23 secondary") resmî olarak geçerli kalır; hiçbir kod
veya rapor bu ADR'yi onaylanmış varsaymaz.

## Problem

G1'de CICIoT2023 birincil, IoT-23 ikincil kaynak seçildi. İki ölçüm bu seçimi
sorguluyor:

1. **CICIoT2023 erişilemiyor ve tehdit modeline uymuyor olabilir.** İndirme
   sunucusu `cicresearch.ca` TLS bağlantısını kapatıyor: 11-12 Eylül'de terminal,
   sandbox dışı ve tarayıcıdan, 14 Eylül 10:28 UTC'de yeniden denendi
   (`curl: (35) SSL_ERROR_SYSCALL`). UNB saldırıların ağdaki IoT cihazlarından yine
   ağdaki IoT sistemlerine yapıldığını yazıyor; ev gateway'inde bu LOCAL trafiktir,
   extractor ise yalnız EGRESS okur. Bu ikinci nokta kaynağın açıklamasından
   çıkarımdır; capture denetlenemediği için ölçüm değildir.
2. **IoT-23 EGRESS ağırlıklı, ama benign tarafı dar.** Altı capture
   [denetlendi](../../data/DATASET_AUDIT.md); üç malware capture'ında IP
   paketlerinin %79-%94'ü EGRESS. Benign tarafta IoT-23 yalnız üç honeypot senaryosu
   yayınlıyor (Philips Hue, Amazon Echo, Somfy kapı kilidi). KAN-18 gerçek
   baseline'ında pencere FPR'si, eğitimde hangi benign capture'ın olduğuna göre
   0,0001 ile 0,80 arasında değişti
   ([PR #22](https://github.com/sicloid/OmniGuard-eAI/pull/22), `docs/KAN18_BASELINE.md`).

Veri kaynağı değişikliği sessiz bir kod değişikliği olmamalı
([REVIEW_RESOLUTION, R1 kararları](../architecture/REVIEW_RESOLUTION_2026-09-12.md));
bu ADR onu kaydeder.

## Kapsam

Kapsamda: pencerelerin hangi capture'lardan geleceği, lisans ve atıf, EGRESS yön
semantiğinin veri tarafı, pencere etiket kuralı, benign kapsam açığının nasıl
kapatılacağı ve bilinen karıştırıcılar.

Kapsam dışı: özellik kataloğunun içeriği (KAN-15), eşik/N/lease seçimi (KAN-19,
KAN-51), unseen-family holdout tasarımı (KAN-21), canlı lab capture'ı (G8).

## Önerilen kararlar

### 1. IoT-23 birincil kaynak olur

- Kaynak: Garcia, Parmisano, Erquiaga (2020), *IoT-23: A labeled dataset with
  malicious and benign IoT network traffic*, v1.0.0, Zenodo,
  doi:10.5281/zenodo.4743746. Lisans: **CC BY 4.0**. Atıf rapor ve sunumda zorunlu.
- Kullanılan capture'lar audit raporundaki altı senaryodur ve SHA-256 ile
  sabitlenir. Senaryo eklemek manifest değişikliğidir ve yeni pack hash'i üretir.
- Pack commit'lenmiş koddan yeniden üretilir (`data/samplepack`, PR #21). Eğitim
  koşusu, pencere dosyası manifestteki `windows_sha256` ile eşleşmedikçe başlamaz
  (PR #22).

### 2. CICIoT2023 birincil kaynak olmaktan çıkar

Aday olarak kalır. Erişim sağlanırsa aynı `data/audit.py` ile yön denetimi yapılır.
LOCAL ağırlığı doğrulanırsa yalnız KAN-23 aktarım deneyinde kullanılır; LOCAL
trafik EGRESS'e çevrilmez.

### 3. EGRESS, evden gerçekten çıkan trafiktir

Multicast (`224.0.0.0/4`, `ff00::/8`), sınırlı broadcast (`255.255.255.255`) ve
link-local (`169.254.0.0/16`, `fe80::/10`) hedefler EGRESS sayılmaz. Ölçülen etki:
Honeypot-4-1'in 13.194 "EGRESS" paketinin 9.048'i SSDP multicast'ti; kural
uygulandıktan sonra 4.146 paket kaldı.

- Kural offline pack'te uygulanıyor (PR #21). **R2 canlı kaynak adaptörü aynı kuralı
  uygulamadıkça** offline eğitim ile canlı çıkarım farklı pencereler görür. İki
  tarafın eşitlik testi KAN-15 kapanış şartıdır.
- Alt ağ broadcast'i (örn. `192.168.1.255`) bugünkü dışlama listesinde yok. LAN
  maskesine bağlı olduğu için R2 ile birlikte karar verilir.

### 4. Pencere etiket kuralı

Manifestteki `label_rule` sabitlenir: pencerede Malicious akışla eşleşen en az bir
EGRESS paketi varsa **malicious**; yoksa eşleşmeyen veya çelişkili paket varsa
**unknown**; yalnız bütün paketler Benign akışla eşleşirse **benign**. Eşleştirme
yön duyarsız 5'li ve ±1 sn toleransla yapılır. Unknown pencereler eğitim ve
değerlendirmeden dışlanır, sayıları raporlanır (bugün 29). Unknown asla benign
sayılmaz.

Honeypot-7-1'in `conn.log.labeled` dosyası yayın sunucusunda yok. Bu yüzden 9.770
benign penceresinin etiketi ölçülmüş değil, **veri seti açıklamasından varsayılmıştır**
(`label_source: declared`). Kural: 7-1'e dayanan her sonuç, 7-1'siz tekrarıyla
birlikte raporlanır.

### 5. Benign kapsam açığı: ikinci, yalnız-benign kaynak

Ölçüm: IoT-23'ün benign tarafı üç cihaz ve 13.620 penceredir (2.831 / 1.019 /
9.770); bunun 9.770'i etiketi varsayılan 7-1'dir. Altı grupla her ayrıma sınıf
başına tek capture düşer ve KAN-18'deki FPR savrulması buradan gelir. Bağımsız bir
kaynak da aynı darlığı not ediyor: UNSW-IoTraffic tanımlayıcısı IoT-23 için
"fewer than 2,000 benign flows" diyor; bizim ölçümümüz 4-1'de 452, 5-1'de 1.374
akış.

**Karar:** Yalnız IoT-23 ile tespit kalitesi iddiası (G5) kurulmaz. Önerilen ikinci
kaynak **UNSW-IoTraffic**'tir: Wannigama, Sivanathan, Habibi Gharakheili (2025),
Dryad, doi:10.5061/dryad.w0vt4b94b.

- **Neden uygun:** Paketler ev tipi bir gateway'in (TP-Link Archer C7, OpenWrt)
  **LAN tarafında, NAT öncesinde** yakalanmış, cihazlar WAN üzerinden internete
  çıkıyor. Bu bizim capture noktamız ve EGRESS tanımımızla aynı geometridir.
  27 cihaz; MAC ile filtrelenmiş cihaz başına bir PCAP; 2016-09-22 ile 2017-04-13
  arası; ham başlıklar dahil 26,9 GB PCAP.
- **Lisans:** Dryad yayınlarını CC0 1.0 ile yayımlar; atıf yine yapılır.
- **Grup tanımı:** bir cihaz bir gruptur. Aynı cihazın günlerini ayrı grup saymak,
  7-1'in `Somfy-0N` klasörlerinde kaçınılan sızıntının aynısıdır.
- **Sınır:** "benign" ölçülmüş değil, varsayımdır. Veri setinde saldırı trafiği
  bildirilmiyor, ama etkileşim veya olay için ground-truth etiketi de yok. Pencereler
  `label_source: declared` olarak kaydedilir.

Kabul için gereken ölçümler. İndirme bu ADR onaylanmadan yapılmaz; `pcaps.zip`
13,92 GB'tır.

1. `data/audit.py` ile her UNSW cihazının EGRESS payı ve multicast etkisi; cihaz
   eşlemesi MAC adresinden.
2. **Kaynak kısayolu testi:** benign eğitim yalnız UNSW'den, benign değerlendirme
   IoT-23 honeypot'larında yapılır. IoT-23 benign FPR'si UNSW benign FPR'sinden
   belirgin yüksekse model davranışı değil "hangi laboratuvar" bilgisini öğreniyordur;
   sonuç böyle raporlanır.
3. FPR ve recall kaynak başına ve capture başına raporlanır; birleşik tek bir FPR
   verilmez. IoT-23 benign grupları her koşuda doğrulama veya test ayrımında kalır.

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

## Değerlendirilen alternatifler

- **CICIoT2023 birincil kalsın:** erişilemiyor ve açıklamasına göre saldırılar LOCAL.
  Reddedildi; KAN-23 adayı olarak kaldı.
- **LOCAL saldırıları EGRESS'e dönüştüren lab-only replay:** mümkün, ama bir
  laboratuvar dönüşümüdür; manifestte beyan edilmeli ve doğal WAN genellemesi iddiası
  taşımaz. Kaynak erişilemediği için bugün uygulanamaz. Ertelendi.
- **Kendi cihazlarımızdan doğal gateway capture'ı:** benign için en gerçekçi kaynak,
  ama birkaç cihazla ve kısa süreyle sınırlı, kişisel trafik içerir. G8 lab ve
  KAN-51/52 canlı doğrulamasında kullanılır; bugün eğitim kaynağı değil.
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
2. R2: canlı adaptörde EGRESS dışlama eşitliği ve alt ağ broadcast kararı (KAN-15).
3. R1: UNSW-IoTraffic indirilir, denetlenir, pack'e yalnız-benign kaynak olarak
   eklenir; Karar 5'teki kısayol testi koşulur.
4. `docs/G1_REVIEW.md` ve `docs/STATUS.md` kaynak satırları bu ADR'ye bağlanır.
5. KAN-57 metodoloji dokümanı karıştırıcılar bölümünü buradan alır.

## Kaynaklar

Erişim tarihi 2026-09-14.

- [IoT-23, Zenodo kaydı ve lisansı](https://zenodo.org/records/4743746)
- [IoT-23, Stratosphere Lab sayfası](https://www.stratosphereips.org/datasets-iot23)
- [UNSW-IoTraffic, Dryad](https://datadryad.org/dataset/doi:10.5061/dryad.w0vt4b94b)
- [UNSW-IoTraffic tanımlayıcısı](https://www2.ee.unsw.edu.au/~hhabibi/pubs/jrnl/25unsw-iotraffic.pdf)
- [Dryad yayın ve CC0 politikası](https://datadryad.org/publication_policy)
- [UNB CICIoT2023](https://www.unb.ca/cic/datasets/iotdataset-2023.html)

## Ekip review

- [ ] R1 Onur: yazar.
- [ ] R2/Lead Şükrü: kaynak değişikliği, EGRESS dışlamalarının canlı adaptörle
      eşitliği, UNSW indirmesi.
- [ ] R3 Gabriel: ExperimentManifest veri bölümünde kaynak, lisans ve atıf
      alanlarının taşınması.

İmzalar gerçek inceleme sonrası işaretlenir. Bu ADR onaylanana kadar veri
kaynağı değişikliği yapılmış sayılmaz; mevcut pack ve KAN-18 sonuçları "IoT-23
önerisi altında" sonuç olarak anılır.
