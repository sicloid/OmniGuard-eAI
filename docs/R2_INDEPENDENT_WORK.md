# R2 bağımsız çalışma paketi — 10 Eylül 2026

Şükrü'ye atanmış açık kartlar Jira'dan yeniden okundu. Görev sahipleri/tarihleri
korundu; çalışma sırasında kişi başına bir Devam ediyor kartı tutuldu. Aşağıdaki
uygulamalar incelemeye sunulur, ekip onayı veya gerçek entegrasyon yerine geçmez.

| Kart | Bağımsız teslim | Doğrulama / kalan |
|---|---|---|
| KAN-29 | [PR #5](https://github.com/sicloid/OmniGuard-eAI/pull/5): checked detector arayüzü | 7 yeni test; R1 gerçek model ve artifact entegrasyonu ayrı |
| KAN-28 | [PR #6](https://github.com/sicloid/OmniGuard-eAI/pull/6): bounded 5s cihaz pencereleri | 10 yeni test; canlı watermark/health, extractor parity ve N reset bağlantısı ayrı |
| KAN-27 | [PR #7](https://github.com/sicloid/OmniGuard-eAI/pull/7): gerçek LAN ingress adapterı | 10 yeni test; Docker 100/100/100, 100/100/0, 100/100/100; taşma tespiti; health bağlantısı ayrı |
| KAN-32 | [Replay harness](../lab/REPLAY.md), run manifest ve t0 | 9 yeni test; iki gerçek 100/100/100 replay; label/preparation audit ve leakage korelasyonu ayrı |

KAN-32, capture oracle'ını tekrar kullanmak için PR #7 dalı üzerine kuruldu;
incelemede yalnız replay değişiklikleri gösterilir. PR #7 birleşince hedef main
olarak güncellenebilir. PR #4 mimari incelemesinin kapsamı genişletilmedi.

## Diğer açık kartların mevcut bağımlılıkları

| Kartlar | Neden aynı bağımsız pakette tamamlanmış sayılmıyor? |
|---|---|
| KAN-30/31 | KAN-63'te yeni health/lease/episode ve uygulama sonucu kararları; ardından gerçek state/enforcer testleri |
| KAN-33 | KAN-31 uygulama/ACK kanıtı ile sink ölçümünü korele etmesi gerekiyor; send return containment değildir |
| KAN-34 | Gabriel'in KAN-38 UDS/framing ADR'siyle ortak transport kararı gerekiyor |
| KAN-48 | Gerçek state/enforcer bağlantısı ve fault matrisi henüz yok; yalnız python -m stubs gate değil |
| KAN-49 | R1 gerçek extractor/RF artifact ve tam R2 zinciri gerekiyor; canlı capture veya replay tek başına G8 değil |
| KAN-35 | G8 sonrası gerçek laptop core demo gerekiyor |
| KAN-54 | Gerçek deney/holdout/ablation sonuçları yok; metrik freeze yapılamaz |
| KAN-55/58 | Kurulum ve yeni modül runbook'ları ilerledi; tam G8/G10/Pi/fallback demo henüz doğrulanmadı |
| KAN-59 | Gerçek ekip bilgi aktarımı/Q&A provası ekip katılımı gerektiriyor |
| KAN-60 | G8/G10, sonuç freeze, demo ve ekip provası tamamlanmadan release değil |
| KAN-63 | PR #4'te ekip mimari incelemesi bekleniyor; eski onay yeni V3 alanlarını onaylamaz |
| KAN-1/3/5/6 | Üst epikler; alt görevlerin/gate'lerin gerçek tamamlanması gerekiyor |

Yeni PR'lar bu denetimde açık ve inceleme bekliyor. Kartlar Tamamlandı yapılmaz.
Bu kayıt tüm projeyi bitirdiğimiz anlamına gelmez; başlatılıp somutlaştırılan bağımsız
R2 çalışmalarını ve kalan ekip/veri/entegrasyon bağımlılıklarını ayırır.
