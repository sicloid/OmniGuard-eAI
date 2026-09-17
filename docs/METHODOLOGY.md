# OmniGuard eAI — methodology and limitations (KAN-57)

Owner: R1 (Onur), with Lead review. **Status: draft, 17 September 2026.**

This document states how the detection results are produced, what each result may be
used to claim, and what it may not. It collects rules that are already enforced in code
and recorded in ADRs; it adds no new rule. Sections that depend on experiments not yet
run say so. Where a number appears, the linked result document is the authority.

| Prerequisite (from the card) | State on 17 September |
|---|---|
| Capture-aware train/validation/test split (KAN-17) | Done, in `model/split.py` |
| Validation-only threshold calibration (KAN-19) | Done, frozen in `model/frozen/kan19-seed1/` |
| FPR / containment leakage main experiment (KAN-52) | **Not run.** Sections 8 and 9 stay provisional until it is |

## 1. What the system claims to do, and what it does not

The system flags an IoT device whose **outbound (EGRESS) traffic behaviour** at the home
gateway looks malicious, using payload-free per-window features. It then applies a
**time-limited, reversible** restriction on that device's WAN egress (ARCHITECTURE.md,
"Amaç").

Out of scope, and never claimed:

- finding every threat on the network, or detecting attacks that stay inside the LAN;
- cleaning a device, or treating a release as "the device is clean";
- selectively blocking only the malicious connections: quarantine restricts the
  device's WAN egress as a whole;
- stopping lateral movement: a quarantined device can still reach the LAN;
- a general home-network result: every result applies only to the captures it was measured on.

## 2. Data

### 2.1 Sources and roles (ADR-0004)

Every result states which role its data came from.

| Role | Data | May be used for | Status |
|---|---|---|---|
| Development | Six audited IoT-23 captures: benign 4-1, 5-1, 7-1; malware 3-1 (Muhstik), 8-1 (Hakai), 34-1 (Mirai) | Training, validation, threshold, ablation, N sweep, exploratory folds | In use. Every capture has already been on a test or validation side (KAN-18, KAN-21), so **nothing here is untouched** |
| Untouched malware holdout | IoT-23 48-1 (Mirai), 20-1 (Torii), 36-1 (Okiru), selected by a pre-committed rule | Scoring **once**, after the freeze in §5 | Selected (`data/holdout/selection.json`), not downloaded, never scored |
| Untouched benign holdout | None exists. IoT-23 publishes three benign scenarios, all used | — | Until one exists, holdout reports say "untouched benign FPR: not measured" |
| External transfer | CICIoT2023 (KAN-23) | A separate transfer test, never a substitute for the holdout | Not accessible; its attacks are mostly LAN-local |

The ADR as a whole is still PROPOSED. The Lead approved the holdout selection rule and
download budget on 14 September. A second benign source (UNSW-IoTraffic) needs a
separate decision.

### 2.2 Labels

- **Window label rule `window-label-1`** (`data/samplepack/build.py`):
  - a window is malicious if any of its EGRESS packets matches a Malicious flow in the
    capture's Zeek `conn.log.labeled`;
  - it is unknown if any packet is unmatched or ambiguous;
  - it is benign only if every packet matched a Benign flow.
- **Unknown windows** (29 in the pack) are excluded from training and scoring, never
  folded into benign.
- **Pinning:** manifest v2 records the rule version, and a test pins the rule text to it.
- **Declared label:** 7-1's benign label is declared from the dataset description, not
  measured; any result that trains or validates on 7-1 inherits that assumption.
- **Malware captures are not uniformly malicious:** they contain benign flows (3-1: 4,
  8-1: 1,036, 34-1: 930 benign windows). These windows come from the infected device, so
  their false-positive rate is **not** a benign-device FPR.

### 2.3 Pack integrity

- **What training uses:** only a hash-pinned sample pack.
  - `windows.jsonl` SHA-256 `4b97fb95…`.
  - manifest v1 `65c7184c…` and v2 `8ea8c310…`.
- **Checks:** every runner refuses a pack whose windows do not match its manifest, and
  refuses a pack other than the one its spec names.
- **Provenance:** each result records pack, split, model, metadata and policy hashes.
- **What the hashes are:** SHA-256 pins, not signatures.

## 3. From packets to features

- **Observation point:** one capture point on the LAN side. Offline, classic PCAP goes
  through the same `PacketNormalizer` and the same pure extractor as live capture.
- **Direction:** EGRESS means the source is in the configured LAN and the destination is
  outside it and not policy-excluded.
  - Multicast, limited broadcast, link-local and unspecified destinations count as LOCAL
    (`sources/scope.py`).
  - This is a feature policy, not proof that the traffic stayed on the link.
- **Windows:** 5 s, half-open, epoch-aligned, per device.
  - A window with no EGRESS yields no vector.
  - A capture truncated mid-record loses its still-open window rather than padding it.
- **Features:** `features-1`, 14 metadata-only values per window
  (`data/FEATURE_CATALOG.md`).
  - Volume: packet and byte counts and statistics.
  - Destinations: distinct IPs and ports, top-destination share.
  - Protocol mix.
  - Connection behaviour: SYN-only, RST, portless share, active span.
  - Never used as features: identity (device, MAC, IP), raw port numbers, labels,
    capture names or payload.

**"Metadata-only" is a limit, not a privacy guarantee.**
- **Payloads:** never parsed, stored or sent.
- **Metadata:** IP, MAC and port are still processed locally and are themselves
  sensitive.
- **Not certified:** being payload-independent is not anonymity and not a legal
  compliance certificate (ARCHITECTURE.md, "Artifact ve veri yaşam döngüsü").
- **Encrypted traffic:** handled only in the sense that its payload is never needed.

## 4. Splitting

- **Unit:** a capture is one group. Windows of one capture never cross split boundaries
  (`model/split.py`, KAN-17). Derived excerpts of the same PCAP are not separate groups.
- **Consequence:** with six groups, each split holds about one benign and one malware
  capture. Every development run trains on one benign device.
  - KAN-18 shows this dominates the results: window FPR at 0.5 ranged 0.0001–0.80
    depending only on which benign capture was trained on.
- **Order of use:**
  - fitting and any feature choice use train only;
  - threshold, N and lease candidates use validation only;
  - test is only for candidates already frozen.
- **Frozen threshold has not yet been scored on test:**
  - The KAN-19 run never scored its test split, and the KAN-20 ablation never scored any test split.
  - The only test-side numbers so far are the exploratory KAN-21 folds; their test
    captures were scored under per-fold thresholds, not the frozen one.
- **Leave-one-family-out (KAN-21):** 18 folds rotate every capture through test.
  - Those numbers are exploratory.
  - They must not be used to tune features, thresholds or N and then be re-scored on
    the same captures.

## 5. Threshold and policy selection

- **Model score:** the RF score is a score, not a calibrated probability.
  `score >= threshold` means ANOMALOUS.
- **How the threshold is chosen** (`model/calibrate.py`):
  - on validation only, under a window-FPR budget of **1 %**, approved by the Lead on
    14 September;
  - objective `max_recall_at_fpr`;
  - the code refuses `selected_on="test"`;
  - if no threshold meets the budget, that is reported and the budget is never relaxed.
- **Specs committed before runs:** KAN-19 (`operating_policy_spec.json`) and KAN-20
  (`ablation_spec.json`) commit their spec before the run. Each fixes seeds, budget,
  objective, model settings and, for KAN-19, which seed may become the operating policy.
  Sensitivity seeds are reported but can never replace the declared seed.
- **Frozen policy:** seed 1, threshold `0.9798815486832`.
  - Hashes are in `docs/KAN19_POLICY.md`.
  - Selecting and scoring on the same validation windows makes its 0.945 recall
    optimistic.
- **Holdout freeze (ADR-0004 decision 7b).** Before the holdout is scored, these are
  recorded and hashed:
  - `feature_schema_version`;
  - model and metadata hashes;
  - threshold policy hash;
  - N and lease;
  - development pack hash.
  - **Current state:** all of these except N and lease are recorded, so the holdout
    stays unscored. It is scored once, and the result is reported whatever it is.
    Tuning after that consumes it.

### What the threshold results already show

- **The budgeted threshold is not stable across splits.** It is 0.98, 0.995 and 0.41 for
  seeds 1–3, with recall 0.95, 0.27 and 0.86 (KAN-19).
- **It does not transfer between benign devices.** In KAN-21, three of the twelve folds
  that found a threshold gave 12.6 % or 63.1 % FPR on an unseen benign capture. In 6 of
  18 folds, no threshold met the budget at all.
- **Recall at 1 % sits on a score cliff** (KAN-20, PR #35).
  - Near the top, the 200-tree forest scores in steps of about 0.005.
  - A 2,055-window validation set allows about 20 false positives.
  - Once more benign windows than that share the top levels, the threshold jumps and
    recall collapses. Average precision barely moves.
  - Small changes, such as dropping one feature, can move recall at the budget from
    0.95 to 0.33.

These are reasons **not** to freeze one runtime threshold from IoT-23 validation data
and call it a deployment operating point.

## 6. Feature ablation and cost (KAN-20, in review)

- **Setup:** 29 declared subsets of `features-1`, validation only, same budget, three
  seeds. The compact-set rule was fixed before the run; its 0.02 tolerance is awaiting
  Lead review.
- **Volume features are required.** Without them no seed calibrates.
- **Protocol mix is the only group whose removal passed the rule.** This is a
  dev-pack observation, and the finalist is tentative because of the cliff above.
- **Feature count is not the cost lever.**
  - Extraction takes about 1–4.5 µs per window.
  - One `predict_proba` call takes about 4.2 ms on a development Mac.
- **Timings:** development-machine rankings, not gateway measurements. Gateway
  CPU/RAM/latency come from the KAN-42 harness on finalists.

## 7. Uncertainty

- **Bootstrap level:** intervals are bootstrapped at capture level, never window level,
  because windows of one capture are not independent.
- **What that yields here:** with one capture per class per split, capture-level
  resampling degenerates.
  - Recall intervals collapse to a point.
  - FPR intervals span nearly the whole range.
  - These are reported as degenerate, not as confidence intervals.
- **Seeds:** variation across seeds changes which captures are in each split. It is
  reported as sensitivity, not averaged into one number.
- **Zero false positives:** zero observed false quarantines is not zero risk. The
  number of independent benign device-hours is reported next to any such figure.
- **Consecutive windows are not independent.** `FPR^N` is never presented as the
  false-quarantine probability.

## 8. Known confounds

- **Device type.** Every IoT-23 malware capture ran on a Raspberry Pi; every benign
  capture is a real consumer device.
  - "Detected unseen family" may mean "detected Raspberry Pi traffic".
  - KAN-21 cannot separate the two.
  - A second benign source would weaken this explanation, but only a benign Raspberry
    Pi baseline or a device-type-matched malware capture would test it directly.
- **Family equals capture.** One capture per family means family, device, network and
  recording date are a single variable.
- **Environment and period.** IoT-23 was recorded in Prague, 2018–19. Resolvers, cloud
  endpoints and protocol shares can reveal the lab.
- **Scale-sensitive features.** Packet and byte counts and the destination count can
  encode "which device" rather than "what behaviour". KAN-20 shows detection leans
  most on volume, which leaves this concern open rather than resolving it.
- **Declared labels:** 7-1, and UNSW if adopted.

## 9. Proof-of-concept limits

These hold for every result, whatever the numbers:

- **Traffic coverage.** The lab design is IPv4-only with IPv6 disabled (ARCHITECTURE.md).
  No containment claim covers IPv6.
  - Leakage is measured from independent sink and forwarding evidence, not by filtering
    on EGRESS.
  - An unobserved path or address family is unmeasured, never "zero leakage".
- **Replay is not a live botnet.** PCAP replay does not reproduce an adaptive attacker.
  Replayed traffic is labelled as a lab transformation.
- **Timing.**
  - Decision latency for N consecutive windows is phase-dependent, roughly
    `(N−1)·5 s` to `N·5 s` plus processing.
  - N=3 is not a fixed "15 s".
  - Attacks that are never detected are kept, as escape or censored latency, not
    dropped.
- **Failure policy.** On model or health failure, no new quarantine starts and an
  existing lease runs out.
  - This favours availability, so attack traffic can escape during a fault; that
    escape is measured.
  - Fail-closed operation is out of scope.
- **Artifacts.** A model is trusted only by hash against a trusted record. Loading
  joblib can execute code, so the model process holds no enforcement privilege.
- **Hardware.** Results are from x86 or Apple-silicon development machines unless a Pi
  run is recorded; no Pi/ARM64 result is inferred.
- **Scale.** Six development captures, three benign devices, three malware families.
  No statement generalises beyond them.

## 10. How results may be worded

| Allowed | Not allowed |
|---|---|
| "On the six IoT-23 development captures, validation recall at a 1 % window-FPR budget was 0.945 (seed 1); other splits gave 0.27 and 0.86." | "The detector has 94.5 % recall." |
| "Held-out families were still flagged in most KAN-21 folds; the Raspberry Pi confound was not controlled." | "The model detects unseen malware." |
| "Window FPR on validation was 0.68 %; untouched benign FPR has not been measured." | "False-positive rate is under 1 %." |
| "Payload is never read; IP/MAC/port metadata is processed locally." | "The system is privacy-preserving / GDPR compliant." |
| "Quarantine restricts the device's WAN egress for a bounded lease." | "OmniGuard blocks the malicious connection." / "Release means the device is clean." |
| "No false quarantine was observed in X independent benign device-hours." | "OmniGuard causes no false quarantines." |

## 11. Open items before this document is final

1. **KAN-52:** measure false quarantine per device-hour, benign blocked time and
   L3 leakage, and replace the provisional wording in §8–9 with the measured result.
2. **KAN-51:** choose and record N and lease. Then score the holdout once and add the
   result under its own heading, including "untouched benign FPR: not measured" unless
   a benign holdout exists by then.
3. **Lead review:** the whole document, the KAN-20 tolerance, and ADR-0004's remaining
   open decisions.
4. **If UNSW-IoTraffic is approved:** add its device-level holdout split (ADR-0004
   decision 7c) and the repeated KAN-21 folds to §2, §4 and §8.
