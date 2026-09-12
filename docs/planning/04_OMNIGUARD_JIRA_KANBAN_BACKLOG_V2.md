# OmniGuard eAI — Jira Kanban Backlog v2

> Tarihsel V2 kaynak belgesi. Güncel yönerge: [AI_SYSTEM_PROMPT](../../AI_SYSTEM_PROMPT.md);
> hedef tasarım: [ARCHITECTURE](../../ARCHITECTURE.md); uygulanan durum: [STATUS](../STATUS.md).
> Aşağıdaki özgün plan/checklist tamamlanma veya yeni ekip onayı kanıtı değildir.

## Jira setup

- Project: **OmniGuard eAI**
- Current project key: **KAN**
- Board: Kanban
- Issue types: Epik / Görev / Hikaye / Feature / Hata / Subtask
- No sprint dependency.

Recommended workflow:

```text
TO DO -> IN PROGRESS -> IN REVIEW -> DONE
                   \-> BLOCKED
```

Recommended labels:

```text
role-ml
role-gateway
role-platform
architecture
integration
experiment
stretch
pi
security
docs
g8
g10
g13
g15
```

Branch convention:

```text
feat/KAN-XX-short-name
fix/KAN-XX-short-name
exp/KAN-XX-short-name
docs/KAN-XX-short-name
```

Assignee'lar ekip üyeleri Jira hesaplarını açtıktan sonra role göre atanacaktır.

---

# EPIC E0 — Architecture & Foundation

| Task | Owner Role | Target | Acceptance |
|---|---|---|---|
| G1 architecture workshop | Lead + all | G1 | 5 data + 1 artifact contract; data/network/platform decisions recorded |
| Schema types/versioning | Lead + R1/R2 review | G1-2 | PacketTuple/FeatureVector/DetectionResult/StateEvent/TelemetryPayload typed/tested |
| Model artifact contract | R1 | G2 | joblib+meta; feature order/version/window/threshold/hash/env; fail-fast mismatch |
| Environment pinning | R3 | G1-2 | Python/dependencies pinned, clean setup passes |
| CI + CODEOWNERS | Lead + R3 | G2 | install/lint/unit/schema tests + owner review |
| Dev stubs | Shared | G1 | fake_features/fake_detector/fake_telemetry deterministic |

# EPIC E1 — Dataset, Features & ML

| Task | Owner | Target | Acceptance |
|---|---|---|---|
| CICIoT2023 audit | R1 | G1-2 | capture/label/device mapping documented |
| Fixture/sample pack builder | R1 | G2-3 | script+manifest+hash, large data outside Git |
| Feature catalog v1 | R1 | G2 | practical payload-independent set, order/unit documented |
| Shared pure feature extractor | R1 | G3-4 | PacketTuple[] -> FeatureVector, no I/O, oracle tests |
| Capture-aware split | R1 | G4 | no random window leakage, reproducible manifest |
| RF baseline | R1 | G5 | Precision/Recall/F1/FPR + model artifact |
| Threshold calibration | R1 | G5-6 | validation-only threshold |
| Feature ablation | R1+R3 | G6-7 | reduced feature sets + detection + cost |
| Unseen holdout | R1 | G11 | separate methodology/result |
| Isolation Forest [stretch] | R1 | G11-12 | benign-only train; score not probability |
| CIC -> IoT-23 [stretch] | R1 | G11-12 | same extractor; label harmonization; separate result |

# EPIC E2 — Gateway, Lab & Enforcement

| Task | Owner | Target | Acceptance |
|---|---|---|---|
| Isolated A->B->C netns | R2 | G1 | traffic through B, no public lab route |
| nftables safety + conntrack | R2 | G2 | gw netns only, no host flush, established bypass tested |
| PCAP PacketTuple adapter | R2 | G2-3 | canonical tuple, direction/L3 semantics, oracle count |
| Live PacketTuple adapter | R2 | G3-4 | same tuple, packet-loss sanity |
| 5s tumbling window | R2 | G4 | per-device windows + boundary tests |
| Detector interface | R2 | G4-5 | model-independent gateway interface |
| State machine | R2 | G5-6 | N configurable, timeout/release, StateEvent |
| Real quarantine/release | R2 | G6 | sink proves traffic stop/restore |
| Replay harness + t0 | R2 | G6-7 | reproducible run IDs/logs |
| Containment leakage | R2+R3 | G7 | L3 byte/packet t0->containment |
| UDS event bridge | R2+R3 | G7-8 | gateway -> host without lab Internet route |
| Laptop-only demo | R2 | G12-14 | full core demo without Pi/Tailscale |

# EPIC E3 — Platform, Telemetry & Observability

| Task | Owner | Target | Acceptance |
|---|---|---|---|
| Docker Compose platform skeleton | R3 | G1-2 | Mosquitto/PostgreSQL/Grafana services up |
| Mosquitto broker config | R3 | G2-3 | local MQTT pub/sub works, config documented |
| Telemetry adapter | R3 | G3 | fake/real StateEvent -> TelemetryPayload/MQTT |
| PostgreSQL schema | R3 | G3-4 | minimum tables + migration/init script |
| Telemetry consumer | R3 | G4 | MQTT events persist to PostgreSQL |
| Grafana dashboard stub | R3 | G4-5 | state/score/time visible from fake data |
| Measurement harness | R3 | G5-6 | CPU/RAM/latency run metadata |
| Telemetry volume accounting | R3 | G6 | actual bytes/run/time methodology |
| Pi5 + Tailscale management | Lead+R2/R3 | G4-6 | private management, no lab subnet advertisement |
| Controlled compute-budget benchmark | R3+R1 | G11-12 | cgroup documented; not called router emulation |
| Pi contamination guard | R3 | G11 | load/throttle pre/post; bad runs invalid |
| FastAPI remote inference [stretch] | R3+R1 | G12 | only after G8/G10, local inference remains |

# EPIC E4 — Integration & Experiments

| Task | Owner | Target | Acceptance |
|---|---|---|---|
| Stub-based E2E | Lead+R2 | G5 | deterministic state/enforcement test |
| G8 Core Kill Gate | Whole team | G8 | traffic->extractor->RF->state->nftables->sink stop->release |
| G10 Telemetry Gate | R3+team | G10 | StateEvent->UDS->MQTT->Postgres->Grafana |
| N vs FPR vs delay | R1/R2/R3 | G11 | agreed N values, reproducible |
| FPR vs Containment Leakage | Whole team | G12-13 | headline plot from measured raw data |
| Pi ARM64 validation | Whole team | G12 | separate Pi result, environment/load recorded |
| G13 Results Freeze | Lead | G13 | main metrics/plots frozen |

# EPIC E5 — Docs, Demo & Presentation

| Task | Owner | Target | Acceptance |
|---|---|---|---|
| Reproducible README | Team | G10-13 | setup/data/train/lab/platform/G8/G10/Pi/fallback |
| Architecture diagrams | R3+Lead | G12 | runtime + management/data plane |
| Methodology/limitations | R1+Lead | G13 | split/threshold/metadata-only/PoC limits |
| Demo runbook | Team | G14 | Pi path + laptop fallback + cleanup |
| Q&A knowledge transfer | Team | G14-15 | everyone explains all contracts/core trade-offs |
| Final release | Lead | G15 | clean checkout, G8/G10 pass, release tag |

## Kanban policy

WIP önerisi:
- kişi başı aynı anda max 1 major issue IN PROGRESS
- ekip toplam max 3 major issue IN PROGRESS
- BLOCKED issue'nun blocker açıklaması zorunlu
- PR açıldığında issue IN REVIEW
- acceptance criteria + tests geçmeden DONE değil

## Gate labels
- G8 issue'ları: `g8`
- G10 issue'ları: `g10`
- G13 issue'ları: `g13`
- G15 issue'ları: `g15`
