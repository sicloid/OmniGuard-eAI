# OmniGuard eAI — Architecture & Execution Plan v2

> Tarihsel V2 kaynak belgesi. Güncel yönerge: [AI_SYSTEM_PROMPT](../../AI_SYSTEM_PROMPT.md);
> hedef tasarım: [ARCHITECTURE](../../ARCHITECTURE.md); uygulanan durum: [STATUS](../STATUS.md).
> Aşağıdaki özgün plan/checklist tamamlanma veya yeni ekip onayı kanıtı değildir.

## 1. Final prototype architecture

```text
                 ┌──────────────── ISOLATED LAB ────────────────┐

  IoT Simulator / Replay
            |
            v
      [A: IoT namespace]
            |
            v
      [B: Gateway namespace]
        - capture
        - PacketTuple
        - 5s windowing
        - shared features
        - local RF inference
        - state machine
        - nftables
            |
            v
      [C: Sink namespace]

                 └───────────────────────────────────────────────┘

                         StateEvent
                             |
                             v
                  Unix Domain Socket
                             |
                             v
                  Host Telemetry Adapter
                             |
                             v
                       Mosquitto
                             |
                             v
                   Telemetry Consumer
                             |
                             v
                      PostgreSQL
                             |
                             v
                         Grafana
```

## 2. Network planes

```text
tailscale0   = team management plane
eth0/wlan0   = normal host network
veth/netns   = malicious/controlled lab data plane
```

Kurallar:
- attack/replay traffic public Internet'e çıkmaz
- lab subnet Tailscale üzerinden advertise edilmez
- Tailscale yalnız Pi management/SSH için
- gateway namespace host ruleset'i değiştirmez

## 3. Runtime contracts

```text
Source Adapter
    ↓ PacketTuple
Feature Extractor
    ↓ FeatureVector
Model
    ↓ DetectionResult
State Machine
    ↓ StateEvent
 ┌──┴───────────────┐
 ↓                  ↓
nftables         Telemetry Adapter
                    ↓
              TelemetryPayload
```

Ayrı artifact contract:

```text
model.joblib + model.meta.json
```

## 4. Data flow principles

- offline/live aynı feature extractor
- EGRESS primary detection input
- LOCAL ayrıca ölçülebilir
- L3 byte semantics
- `device_id` abstraction
- no random window split
- validation threshold
- reproducible sample packs

## 5. State policy

Baseline:

```text
NORMAL
  ↓ anomaly
SUSPICIOUS
  ↓ N consecutive anomalies
QUARANTINED
  ↓ timeout/manual release
NORMAL
```

N deney parametresidir.

Ana trade-off:
**daha agresif containment ↔ daha yüksek false positive riski ↔ daha düşük leakage**

## 6. Platform stack

### Mosquitto
StateEvent/TelemetryPayload dağıtımı.

### PostgreSQL
Önerilen minimum tablolar:
- devices
- detection_events
- state_events
- experiment_runs
- resource_metrics

### Grafana
- state
- anomaly score
- latency
- leakage
- CPU/RAM
- telemetry volume

### Docker Compose
Platform bileşenlerini local ve Pi'de aynı şekilde kaldırmak için.

## 7. Raspberry Pi 5

Pi:
- shared integration host
- ARM64 sanity benchmark
- optional primary demo host

Pi değildir:
- tek development environment
- tipik ONT/router SoC temsilcisi
- ekip blocker'ı

Her zaman laptop-only path tutulur.

## 8. 15 iş günlük yürütme

### G1
- architecture workshop
- contracts structure
- netns skeleton
- data audit
- self-hosted platform skeleton
- stubs

### G2
- feature catalog freeze
- schema/versioning
- nftables safety
- environment pin
- sample pack
- Docker Compose/Mosquitto/Postgres smoke test

### G3-G5
- shared extractor
- pcap/live sources
- RF baseline
- dashboard stub
- telemetry consumer
- first measurements

### G6-G7
- state machine
- real quarantine
- replay/t0
- leakage counter
- feature ablation
- UDS bridge

### G8
Core Kill Gate.

### G9-G10
- hardening
- telemetry adapter
- Mosquitto -> PostgreSQL -> Grafana
- G10 telemetry gate

### G11-G12
- N/FPR/leakage
- controlled compute budgets
- Pi validation
- unseen holdout
- optional IF/cross-dataset

### G13
Measurement freeze.

### G14
- demo runbook
- docs
- Q&A
- laptop fallback rehearsal

### G15
- clean checkout
- final release
- final rehearsal

## 9. Kill/cut order if schedule slips

İlk kesilecek:
1. FastAPI remote inference comparison
2. cross-dataset test
3. Isolation Forest
4. sliding window
5. extra dashboard polish

Kesilmeyecek:
- shared extractor
- RF baseline
- capture-aware split
- G8 real containment
- Mosquitto/PostgreSQL/Grafana basic telemetry
- core metrics
- containment leakage
- laptop fallback
