# KAN-22 — Isolation Forest validation karşılaştırması

Koşu: 27 Eylül 2026. Lider onayı yalnız offline validation karşılaştırmasını kapsar;
test split'i ve harcanmış ADR-0004 holdout'u okunmadı. Hiçbir model artefaktı, runtime
eşiği veya politika üretilmedi.

| Seed | Model | Eşik | Validation recall | Benign-device FPR | Average precision |
|---:|---|---:|---:|---:|---:|
| 1 | Isolation Forest | 0.8339 | **%0.0** | %0.098 | 0.8110 |
| 1 | Random Forest | 0.9799 | %94.5 | %1.374 | 0.9975 |
| 2 | Isolation Forest | 0.8378 | **%0.0** | %0.098 | 0.9824 |
| 2 | Random Forest | 0.9950 | %26.5 | %0.981 | 0.9951 |
| 3 | Isolation Forest | 0.4705 | **%100.0** | %0.542 | 0.9994 |
| 3 | Random Forest | 0.4050 | %85.9 | %0.645 | 0.9967 |

Isolation Forest istikrarlı bir alternatif değildir: aynı yöntem üç capture-group
seed'inde 0, 0 ve 1 recall üretmiştir. Seed 1 ve 2'de düşük benign FPR, tüm saldırı
pencerelerini kaçırma karşılığında elde edilmiştir. Seed 3'teki güçlü sonuç diğer iki
split'e taşınmadığı için aday model kabul edilmez.

Random Forest da capture seçimine duyarlıdır. Seed 1 sonucu tek başına model başarısı
olarak sunulamaz; seed 2'de recall %26,5'e düşmektedir. Bu bulgu KAN-71'in harcanmış
holdout sonucu ile aynı sınırı gösterir: mevcut veri cihaz ve ortam çeşitliliği için
yetersizdir.

Yeni aday model ancak KAN-64/65/68 kapsamındaki cihaz-bazlı benign ayrım ve daha geniş
eğitim verisi tamamlandıktan sonra eğitilir. Bu validation koşusu eşik, N veya lease
seçimini değiştirmez.

Kanıt pinleri `model/frozen/kan22/iforest_summary.json` içindedir. Tam rapor ham
çalışma kanıtı olarak Git dışında tutulur ve SHA-256 değeri özet kaydında sabittir.
