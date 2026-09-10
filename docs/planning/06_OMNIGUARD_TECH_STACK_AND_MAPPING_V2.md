# OmniGuard eAI — Technology Stack & Optional Production Mapping v2

> Tarihsel V2 kaynak belgesi. Güncel yönerge: [AI_SYSTEM_PROMPT](../../AI_SYSTEM_PROMPT.md);
> hedef tasarım: [ARCHITECTURE](../../ARCHITECTURE.md); uygulanan durum: [STATUS](../STATUS.md).
> Aşağıdaki özgün plan/checklist tamamlanma veya yeni ekip onayı kanıtı değildir.

## 1. Prototype stack — implemented

| Need | Prototype technology | Why |
|---|---|---|
| Packet parsing | dpkt | lightweight, reproducible |
| ML | scikit-learn | fast, stable PoC |
| Model persistence | joblib + metadata JSON | reproducibility/compatibility |
| Gateway lab | Linux network namespaces | real routing in isolated host |
| Enforcement | nftables | real reversible egress control |
| Connection state | conntrack | established flow handling |
| Messaging | Eclipse Mosquitto | local/self-hosted MQTT |
| Persistence | PostgreSQL | reliable relational event store |
| Dashboard | Grafana | fast observability without custom UI project |
| Service orchestration | Docker Compose | reproducible local/Pi deployment |
| Metrics | psutil + custom timers | CPU/RAM/latency |
| Shared edge host | Raspberry Pi 5 | ARM64 validation/integration |
| Remote management | Tailscale | private management plane |

## 2. Explicitly not required

- Huawei Cloud account
- IoTDA
- ModelArts
- GaussDB
- FunctionGraph
- managed dashboard
- paid cloud credits

These must not appear in core acceptance criteria.

## 3. Optional production mapping — presentation only

This section is conceptual.

| Prototype | Possible managed-service category |
|---|---|
| Mosquitto | managed IoT/MQTT platform |
| PostgreSQL | managed relational database |
| local sklearn/FastAPI | managed model serving |
| Grafana | managed observability |
| Linux/Pi gateway | suitable edge/container deployment |

If Huawei branding/integration is discussed, phrase it as:

> "The prototype is intentionally portable and self-hosted. In a production Huawei ecosystem, equivalent managed services could be evaluated."

Do not say:
- "drop-in replacement"
- "already integrated"
- "production ready on Huawei"
- "runs on all Huawei ONTs"
