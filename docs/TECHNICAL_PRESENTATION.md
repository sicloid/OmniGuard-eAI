# OmniGuard-eAI technical presentation

Suggested duration: 15 minutes plus a 3 minute live demonstration and 2 minutes
for questions. The presentation should show the bounded evidence and the known
limits together; the candidate-model table is validation-only.

## Slide flow and speakers

1. **Problem and goal — Şükrü, 45 s.** Explain that the project detects IoT
   botnet behavior from network observations and applies reversible local
   containment. The objective is a measurable decision-to-enforcement loop,
   not only a classifier score.
2. **System boundary — Şükrü, 45 s.** Show PCAP/live capture, shared extractor,
   detector, N-window policy, nftables, UDS, MQTT, PostgreSQL and Grafana. State
   that the runtime is self-hosted and has no cloud inference dependency.
3. **Contracts and safety — Şükrü, 45 s.** Cover the fixed StateEvent and
   FeatureVector contracts, loss handling, explicit missing observations and
   the rule that inference failure cannot become NORMAL.
4. **Data audit and splits — Onur, 60 s.** Explain parent-group disjoint
   train/validation/test roles, capture provenance, extractor parity and why
   random row splitting would overstate performance.
5. **Frozen baseline — Onur, 45 s.** Introduce the KAN-19 RF artifact and the
   frozen threshold. Separate training evidence, validation evidence and the
   one-shot malware holdout.
6. **Policy decision — Onur, 60 s.** Explain N=2 and lease=300 s. Show that N=1
   produced false quarantines while larger N delayed or missed malicious spans.
   Use the wording: “zero observed false quarantines is not zero risk.”
7. **Where the model fails — Onur, 60 s.** Show the test confirmation: leakage
   rose to 50.6% and the benign test capture contained anomalous windows, so
   the result is not presented as clean generalization.
8. **Candidate improvement — Onur, 60 s.** Show the KAN-67 table: regularized
   ExtraTrees reached 99.16% worst-seed validation recall at the stated FPR
   budget. Emphasize that it is exploratory and has not replaced the frozen
   runtime model or been scored on a new holdout.
9. **Containment evidence — Şükrü, 60 s.** Explain the real Linux G8 path:
   TCP and UDP sink behavior, kernel enforcement, release and expiry. State the
   exact bounded development-validation scope.
10. **Telemetry path — Gabriel, 60 s.** Walk through StateEvent → UDS → MQTT →
    PostgreSQL → Grafana, including framing, peer-credential policy, dedup and
    outage/recovery behavior.
11. **Measurements — Gabriel, 60 s.** Show KAN-42 x86 evidence: inference
    about 40.3 ms, enforcement about 15.6 ms, feature extraction about 13.7 ms,
    policy about 5.0 ms and peak RSS about 128.5 MB. Label these as x86 Docker
    measurements, not Raspberry Pi performance.
12. **Dashboard and operator view — Gabriel, 45 s.** Show a decision, an
    enforcement outcome, a recovered duplicate and the corresponding telemetry
    row. Explain what an operator can verify from the event IDs and timestamps.
13. **Live demo — all, 3 min.** Run the local core demo, then show the retained
    G8/G10 evidence. Make clear which screen is synthetic wiring and which file
    is measured acceptance evidence.
14. **Limitations — Şükrü, 60 s.** State the consumed holdout, benign-device
    generalization gap, invalid Pi timing under constrained power/load, and the
    fact that candidate selection used validation data.
15. **Conclusion and next step — Şükrü, 45 s.** The prototype closes the
    detect-to-contain-to-observe loop with auditable contracts. The next honest
    milestone is a fresh benign-device holdout and independently reviewed
    candidate freeze.

## Demo sequence

From the checked-out repository:

```bash
./demo.sh core
./demo.sh evidence
```

During the demo, first show a normal event, then an anomalous decision, the
N-window transition, containment, release/expiry and the telemetry record. Do
not improvise a claim from a live network. If Docker, nftables or the Pi is
unavailable, use the stored G8/G10 evidence and say which acceptance boundary
it represents.

## Closing Q&A prompts

- **Why not claim 99% accuracy?** Because the 99.16% number is worst-seed
  validation recall for a candidate selected on validation data; it is not a
  fresh-device or unseen-family guarantee.
- **Why N=2?** It removed the observed benign single-window false positives in
  the selection capture while preserving the chosen coverage trade-off.
- **Why local enforcement?** The response path must remain available during
  WAN loss and must be reversible and auditable.
- **Does the Pi meet the x86 latency figure?** No such claim is made. The Pi
  run established functional behavior under its available power/cooling; its
  timing guard invalidated that run for performance estimation.

