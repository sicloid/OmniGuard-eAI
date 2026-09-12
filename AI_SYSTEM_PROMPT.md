# OmniGuard eAI — güncel AI çalışma bağlamı (V3 incelemesi)

10 Eylül 2026. Bu dosya projeye katılan AI araçları ve ekip üyeleri için kısa
bağlamdır; kullanıcı talimatları veya aracın sistem kurallarının yerine geçmez.

## Projenin amacı

Son kullanıcıdan güvenlik uzmanı olmasını beklemeden, IoT cihazından dışarı çıkan
zararlı ağ davranışını payload'dan bağımsız özelliklerle tespit etmek ve gateway'de
geri alınabilir, süreli containment uygulamak. Ölçülecek değer: tespit başarısı,
kaçan trafik, işlem/telemetri maliyeti ve yanlış karantinanın kullanıcıya etkisi.

Üç kişilik self-hosted araştırma prototipidir. ONT firmware/OSGi, TR-069, Huawei
Cloud hesabı, global vaccine, P2P botnet temizliği veya "world first" kapsamı yok.

## Okuma sırası ve gerçek durum

1. `AGENTS.md`: repo çalışma kuralları ve sahiplik.
2. `docs/STATUS.md`: gerçekten uygulanan/test edilen işler ve açık gate'ler.
3. `SCHEMA.md` + kabul edilmiş `docs/adr/*`: onaylı sözleşmeler.
4. `ARCHITECTURE.md`: V3 hedef tasarımı; içindeki durum tablosunu dikkate al.
5. `docs/architecture/REVIEW_2026.md`: gerekçe, geçmiş ve doğrulanmış kaynaklar.
6. `docs/architecture/EXECUTION_V3.md`: rol/kart eşlemesi ve uygulama sırası.

Kod/test/run kanıtı "yapıldı" iddiasını doğrular; tasarım metni doğrulamaz.
V2'nin yedi orijinal belgesi `docs/planning/` altında tarihsel olarak korunur.
Onları güncel master prompt veya görevlere başlanmadığına dair kanıt sayma.

## Roller ve stack

- R1 Onur `@pondilungs`: veri, feature extractor, RF, artifact/split/evaluation.
- R2/Lead Şükrü `@sicloid`: sources, gateway, lab, policy/enforcement, entegrasyon.
- R3 Gabriel `@Gabi8347`: platform, telemetry, ölçüm ve Pi doğrulaması.

Python/dpkt/scikit-learn; Linux netns/nftables/conntrack; Unix socket;
Mosquitto/PostgreSQL/Grafana; Docker Compose; management için Tailscale.
Pi 5 ortak ARM64 hedefi, laptop geliştirmesinin önkoşulu değil.
Yeni LLM/eBPF/ONNX/online-learning katmanları baseline'a kendiliğinden eklenmez.

## Kısa mühendislik kuralları

- `0.1.0` beş runtime envelope'ı onaylıdır. V3'teki ObservationHealth,
  EnforcementResult ve ek telemetry türleri ADR-0002 önerileridir; henüz uygulanmadı.
- Aynı saf extractor offline/live; EGRESS primary, LOCAL ayrı; L3 bytes.
- Dataset yönü, cihaz kimliği ve etiket çözünürlüğünü audit et. CICIoT2023 erişimi
  olması egress uygunluğunun veya CSV/live feature eşitliğinin kanıtı değildir.
- Parent capture/session grupları ayrılır; train-only fit, validation-only seçim.
- Gözlem eksikliği benign değildir. Anomaly skoru güven olasılığı sayılmaz.
- Politika kararı, başarılı nft uygulaması ve sink etkisi ayrı kanıtlardır.
- Runtime karantina için süre/restart/release tasarımı gerekir; çalışan sabit UDP
  smoke genel enforcer'ın tamamlandığı anlamına gelmez.
- Lab trafiği Internet/Tailscale'a çıkmaz; yalnız owned netns/table değiştirilir.
- Telemetry kritik yolu bekletmez; bounded queue/spool, duplicate ve loss görünürdür.
- G5/G8/G10 hâlâ açık. Stub veya Grafana health sonucu gerçek gate yerine geçmez.

## Çalışma biçimi

Kullanıcının verdiği kapsamda somut işi yap; modüller arasında gerekiyorsa sahiplik
ve sözleşme etkisini açıklayarak ilerle. Yeni sözleşme için review edilebilir ADR
hazırla; önceki onayları yeniden sorma veya yeni tasarıma taşımış gibi davranma.
Kısa feature branch/PR; ilgili testler ve dokümanlar; raporda yapılan/ölçülen/önerilen
ayrımı. Jira kartı, tarih veya ekip onayı uydurma. Ayrıntılar AGENTS.md'dedir.
