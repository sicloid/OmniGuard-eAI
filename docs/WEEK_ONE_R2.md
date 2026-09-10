# Şükrü / R2 — ilk hafta uygulama raporu

10 Eylül 2026. Kapsam: Jira `bu-hafta` etiketli, Şükrü'ye atanmış açık işler.
Önceden bitmiş KAN-12/KAN-61/KAN-62 tekrar yapılmadı.

İnceleme: [PR #1](https://github.com/sicloid/OmniGuard-eAI/pull/1).
Dal: `feat/KAN-24-week-one-gateway`.

| Kart | Yapılan | Kapanış için kalan |
|---|---|---|
| KAN-7 | G1_REVIEW.md: kararlar, somut inceleme dosyaları ve onay tablosu | Gerçek ekip değerlendirmesi/onayı |
| KAN-8 | Mevcut taslak korunarak parser semantiği ve açık kararlar belgelendi | R1/R2/R3 onayı ve sürüm freeze |
| KAN-11 | GitHub'a yayın, draft PR, Windows/Linux CI, Linux ShellCheck; CODEOWNERS API hatasız | Ekip review ve Onur'un GitHub hesabı |
| KAN-24 | Owned A→B→C netns setup/teardown, çakışma/kimlik kontrolleri, belirli subnet routing | Dedicated Linux üzerinde gerçek topoloji/smoke kanıtı |
| KAN-25 | Gateway-only nftables; karantina established kabulünden önce; conntrack + sink stop/restore testi | Dedicated Linux üzerinde gerçek test ve güvenlik review |
| KAN-26 | Classic PCAP → PacketTuple, LAN/cihaz eşlemesi, VLAN/IPv4/IPv6/fragment desteği, CLI ve sayaçlar | Şema/owner review |

## Test kanıtı

- Windows yerel: 20 unit test, editable install, Ruff lint/format geçti.
- Testler struct ile bağımsız kurulmuş paket oracle'larını ve geçici gerçek PCAP
  dosyalarını kullanır. CLI JSONL çıktısı ve istatistikleri de doğrulanır.
- Tüm `.sh` dosyaları ayrı ayrı Bash syntax kontrolünden geçti.
- GitHub Actions Windows/Linux matrisi PR üzerinde çalışır; güncel sonuçlar
  PR Checks sekmesindedir. Linux işindeki Python testleri ve ShellCheck doğrulandı.
- CODEOWNERS hata API'si feature branch için boş hata listesi döndürdü.
- 1 MiB üstü PCAP kayıt talepleri okumadan reddedilir; kısa kayıt/truncated IP,
  unsupported linktype ve PCAPNG açık hata üretir. Paket payload'u çıktıya taşınmaz.

## Ortam engeli

`wsl --list --verbose`: kurulu dağıtım yok.
`docker info`: Linux engine named pipe yok.
`docker desktop start`: kayıtlı launcher yolu başka bir Windows kullanıcı
profilini gösteriyor; bulunan yerel executable ile başlatma denemesi de engine'i
çalıştırmadı. Docker/WSL kurulumunun veya erişilebilir Pi/Linux lab'ın hazırlanması
sonrasında `lab/README.md` komutları uygulanmalı.

Root gerektiren lab betikleri bu Windows oturumunda veya shared GitHub CI'da
çalıştırılmadı. Host firewall, routing ve Tailscale ayarları değiştirilmedi.
Bu rapor G5/G8/G10 veya gerçek containment başarısı iddiası değildir.

## İnceleme sınırı

İlk repo boş olduğundan, uygulamayı incelemesiz main'e koymamak için boş main
tabanı oluşturuldu; tüm uygulama mevcut yerel geçmiş korunarak PR'a alındı.
PR merge edilmedi. Şema draft kaldı. İnsanların onayları yerine AI onayı yazılmadı.
