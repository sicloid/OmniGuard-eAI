# KAN-64 — yeni benign cihaz genellemesi deney protokolü

Durum: koşu öncesi protokol. Sahip: Şükrü/R2 (protokol ve capture), Onur/R1
(değerlendirme). Bu belge KAN-65, KAN-67 ve KAN-70 için seçim kurallarını koşu
sonucundan önce sabitler. KAN-19 modeli, eşik veya politika parametreleri bu
belgeye bakılarak değiştirilemez.

Sahip kontrollü Raspberry Pi capture koşulları ve sınırlı güç sınırı
[KAN-66 belgesinde](KAN66_PI_BENIGN.md) ayrıca kayıtlıdır.

## Araştırma sorusu

Donmuş KAN-19 çalışma modeli, eğitimde görülmeyen normal cihaz trafiğinde yanlış
anormallik ve yanlış karantina üretiyor mu? İlk hedef yeniden eğitim değil,
mevcut modelin cihaz/ortam kısayoluna duyarlılığını görünür kılmaktır.

## Sabit değerlendirme yolu

- Model ve metadata: KAN-19'in hash ile doğrulanmış artefaktı; yeni eğitim yok.
- Feature sözleşmesi: `features-1`, aynı saf extractor ve EGRESS yön semantiği.
- Eşik: `threshold.policy.json`, `0.9798815486832`.
- Politika: `N=2`, `lease=300 s`; kararlar `DevicePolicy` üzerinden replay edilir.
- Çıktı: pencere FPR, false quarantine/device-hour, benign blocked seconds/device-hour,
  policy reset/rejection sayıları, karar gecikmesi ve her censor/invalid nedeni.
- Fırsat ölçümleri: pencere ve aktivite segmenti sayısı, wall-clock ve gözlenen süre,
  gap sayısı ve toplam sessiz süre, gap'siz ardışık pencere çifti, anormal pencere
  sayısı ve en uzun ardışık anormal pencere dizisi.

Bu ilk çalışma deployment FPR tahmini veya dokunulmamış holdout değildir. Mevcut
modeli yeni veriye göre ayarlamak, bu değerlendirme tamamlanmadan yasaktır.

## Veri rolü ve cihaz ayrımı

Pi capture'ı `evaluation_benign` rolündedir: model eğitimine veya validation eşik
seçimine katılmaz. Her fiziksel cihaz tek gruptur; aynı cihazın farklı günleri veya
senaryoları train/test diye ayrılmaz. Bir koşuda aynı Wi-Fi'de başka cihazların
trafiği varsa, `sources.benign_capture` yalnız belirlenmiş cihaz IP'sine giden veya
ondan gelen IP paketlerini yazar; yine de koşu manifestinde ortam kontaminasyonu
not edilir.

Senaryolar önceden tanımlıdır: `idle`, `dns_https`, `file_download`, `reconnect`,
`update`. Gerçek güncelleme veya indirme başlatılamıyorsa o senaryo `not-run` kalır;
yerine başka normal trafik koyup aynı isimle raporlanmaz.

## Capture ve geçerlilik kuralları

1. Capture yalnız explicit interface, LAN CIDR ve cihaz IP'si ile başlatılır.
2. Her koşu yeni bir evidence dizinine yazar; eski sonuç dizini tekrar kullanılmaz.
3. Raw PCAP private evidence'dir, Git'e girmez. Manifest PCAP SHA-256, boot ID,
   Unix/monotonic zaman, arayüz, cihaz ve senaryoyu taşır.
   `sudo` ile çalışan collector, yalnız kendi PCAP ve manifest dosyalarının
   sahipliğini çağıran kullanıcıya geri verir; evidence dizini üzerinde geniş izin
   açılmaz.
4. Operator interrupt, socket hatası, boş cihaz-frame kaydı, yanlış cihaz IP'si,
   capture drop veya koşu sırasında güç/boot değişimi `invalid` ya da `censored`
   olarak saklanır. Başarılı tekrar eski kaydı silmez.
5. Paketler sadece raw-PCAP'ten aynı offline extractor ile pencereye dönüştürülür.
   Live/offline parity ayrı testle korunur.
6. Offline normalizer'ın tek bir frame'i reddetmesi capture'ı `invalid` yapar. Frame
   sessizce atlanmaz. Bu protokol için bozuk kaydın son kayıt olduğu gerekçesiyle
   sapma verilemez; sapma gerekiyorsa koşudan önce ayrı review gerekir.
7. Manifest `device_frames_ipv4` ve `device_frames_ipv6` değerlerini ayrı tutar.
   Bir protokol ailesinin yokluğu sıfır olarak kaydedilir, bilinmiyor sayılmaz.

## Süre, çözünürlük ve belirsizlik

300 saniyelik ilk koşu yalnız collector pilotu/duman testidir. En fazla 60 adet
5 saniyelik pencere üretir; sıfır hata gözlense bile rule-of-three üst sınırı yaklaşık
%5 pencere FPR ve 36 yanlış karantina/cihaz-saat olur. Bu koşu FPR bütçesinin altında
kalındığına veya sahada yanlış karantina olmadığına kanıt değildir.

- Pencere FPR'sini %1'in altında sınırlamaya aday bir senaryo en az 300 geçerli
  pencere içermelidir. Sıfır gözlemde üst sınır yine her zaman raporlanır.
- Yanlış karantinayı 1/cihaz-saatin altında sınırlamaya aday birleşik benign gözlem
  en az 3 cihaz-saat olmalıdır. Daha kısa kayıtlar pilot olarak raporlanır.
- En uzun ardışık anormal pencere dizisi `N`'den küçükse sıfır yanlış karantina
  güvenlik sonucu olarak sunulmaz; politika tetikleme fırsatı oluşmadığı yazılır.
- Belirsizlik gerekiyorsa bootstrap sabit pencere sayısı yerine gerçek zaman blokları
  kullanır ve blok uzunluğu en uzun lease olan 300 saniyeden büyüktür. Yeterli blok
  yoksa aralık uydurulmaz; yalnız ölçüm ve analitik üst sınır verilir.

## Kabul kriteri

KAN-64, protokolün ekip incelemesinden geçmesi ve KAN-66'nın bu protokolü kullanan
en az bir hash'li controlled-scenario manifest üretmesiyle incelemeye hazır olur.
KAN-66, bir capture'ın varlığıyla değil; cihaz, senaryo, label limitation, hash ve
geçerlilik bilgisiyle tamamlanır. KAN-65 model skorlamasını yürütür; KAN-67/70
yeniden eğitim ve holdout için ayrı bağımlı kartlardır.

## Pi 5 ilk koşu planı

Pi'de `wlan0` bağlıdır; `eth0` down durumundadır. İlk koşu `idle` olmalıdır.
Önce IP/LAN bilgisi kaydedilir, sonra 300 saniyelik bounded collector pilotu başlatılır.
Pilot kabul edilirse ölçüm senaryoları yukarıdaki asgari gözlem kurallarına göre daha
uzun ve ayrı koşular olarak alınır. Bu capture zamanlaması Pi performans benchmark'ı değildir. Ham capture kişisel ağ
metadatası taşıyabileceği için yalnız ignored `artifacts/` veya Pi yerel evidence
dizininde tutulur.
