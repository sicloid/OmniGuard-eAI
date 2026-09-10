# OmniGuard eAI — Roller ve Görevler Seçim Tablosu v2

Bu doküman ekip üyelerinin teknik rolünü **kendilerinin seçebilmesi** için hazırlanmıştır.

Her üye:
1. Primary role seçer.
2. Secondary/backup role seçer.
3. Beceri/ilgi puanlarını 0–3 arası doldurur.

Team Lead bu üç rolden birine ek sorumluluktur; ayrı dördüncü teknik rol değildir.

## 1. Rol özeti

| Rol | Ana soru | Ne yapacak? | Ana teknolojiler | Uygun profil |
|---|---|---|---|---|
| **R1 — Data, Features & ML Engineer** | "Sistem neye göre saldırı diyor ve sonuç geçerli mi?" | Dataset, feature extractor, model, split, threshold, ablation, ML metrics | Python, dpkt, pandas, sklearn, joblib | Veri/ML/istatistik seven |
| **R2 — Gateway & Network Security Engineer** | "Sistem gerçek ağ trafiğini gerçekten durduruyor mu?" | netns, routing, capture, windowing, state machine, nftables, conntrack, replay | Linux, Python, Bash, iproute2, nftables, tcpdump | Networking/security/debug seven |
| **R3 — Platform, Telemetry & Observability Engineer** | "Sistemi nasıl çalıştırıyor, kaydediyor, ölçüyor ve gösteriyoruz?" | Mosquitto, PostgreSQL, Grafana, Docker Compose, measurement harness, Pi integration | Docker, MQTT, PostgreSQL, Grafana, Python, Pi/Tailscale | Backend/DevOps/observability seven |

## 2. R1 detay

Ana sahiplik:
- `core/features.py`
- `model/*`
- `scripts/build_sample_pack.py`

Yapacağı işler:
- CICIoT2023 audit
- fixture/sample pack
- feature catalog
- shared feature extractor
- capture-aware split
- Random Forest baseline
- threshold calibration
- feature ablation
- F1/FPR
- unseen-family/device holdout
- optional IF
- optional CIC -> IoT-23 test

R1'in finalde savunacağı:
> "Hangi feature'ları neden kullandık, model nasıl eğitildi, leakage nasıl önlendi ve metrikler ne anlama geliyor?"

## 3. R2 detay

Ana sahiplik:
- `sources/*`
- `gateway/*`
- `lab/*`

Yapacağı işler:
- A -> B -> C netns lab
- routing
- PCAP/live PacketTuple adapters
- 5s tumbling window
- detector interface
- state machine
- nftables
- conntrack
- quarantine/release
- replay harness
- containment leakage counter
- UDS event bridge
- laptop-only fallback demo

R2'nin finalde savunacağı:
> "Bu trafik gerçekten gateway'den geçti, quarantine gerçekten uygulandı ve sink'te trafik gerçekten durdu."

## 4. R3 detay

Ana sahiplik:
- `platform/*`
- `telemetry/*`
- `measure/*`
- `infra/*`

Yapacağı işler:
- Mosquitto
- telemetry adapter
- PostgreSQL schema/consumer
- Grafana dashboards
- Docker Compose
- CPU/RAM/latency harness
- telemetry byte accounting
- Pi5 deployment/benchmark
- Tailscale management access
- run metadata / plots
- G10 telemetry gate

R3'ün finalde savunacağı:
> "Sistem olayları güvenilir şekilde kaydediyor, ölçüyor, görselleştiriyor ve deney sonuçları reproducible."

## 5. Beceri ihtiyacı matrisi

0 = gerekmiyor / 1 = az / 2 = orta / 3 = yüksek

| Beceri | R1 | R2 | R3 |
|---|---:|---:|---:|
| Python | 3 | 2 | 2 |
| Veri analizi | 3 | 0 | 2 |
| Machine Learning | 3 | 0 | 1 |
| İstatistik/metrik | 3 | 1 | 3 |
| Linux terminal | 1 | 3 | 2 |
| Networking | 1 | 3 | 1 |
| Cybersecurity | 1 | 3 | 1 |
| Sistem debugging | 2 | 3 | 2 |
| Backend/API | 1 | 1 | 3 |
| MQTT | 0 | 1 | 3 |
| PostgreSQL | 0 | 0 | 3 |
| Grafana/visualization | 1 | 0 | 3 |
| Docker/DevOps | 0 | 2 | 3 |
| Raspberry Pi | 0 | 2 | 3 |
| Benchmark/measurement | 2 | 2 | 3 |
| Canlı demo altyapısı | 1 | 3 | 2 |

## 6. Ekip seçim formu

Her kişi bunu doldursun:

```text
İsim:

Primary tercih: R1 / R2 / R3
Secondary tercih: R1 / R2 / R3

Python: /3
ML/Data: /3
Linux: /3
Networking: /3
Cybersecurity: /3
Backend/API: /3
Docker/DevOps: /3
PostgreSQL: /3
Grafana: /3
Raspberry Pi: /3
İstatistik/measurement: /3

Özellikle yapmak istediğim:
Özellikle yapmak istemediğim:
Daha önce yaptığım benzer işler:
```

## 7. Team Lead ek sorumluluğu

Team Lead:
- Jira backlog
- `SCHEMA.md`
- ADR
- contract change decisions
- PR cadence
- G8/G10/G13/G15 takibi
- scope control
- release/demo freeze

Team Lead işinin hedefi günde yaklaşık 45–60 dakika; teknik rolünü ezmemeli.

## 8. Ortak işler

| İş | Katılım |
|---|---|
| G1 architecture meeting | 3 kişi |
| Contracts approval | 3 kişi |
| PR review | en az 1 başka kişi |
| G8 core gate | 3 kişi |
| G10 telemetry gate | 3 kişi, R3 lider |
| FPR vs leakage experiment | 3 kişi |
| Pi validation | 3 kişi, R3 organize |
| README | 3 kişi |
| Demo rehearsal | 3 kişi |
| Q&A | 3 kişi |
