# OmniGuard eAI — G1 Architecture Decision Checklist v2

> Tarihsel V2 kaynak belgesi. Güncel yönerge: [AI_SYSTEM_PROMPT](../../AI_SYSTEM_PROMPT.md);
> hedef tasarım: [ARCHITECTURE](../../ARCHITECTURE.md); uygulanan durum: [STATUS](../STATUS.md).
> Aşağıdaki özgün plan/checklist tamamlanma veya yeni ekip onayı kanıtı değildir.

İlk 60–90 dakikalık toplantıda karara bağlanacaklar:

## Contracts
- [ ] PacketTuple fields
- [ ] FeatureVector envelope
- [ ] DetectionResult
- [ ] StateEvent
- [ ] TelemetryPayload
- [ ] Model artifact contract

## Network semantics
- [ ] `device_id` semantics
- [ ] `direction = EGRESS / INGRESS / LOCAL`
- [ ] `packet_length = L3 IP packet length`
- [ ] EGRESS primary detection input
- [ ] LOCAL measurement policy

## Data / ML
- [ ] CICIoT2023 primary
- [ ] IoT-23 secondary
- [ ] 5s tumbling baseline
- [ ] feature catalog freeze G2
- [ ] capture-aware split
- [ ] random window split prohibited
- [ ] RF primary
- [ ] IF stretch
- [ ] threshold validation-only

## Lab / enforcement
- [ ] A->B->C netns architecture
- [ ] no public Internet route from lab
- [ ] nftables only in gateway netns
- [ ] no host `nft flush ruleset`
- [ ] conntrack handling policy
- [ ] t0/replay marker method
- [ ] containment leakage = L3 bytes/packets

## Platform
- [ ] Mosquitto chosen
- [ ] PostgreSQL chosen
- [ ] Grafana chosen
- [ ] Docker Compose chosen
- [ ] telemetry consumer responsibility
- [ ] PostgreSQL minimum schema
- [ ] Grafana minimum panels
- [ ] no managed cloud dependency

## Gateway -> platform
- [ ] Unix domain socket bridge
- [ ] telemetry topic naming
- [ ] TelemetryPayload versioning

## Pi / remote access
- [ ] Pi = shared integration + ARM64 sanity
- [ ] Tailscale = management only
- [ ] no lab subnet advertisement
- [ ] benchmark contamination guard
- [ ] laptop-only fallback required

## Measurement
- [ ] single-host monotonic timing
- [ ] CPU/RAM methodology
- [ ] telemetry byte methodology
- [ ] adapter compute-cost accounting
- [ ] cgroup result title = controlled compute budget
- [ ] Pi results separate from x86

## Gates
- [ ] G5 independent components
- [ ] G8 core kill gate
- [ ] G10 telemetry & observability gate
- [ ] G13 measurement freeze
- [ ] G15 demo release

## Engineering process
- [ ] Jira Kanban workflow
- [ ] WIP policy
- [ ] CODEOWNERS
- [ ] short-lived feature branches
- [ ] ADR process
- [ ] AI-generated code review rule
- [ ] secret handling rule
