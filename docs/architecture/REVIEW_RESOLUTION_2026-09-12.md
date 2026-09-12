# PR #4 — 12 Eylül 2026 inceleme yanıtları

Kaynak: [R1/R3 incelemeleri](https://github.com/sicloid/OmniGuard-eAI/pull/4),
[Gabriel'in ekli incelemesi](https://github.com/user-attachments/files/32102113/pr4review.md).
Şükrü inceleme önerilerinin mimariye/Jira'ya uygulanmasını yetkilendirdi.
Bu kayıt tasarım yönünü ve iş sırasını netleştirir; ADR-0002 PROPOSED, runtime
wire 0.1.0 kalır. KAN-38'in kesin framing/topic/migration sözleşmesi beklenir.

## R3 kararları

- Windows komutları ve PR/Jira kuralları AGENTS.md'ye geri eklendi; agent giriş
  dosyaları bu tek kaynağa yönlenir.
- Event kimliğinde yasak olan retry anında yeni saat/kimlik üretimidir. UUID5
  mümkündür; canonical alanlar, çakışmayan producer/boot/sequence kimliği ve
  spool öncesi crash penceresi KAN-38 testleriyle gösterilir.
- Spool için oldest-first eviction önerisi kabul edilen tasarım yönüdür:
  atomik kayıt, byte/age limiti, kalıcı drop/sequence kanıtı ve eksik G10 sonucu.
- KAN-39/40/41 mevcut 0.1.0 ile ilerler. Yeni envelope onayı bekleyen tasarım
  ayrı migration'dır; mevcut kartların sahipleri/tarihleri değiştirilmez.
- KAN-39: `platform/migrations/NNN_name.sql`, `schema_migrations` sürüm/checksum
  kaydı, transaction ve tek migration runner kilidi. Başarısız migration rollback
  olur; uygulanmış dosya değiştirilmez, checksum uyuşmazlığında startup durur.
  Migration yetkisi consumer'ın sürekli çalışma yetkisinden ayrılır. Temiz DB,
  ikinci startup, eşzamanlı startup ve yarım kalan migration test edilir.
- KAN-41: datasource/provider YAML ve dashboard JSON Git'ten read-only mount
  edilir; parola repoya girmez. Dashboard rolü read-only, StateEvent bir karardır;
  henüz gelmeyen uygulama/health sonucu başarı veya sıfır diye gösterilmez.
- KAN-38/40: enjekte edilebilir transport ile fault testleri; gerçek Compose
  G10 kanıtı ayrıca. Unit test, gerçek broker/DB teslim kanıtını ikame etmez.
- KAN-42: Unix/monotonic saat domainleri ve boot/host kimliği ayrı tutulur.
  `NewType` tek başına aritmetik farkını engellemez, Ruff type checker değildir.
  Yanlış domain çıkarımını reddeden wrapper/API ve negatif test gerekir;
  static checker eklenirse ayrıca kilitlenir ve CI'da çalıştırılır.
- ExperimentManifest accountable sahibi Gabriel (KAN-42/43). R1 veri/lisans,
  capture/parent/split/artifact hashlerini; R2 boot/clock mapping, t0 ve sink
  kanıtını sağlar. Biçim versioned, run'ın başında config freeze, sonunda outcome
  tamamlanır; partial/failed run silinmez.

## R1 kararları

- G1 için Onur'un doğrudan kabulü G1_REVIEW.md'ye işlendi.
- Veri audit'i uygun EGRESS/etiket kapsamı göstermeden veri kaynağı değiştirilmez.
  KAN-13 sonucu LOCAL ağırlığını doğrularsa, eğitimden önce veri seti karar ADR'si
  açılır; ADR numarası mevcut dizine göre ayrılır (KAN-38 ile numara çakışmaz).
  Doğal gateway capture, manifestli lab-only replay dönüşümü ve IoT-23 adayları
  karşılaştırılır. Erişim sorunu veya tek örnek başarı seçim kanıtı değildir.
- KAN-14 IoT-23 pencere etiketi önerisi: güvenle eşlenmiş kötü akışın en az bir
  paketi varsa malicious; mixed/unknown/unmatched sayıları ayrı kaydedilir.
  Unknown trafik benign'e çevrilmez; beşli akış anahtarı, iki yön, zaman aralığı,
  saat toleransı ve label sürümü örnek oracle ile doğrulanır. Eğitim öncesi freeze.
- Baseline boş/invalid/gap reset politikası korunur. Aralıklı saldırı kaçışı ve
  sağlıklı boş-pencereyi saymadan koruyan max-gap sınırlı alternatif KAN-20
  adaylarıdır; capture kaybı hiçbirinde olumlu gözlem sayılmaz.
- KAN-9 metadata için `meta_format` ve `model_sha256` alanlarının belgelenmesi
  önerilir. scipy/joblib sürüm kontrolü ve metadata'nın güvenilen hash'e bağlanması
  artifact uyumluluk revizyonunda birlikte ele alınır. PR #11'in bugünkü kontrolü
  yalnız Python/sklearn/numpy'dir; mimari hedef bugünkü kanıt gibi sunulmaz.
- DetectionRecord tasarımına `model_sha256` eklendi. Policy/feature/model hash
  bağlamı ExperimentManifest ile eşleşir; yeni runtime alanı henüz uygulanmaz.

## Kapanış disiplini

Kod review/merge ile veri ve deney kabulü ayrıdır. KAN-13/14 beklerken
KAN-15/17/18/19'un gerçek veri/önkoşul ölçütleri tamamlandı sayılmaz. KAN-28'in
capture watermark/health ve N entegrasyonu ayrıca kanıtlanır. KAN-10, kullanılan
tüm ekip platformlarını ve seçilen ML bağımlılıklarını kapsayan temiz kurulum
kanıtı olmadan tam ortam kilidi olarak kapatılmaz. G5/G8/G10 açık kalır.
