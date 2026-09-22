# KAN-64 — yeni benign cihaz genellemesi deney protokolü

Durum: koşu öncesi protokol. Sahip: Şükrü/R2 (protokol ve capture), Onur/R1
(değerlendirme). Bu belge KAN-65, KAN-67 ve KAN-70 için seçim kurallarını koşu
sonucundan önce sabitler. KAN-19 modeli, eşik veya politika parametreleri bu
belgeye bakılarak değiştirilemez.

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

## Kabul kriteri

KAN-64, protokolün ekip incelemesinden geçmesi ve KAN-66'nın bu protokolü kullanan
en az bir hash'li controlled-scenario manifest üretmesiyle incelemeye hazır olur.
KAN-66, bir capture'ın varlığıyla değil; cihaz, senaryo, label limitation, hash ve
geçerlilik bilgisiyle tamamlanır. KAN-65 model skorlamasını yürütür; KAN-67/70
yeniden eğitim ve holdout için ayrı bağımlı kartlardır.

## Pi 5 ilk koşu planı

Pi'de `wlan0` bağlıdır; `eth0` down durumundadır. İlk koşu `idle` olmalıdır.
Önce IP/LAN bilgisi kaydedilir, sonra 300 saniyelik bounded capture başlatılır.
Bu capture zamanlaması Pi performans benchmark'ı değildir. Ham capture kişisel ağ
metadatası taşıyabileceği için yalnız ignored `artifacts/` veya Pi yerel evidence
dizininde tutulur.
