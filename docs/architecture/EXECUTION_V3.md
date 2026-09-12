# V3 uygulama sırası ve rol haritası

10 Eylül 2026. Bu plan bir mimari öneridir; Jira kabul maddeleri güncellendi (bkz. [kayıt](JIRA_SYNC_V3.md)); aşağıdaki
kabul maddelerinin tamamlandığı iddia edilmez. Mevcut G1/G2 doğrulamaları korunur.
Takvimden önce bağımlılık/kanıt sırası gelir; eski 15 iş günü hedefi garanti değildir.

## Sıra ve mevcut kartlara etkisi

| Sıra | Sahip | Mevcut kartlar | V3 ile somutlaştırılan teslim |
|---|---|---|---|
| 0 | Lead + ekip | KAN-63: yeni ADR ekip incelemesi | ADR-0002 kayıt/timeout/health kararlarını incele; V2 kartlarını geçmiş onay olarak tut |
| 1 | Onur + Şükrü | KAN-13/14/15 | PCAP görünürlüğü/yönü, device-label-time eşlemesi, parent capture grupları, feature catalog ve manifest |
| 2 | Onur + Gabriel | KAN-9/10 | Artifact hash + environment check; deployment interpreter/architecture kilidi; güvenilir deserialization sınırı |
| 3 | Onur | KAN-16/17/18 | Tek extractor, sabit grup split, leakage-free RF ve basit rate-rule karşılaştırması |
| 3 | Şükrü | KAN-27/28/29 | LAN capture, bounded queue, drop health, epoch pencereler ve offline/live parity |
| 3 | Gabriel | KAN-38/39/40/41 | Önce mevcut 0.1.0 StateEvent ile DB/consumer/dashboard; yeni kayıtlar KAN-38/63 onayı sonrası sürümlü migration ile |
| 4 | Şükrü | KAN-30/31/48 | N off-by-one/gap davranışı, kernel TTL, apply sonucu, restart/release, stub fault testleri |
| 5 | Şükrü + Gabriel | KAN-32/33/42/43 | t0 mapping, ACK sınırı, sink sayaçları, timeout/non-detection, edge/platform cost ayrımı |
| 6 | Şükrü + Onur | KAN-49 | Gerçek RF ile G8; telemetry kapalı; TCP/UDP; process crash; lokal service kontrolü |
| 7 | Gabriel + Şükrü | KAN-34/50 | Docker/direct-netns UDS mount izinleri; gerçek event zinciri; duplicate/outage/recovery G10 |
| 8 | Onur + Gabriel | KAN-19/20/21/51/52 | Validation seçimi, feature/policy ablation, benign kesinti ve grouped uncertainty |
| 9 | Gabriel | KAN-44/45/46/53 | Pi gerçek donanım doğrulaması, kaynak ve termal koşul, x86'dan ayrı sonuç |
| 10 | Ekip | KAN-54–60 | Sonuç/run manifest freeze, temiz checkout demo, sınırlamalar ve bilgi aktarımı |

Aynı sıra numaralı işler bağımsız ilerleyebilir. Rol başına bir büyük aktif iş;
stub bir bileşenin bağımsız gelişmesini sağlar ama gate kanıtı olmaz.
R3'ün KAN-36/KAN-37 kodu PR #2 ile birleşti; kartlar Tamamlandı. Gabriel'in
sıradaki planı KAN-38 ve UDS/framing ADR'sidir; V3 kayıt önerileri bu incelemeyle koordine edilir.

## İlk uygulanacak küçük paket

1. **Veri audit çıktısı:** bir benign ve bir saldırı örneğiyle mekanizma gösterimi,
   sonra bütün seçilecek capture grupları için kapsam tablosu. İki örnek araştırma
   yeterliliği değildir. Eksik/uygunsuz label varsa eğitimden önce durumu kaydet.
2. **Parity fixture:** aynı packet metadata dizisinin offline/live yoldan aynı
   pencere/feature sonucunu verdiği test. Exact float toleransı feature bazlı belirlenir.
3. **Policy fixture:** N=1/2/3, benign reset, invalid gap, stale score, release,
   tekrar karar ve episode süresi. Bu fixture ML başarısı göstermez.
4. **Gerçek enforcer fault testi:** timeout set'i, controller kill ve restore.
   Aynı namespace-owned güvenlik sınırını kullanır; ev ağına replay yok.

## Veri manifest minimumu

source URL/version/license, capture SHA-256, original parent capture/session,
scenario, label kaynağı ve çözünürlüğü, capture noktası, yön/subnet/device binding,
label mapping/exclusion sayıları, replay dönüşümü, feature catalog/version,
train/validation/test group listeleri ve tekrar üretim komutu.

Etiket veya capture kimliği model feature'ı değildir. Port/destination-count gibi
izinli metadata da veri toplama koşullarını ele verebilir; grup bazlı test ve
karşılaştırma gerekir. CICIoT2023 varsayılan aday olarak kalır; uygunluk kanıtı
çıkmadan bütün veri setinin ev-gateway egress'e uyduğu söylenmez.

## Küçük ama anlamlı deney matrisi

Önerilen başlangıç adayları; ekip validation bütçesini belirlediğinde freeze edilir:

- Pencere: 5s tumbling sabit. N adayları: 1, 2, 3, 5.
- Özellikler: onaylı tam katalog + ablation ile üretilmiş bir küçük altküme.
  Başlangıçta `2 feature-set × 4 N = 8` RF policy ayarı; bağımsız capture tekrarları
  bu sayıya ayrıca eklenir. CPU bütçe taraması yalnız seçilen finalistlerde.
- Basit rate kuralı ve detection-only run, aynı split/senaryo/süre koşullarında.
- Benign durumlar: idle/active/startup/update erişilebilen gerçek kapsamıyla;
  erişilemeyen mod test edilmiş sayılmaz. Sentetik stres ayrı etiketlenir.
- Saldırı profilleri: uygun PCAP/label kanıtı olan en az yüksek oranlı ve mümkünse
  düşük oranlı davranış. Replay gerçek botnetin adaptif davranışı diye sunulmaz.
- Aralıklı düşük oranlı saldırı: bir dolu/bir boş pencere profili ve kaçış/miss
  sonucu açık raporlanır. Baseline boş pencere seriyi sıfırlar. KAN-20'de yalnız
  sağlıklı boş pencerenin saymadan seriyi koruduğu varyant karşılaştırılabilir;
  invalid/loss/stale her varyantta reset olur, adayın max-gap süresi validation'da
  sabitlenir. Bu deney adayı baseline'ı sessizce değiştirmez.
- Arıza matrisi: broker down, enforcer/runtime kill, capture overload, stale binding,
  duplicate event ve release/restart. Fault run'lar ML accuracy örneğine karışmaz.

Threshold, N, lease ve feature seçimi validation'da yapılır. Nihai test
karşılaştırmasının hipotezleri önceden belirlenir; test grafiğinden yeni en iyi
policy seçilmez. Veri azsa bağımsız grup sayısını raporlayıp iddiayı sınırla.

## Raporun zorunlu sütunları

| Boyut | Sonuç |
|---|---|
| Tespit | Precision/Recall/F1/window FPR; incident recall; sınıf ve capture sayıları |
| Kullanıcı maliyeti | False quarantine/device-hour; benign blocked seconds/device-hour; lokal işlev başarı oranı; release recovery |
| Containment | t0→decision, decision→ACK, t0→ACK; leakage L3 packets/bytes; ACK sonrası geçenler; miss/timeout oranı |
| Kaynak | capture/feature/inference/policy/enforcer/exporter CPU/RSS; platform maliyeti ayrıca; packet loss/queue overflow |
| Telemetry | JSON vs UDS vs MQTT/wire hacmi; duplicate/drop/spool occupancy ve completeness |
| Tekrar üretim | commit, artifact/env/policy/split hash, run id, hardware/boot/time mapping |

FPR^N ile false quarantine olasılığı uydurulmaz. Sıfır gözlenen false quarantine,
sıfır gerçek risk değildir. Bağımsız device-hour ve capture sayısı/güven aralığı
sunulur. Uygun benign işlev verisi yoksa "kullanıcı kesintisini çözdük" denmez.

## Kapsam kesme sırası

Önce adaptive windows, LLM açıklama, eBPF optimizasyonu, ONNX karşılaştırması,
online/federated learning, yeni 2026 dataset genişletmesi ve dashboard süsü kesilir.
Kesilmez: veri uygunluğu, aynı extractor, basit baseline, gerçek G8, süreli release,
arızada dürüst state/health, temel G10, leakage/benign kesinti ve laptop demo.
Pi erişilemezse x86 sonucu teslim edilir; Pi/ARM64 sonucu uydurulmaz.

## 12 Eylül inceleme kararı

R3 mevcut 0.1.0 üzerinde ilerler; tarihler ve sahipler değişmez. KAN-39 numaralı
SQL migration, KAN-40 dedup/recovery ve KAN-41 dosyadan provisioning getirir.
Yeni health/applied türleri önce ADR'de onaylanır; mevcut dashboard StateEvent'i
yalnız karar olarak gösterir. ExperimentManifest biçimi/yazımı R3 KAN-42/43,
veri/split/artifact bölümü R1 KAN-14/17/18, saat/sink girdisi R2 KAN-32/33'tür.
Detay ve açık kararlar: [inceleme yanıtları](REVIEW_RESOLUTION_2026-09-12.md).
