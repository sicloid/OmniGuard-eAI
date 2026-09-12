# OmniGuard mimari değerlendirmesi — 10 Eylül 2026

Durum: araştırmaya dayalı tasarım değerlendirmesi ve V3 önerisi. Çalışan kodun
veya ekipçe kabul edilmiş yeni bir runtime sözleşmesinin yerine geçmez.
İnceleme tabanı: `7fd2d36`; uygulama kanıtı: [Linux raporu](../LINUX_VALIDATION.md).

## Kararım

Self-hosted V2 yönünü koruyorum. Projeyi güçlendirecek katkı, daha karmaşık bir
model veya daha fazla cloud servisi eklemekten çok, yanlış ve eksik gözlemlere
rağmen kontrollü karar veren, uygulamasını doğrulayan, süresi sınırlı karantina
sistemidir. Özgünlük hipotezi şu ölçülebilir soruda toplanmalı:

> Belirli bir yanlış karantina ve kullanıcı kesintisi bütçesi altında, ne kadar
> az ağ özelliği ve işlem kaynağıyla zararlı egress trafiğini sınırlayabiliyoruz?

Bu bir araştırma katkısı önerisidir; literatürde ilk olduğu veya ticari
rakiplerden daha iyi olduğu henüz gösterilmedi. Önceki sohbetlerdeki başarı
olasılıkları, yarışma puanları ve "minimum 15 saniye" gibi kesin ifadeler ölçüm
kanıtı değildir. Yarışma başarısı hakkında sayısal garanti vermem.

## İlk fikrin nasıl değiştiği

Kaynaklar doğrudan `ChatGPT Plus Tanıtımı` görevinden okundu; paylaşılan URL'nin
boş web çıktısına dayanılmadı. Yakın dönem mesajlar, mimarinin dondurulduğu önceki
mesajlar ve PDF sayfaları karşılaştırıldı. Sohbetin her mesajının veya Windows
paylaşımının tamamının okunduğu iddia edilmez.

| Aşama | Kaynak / gözlem | Bugünkü karar |
|---|---|---|
| 32 sayfalık ilk tartışma | `omniguard(1).pdf`, "Huawei Staj Projesi Fikirleri Analizi"; ilk bölüm fikir seçimi, özellikle s.21–32 OmniGuard: ONT/OSGi, cloud karar, legacy/TR-069, kolektif sinyal ve P2P engelleme | Uzun vadeli vizyon; bugünkü çalışabilirlik veya novelty kanıtı değil |
| 8 sayfalık sunum | `Omnıguard_eAI-Sukru_Bicer.pdf`, özellikle s.4 ve 7: ONT agent, ModelArts, cerrahi izolasyon, global vaccine | Kullanıcı yükünü azaltma hedefi korunur; evrensel ONT uyumu ve sıfır mahremiyet riski iddiaları çıkarılır |
| PDF sonrası sohbet | Yerel gateway, aynı extractor, PCAP, RF, gerçek sink, capture-aware split; Plume/CUJO benzerliği kabul ediliyor | Projenin savunulabilir araştırma çekirdeği |
| En son V2 düzeltmesi | Kullanıcı erişilemeyen Huawei servislerini çıkarıyor; Mosquitto/PostgreSQL/Grafana; Pi yalnız ortak hedef | Güncel temel; eski cloud görevlerine dönülmez |
| Linux devamı | PR #1 merge, 21 test, gerçek UDP karantina, Compose smoke; PR #2 | İlk iki aşamanın kanıtı var; gerçek ML ve G8/G10 henüz yok |
| Bu V3 incelemesi | Observation quality, uygulama sonucu, süre sınırı, kullanıcı kesintisi, veri uygunluğu | Dokümanlarda somutlaştırıldı; yeni runtime uygulaması ayrı işler |

Sohbet: https://chatgpt.com/share/6aa23e99-eb38-83ed-9e7b-e55044a16761
Windows devamı: https://chatgpt.com/s/cx_6aa21bbb71088191a13104d87fb80683
Kaynak PDF'ler ve sohbet kişisel içerikleri repoya kopyalanmadı.

## En önemli açıklar

| Öncelik | Mevcut açık | Neden önemli / düzeltme |
|---|---|---|
| P0 | Veri seti yönü ile hedef egress senaryosu eşit varsayılıyor | CICIoT2023'te saldırgan ve hedef aynı LAN'daysa mevcut normalizer LOCAL üretir; EGRESS extractor'a örnek kalmayabilir. Önce gerçek PCAP/topoloji/cihaz-etiket eşlemesi denetimi |
| P0 | StateEvent ile gerçek firewall sonucu ayrılmamış | QUARANTINED kararı uygulanamayabilir; karar, nft ACK/readback ve sink gözlemi ayrı tutulmalı |
| P0 | TTL yalnız Python timer olursa süreç ölünce blok kalabilir | Kernel timed set + yeniden başlatmada uzlaştırma + yönetici release; sürekli yenilemeyle sınırsız karantina oluşturma |
| P0 | Eksik gözlem "normal" sanılabilir | Capture drop, kuyruk taşması, eski/geç pencere, belirsiz device binding ayrı health bilgisi; güvenilir olmayan pencere karantina serisini ilerletmemeli |
| P0 | UI için bilgi eksik | TelemetryPayload yalnız StateEvent içeriyor; anomaly score grafiği ve enforcement sonucu mevcut sözleşmeden türetilemez. Sürüm kontrollü ek kayıtlar öner |
| P1 | Offline skor politikası ile gerçek kapalı çevrim aynı sanılabilir | Karantina TCP/retry davranışını değiştirir. Offline N taraması aday üretir; sonuçlar canlı senaryo ile doğrulanır |
| P1 | Window FPR kullanıcı zararını anlatmıyor | Yanlış karantina/device-hour, benign engellenme süresi, yerel işlev testi ve tekrar karantina sayısı ölç |
| P1 | Tam frame alımı "payload hiç okunmuyor" diye anlatılıyor | Mevcut parser tam IP uzunluğu ister. Doğru iddia payload-independent özellikler; header-only capture için ayrı adapter/uzunluk sözleşmesi gerekir |
| P1 | 15 günlük tarih çizelgesi fiziksel gerçeklik gibi kullanılıyor | Veri uygunluğu, G8 ve G10 bağımlılıklarına göre ilerle; Jira tarihlerini kendiliğinden değiştirme |

### Veri uygunluğu özellikle önce gelmeli

UNB, CICIoT2023'te saldırıların IoT cihazlarından başka IoT cihazlarına yapıldığını
ve hem PCAP hem çıkarılmış CSV sunduğunu açıklıyor [S1]. Bu, seçtiğimiz capture'ın
evden dışarıya saldırı örneği olduğunu tek başına kanıtlamaz. R1/R2 birlikte gerçek
capture noktasını, subnetleri, saldırgan/hedef kimliğini ve etiket çözünürlüğünü
incelemeli. Tüm LAN'ı tek cihazmış gibi göstermeyin. LOCAL trafiği sessizce EGRESS
olarak yeniden etiketlemeyin. Kontrollü topoloji dönüşümü yapılırsa bunun bir
laboratuvar dönüşümü olduğunu manifestte gösterin; doğal WAN genellemesi iddiası
ayrı tutulmalı. Veri uygun değilse kapsam veya veri seti ADR ile değişmeli.

IoT-23, akış etiketleri ve PCAP sağlar; hafif paket PCAP içermez [S2]. Akış etiketi
cihazın tüm süresini kötü etiketlemek değildir. Cihaz/pencere etiketi üretirken zaman
çakışması, yön, benign/malicious karışımı ve belirsiz örnekler açıkça tanımlanmalı.
Kaynak cihazlar ve kayıt koşulları sınıfı ele verebilir; IP'yi özelliklerden çıkarmak
bütün shortcut risklerini ortadan kaldırmaz.

### 2026'da gerçekten ne eklerdim?

1. **Süre ve kanıtla sınırlandırılmış otomatik karantina.** Tek başına model skoru
   karar yetkisi olmamalı: observation health, cihaz eşlemesi, politika sürümü,
   uygulama sonucu ve kernel timeout birlikte çalışmalı. Süre sınırı dolunca ağın
   açılması cihazın temizlendiği anlamına gelmez; şüphe geçmişi korunur.
2. **Yanlış karantina maliyetiyle özellik/hesap bütçesi karşılaştırması.** Basit bir
   rate/connection-count kuralı, RF ve RF+N politikası aynı veride karşılaştırılsın.
   RF basit kuralı geçmiyorsa bunu raporlamak da değerlidir. Özellik sayısı, CPU,
   kaçan saldırı byte'ı ve benign engellenme süresinin Pareto sınırı hedeflensin.
3. **Cihaz yaşam döngüsü ve dağılım değişmesi testi.** Setup, update, idle, active
   gibi benign durumları stres setine ekleyin. NIST IR 8349 (2025) bu davranış
   çeşitliliğini karakterize etmeyi ele alıyor [S3]. İlk adım online öğrenme değil;
   gözlem güveni düştüğünde otomatik karar yetkisini azaltmak ve bunu ölçmek.

Bunların tümünü "ilk biz yaptık" diye sunmayın. REAL-IoT (2025) gibi çalışmalar,
gerçekçi saldırı ve değişen dağılımlarda dayanıklılığı zaten araştırıyor [S4].
Benim önerim, bu ilkeyi küçük, tekrar üretilebilir bir sistem deneyine uygulamak.

### Hangi güncel teknolojiyi neden ertelerim?

| Seçenek | 2026 değerlendirmesi | Karar |
|---|---|---|
| LLM/agent firewall kararları | Model çıktısından shell/kural üretimi ve değişken karar maliyeti ana soruna katkı kanıtı sunmuyor | Kritik yol dışında; ileride yalnız kayıt açıklama |
| eBPF/XDP | Capture/aggregation için ölçülebilir performans araştırması olabilir; özellik semantiği farklılaşabilir | Önce dpkt/AF_PACKET drop bütçesi ölçülsün; G8 sonrası gerekirse |
| ONNX/skops | Artifact güvenliği veya runtime maliyeti için aday; destek/eşitlik ayrı doğrulanmalı | Trusted joblib baseline; hash, environment ve düşük yetki önce [S5] |
| MUD | Cihaz davranışını sınırlandıran standart yaklaşım var [S3] | İleride sürümlü cihaz profili karşılaştırması; üretici dosyası olmadan "MUD uyumlu" deme |
| Kubernetes/Kafka/feature store | Üç kişilik, tek host PoC'de yeni işletim yükü | Compose/MQTT/PostgreSQL yeterli |
| Federated/continual learning | Poisoning, etiket ve drift değerlendirmesini büyütür | G8/G10 ve bağımsız holdout sonrası araştırma |
| CIC-YNU-IoTMal 2026 | PCAP kökenli işlenmiş Parquet ve LLM-generated benign açıklanıyor; raw capture uygunluğu ayrı belirsizlik | Otomatik ana veri seti değişikliği yok; audit adayı [S6] |

Plume zaten IoT anomaly detection ve device quarantine tanımlıyor [S7]. CUJO da
router katmanında güvenlik sunduğunu açıklıyor; 2026 RDK-container duyurusu listeleniyor
[S8]. Container kullanmak veya cloud'dan edge'e taşınmak tek başına özgünlük sağlamaz.
Bu kaynaklar ürün sahibinin iddiasıdır; bağımsız performans karşılaştırması değildir.

## Uygulama önceliği ve kapsam

Önce [V3 mimari](../../ARCHITECTURE.md) ve [uygulama sırası](EXECUTION_V3.md).
Yeni state, classifier sınıfı veya wire alanı bu incelemede koda eklenmedi.
[ADR-0002](../adr/0002-bounded-containment.md) öneridir; önceki ekip onayını yeni
EnforcementResult/ObservationHealth sözleşmeleri için otomatik onay saymayın.
Daha önce tamamlanan KAN-7/KAN-8 ilk sözleşme onayını temsil etmeyi sürdürür.

## Doğrulanmış kaynaklar

Erişim tarihi 2026-09-10. Kaynakların gösterdiği mekanizma ile önerdiğim tasarım
ayrıdır; dokümanlardaki eşikler yeni deney ayarlarıdır, dış kaynak sonucu değildir.

- [S1 — UNB CICIoT2023](https://www.unb.ca/cic/datasets/iotdataset-2023.html)
- [S2 — Stratosphere IoT-23](https://www.stratosphereips.org/datasets-iot23)
- [S3 — NIST IR 8349, final 2025](https://csrc.nist.gov/pubs/ir/8349/final)
- [S4 — REAL-IoT, 2025 araştırması](https://arxiv.org/abs/2507.10836)
- [S5 — scikit-learn model persistence](https://scikit-learn.org/stable/model_persistence.html)
- [S6 — CIC-YNU-IoTMal 2026](https://www.unb.ca/cic/datasets/ynu-iot-2026.html)
- [S7 — Plume ürün tanımı](https://www.plume.com/legal/product-descriptions)
- [S8 — CUJO AI](https://cujo.com/)
- [S9 — Linux flowtable bypass](https://docs.kernel.org/networking/nf_flowtable.html)
- [S10 — nftables timed elements](https://wiki.nftables.org/wiki-nftables/index.php/Element_timeouts)
- [S11 — scikit-learn leakage ve pipeline](https://scikit-learn.org/stable/common_pitfalls.html)
