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
7. **Where the frozen model fails — Onur, 60 s.** Show both failure boundaries.
   Its internal test confirmation leakage rose to 50.6%. On device-disjoint
   CICIoT2023 benign traffic it produced 19.55% development FPR and 21.97%
   one-shot holdout FPR, with 532 false quarantine episodes on the 11 holdout
   devices. These are reported as failures, not hidden by the original
   validation score.
8. **Candidate improvement and trade-off — Onur, 75 s.** Show that the existing
   regularized ExtraTrees candidate reduced CIC benign development FPR to
   0.957% and false quarantines to 0.192 per observed device-hour. Then show the
   cost: on the folder-labelled CIC Backdoor EGRESS stress set its window recall
   was 6.41%, versus 25.56% for KAN-19. On the fresh Pi run, KAN-19 produced
   75.00% FPR, ten false quarantines and 2,980 blocked seconds; the candidate
   produced zero anomalous windows and zero quarantine across 328 windows.
   The candidate is therefore selected for the bounded competition/demo
   runtime profile, while neither model supports a general production-IDS claim.
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
14. **Limitations — Şükrü, 60 s.** State the consumed holdout, one-device-hour
    Pi boundary, constrained-power/non-performance Pi scope, candidate selection
    on development data, and the conflict between benign FPR and external attack
    recall. The CIC Backdoor folder label is not packet-level ground truth.
15. **Conclusion and next step — Şükrü, 45 s.** The prototype closes the
    detect-to-contain-to-observe loop with auditable contracts. The selected
    demo profile controls benign disruption on both CIC and fresh Pi evidence;
    the next honest milestone is improving unseen-family recall without losing
    that safety property.

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
  run establishes functional and fresh-benign behavior under the available
  supply and an externally powered 100% fan. `get_throttled`, temperature and
  load are retained, but the run is not a full-power Pi performance estimate.
- **Why deploy the candidate despite lower Backdoor stress recall?** The bounded
  competition/demo profile must avoid disrupting a benign device: KAN-19 blocked
  2,980 seconds in the fresh Pi hour, while the candidate caused no quarantine
  and also met the IoT-23 validation and hash-pinned G8 gates. We disclose the
  6.41% external stress recall and do not call it a production IDS.
