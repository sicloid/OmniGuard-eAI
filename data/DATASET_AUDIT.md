# KAN-13 dataset audit — 2026-09-12

Owner: R1 (Onur). Tool: `data/audit.py`. Evidence below is measured, not quoted.
Command form: `python -m data.audit <capture>.pcap --lan <CIDR> --top N`.

Direction is assigned relative to the modelled home LAN: EGRESS (LAN → outside),
INGRESS (outside → LAN), LOCAL (LAN → LAN), OUTSIDE (neither endpoint in the LAN).
The tool assigns no labels and never relabels LOCAL traffic as EGRESS.

## CICIoT2023: not available, and questionable for an egress detector

- The distribution host `cicresearch.ca` is unreachable from this environment:
  TLS connections are reset over the terminal, outside the sandbox proxy, and in a
  browser; the UNB dataset page itself loads, but the download host does not serve.
  Nothing was downloaded, so nothing about it is audited here.
- UNB documents that its attacks are "executed by malicious IoT devices targeting
  other IoT systems within the network". At a home gateway that is LOCAL traffic.
  The V3 acceptance criterion forbids silently relabelling it as EGRESS.

Until the host is reachable, CICIoT2023 cannot be the primary source.

## IoT-23: audited, and EGRESS-dominant

Six captures were downloaded (620 MB) with their Zeek label files.

| Capture | IP packets | EGRESS | INGRESS | LOCAL | OUTSIDE | Span | LAN |
|---|---|---|---|---|---|---|---|
| CTU-Honeypot-Capture-4-1 (benign) | 16,921 | 13,194 | 3,341 | 386 | 0 | 21.9 h | 192.168.1.0/24 |
| CTU-Honeypot-Capture-5-1 (benign) | 397,061 | 138,946 | 253,406 | 2,423 | 2,286 | 5.5 h | 192.168.2.0/24 |
| CTU-Honeypot-Capture-7-1 (benign) | 110,624 | 51,350 | 59,162 | 112 | 0 | 2.6 h | 192.168.1.0/24 |
| CTU-IoT-Malware-Capture-3-1 | 491,301 | 386,577 | 104,688 | 36 | 0 | 36.1 h | 192.168.2.0/24 |
| CTU-IoT-Malware-Capture-8-1 | 16,677 | 14,513 | 2,162 | 2 | 0 | 24.0 h | 192.168.100.0/24 |
| CTU-IoT-Malware-Capture-34-1 | 228,469 | 213,760 | 13,929 | 780 | 0 | 24.0 h | 192.168.1.0/24 |

**Verdict: every audited malware capture is EGRESS-suitable.** The infected device
contacts external addresses directly, so the traffic crosses the boundary this
project models. In 34-1 a single device reaches dozens of external hosts over 24 h;
in 3-1 the dominant pair is one device scanning one external host 46,589 times.

The benign capture is INGRESS-heavy (a device pulling from CloudFront/AWS), but it
still provides 138,946 EGRESS packets, which is what the extractor consumes.

### LAN inference is not guessed

Running 5-1 with the wrong LAN (192.168.1.0/24) reported all 397,061 packets as
OUTSIDE rather than inventing directions. The device is 192.168.2.3. Each capture's
LAN above was confirmed from its own traffic or its Zeek log, and belongs in the
sample-pack manifest (KAN-14) alongside the capture hash.

### Multicast and broadcast are not "outside the home"

4-1's busiest pair is `192.168.1.132 -> 239.255.255.250` with 9,048 packets: SSDP
discovery. That destination is multicast and never leaves the house, yet the plain
"destination outside the LAN" rule counts it as EGRESS. 5-1 shows the same shape for
DHCP broadcast (`0.0.0.0 -> 255.255.255.255`).

Left uncorrected, a benign device's discovery chatter would train and be scored as
outbound traffic, and `uniq_dst_ip` would count addresses no gateway ever forwards.
Before KAN-14 freezes the sample pack, EGRESS must exclude multicast (224.0.0.0/4,
ff00::/8), broadcast (255.255.255.255, subnet broadcast) and link-local
(169.254.0.0/16, fe80::/10) destinations, treating them as LOCAL. This also affects
the R2 source adapter, which applies the same rule, so it needs a shared decision.

### Labels

Labels are per Zeek connection in `conn.log.labeled`, not per packet: the final
columns carry `label` (Benign/Malicious) and a detailed label. Example distribution
for 3-1: 145,597 PartOfAHorizontalPortScan, 5,962 Attack, 4,536 Benign, 8 C&C.
Malware captures therefore contain benign flows too; a capture is not one label.

Proposed window rule for KAN-14, to be frozen in the manifest: a 5-second device
window is malicious when at least one of its packets belongs to a Malicious flow;
windows mixing labels are counted and reported separately, never silently dropped.

## Group counts for the split

`model/split.py` requires at least three independent groups per class. That is now
satisfied: three benign captures (4-1, 5-1, 7-1) and three malware captures (3-1,
8-1, 34-1).

Capture 7-1 ships as six `Somfy-0N` sub-folders recorded from the same device on
different days. They are one parent capture, not six independent groups; splitting
them apart would leak the same device across train and test. Only `Somfy-02` is
used, and the manifest must record 7-1 as a single group.

Three groups per class is the floor, not comfort: capture-level bootstrap intervals
will be wide, and KAN-18 must report them rather than quote a point estimate.

## Recommendation to the team

1. Make IoT-23 the primary dataset for training and evaluation. The measurements
   above show it matches the egress threat model; CICIoT2023 does not, and is also
   unreachable. This is a source change, so it belongs in an ADR (proposed
   [ADR-0004](../docs/adr/0004-dataset-source.md)) rather than in a quiet code edit.
2. Keep CICIoT2023 as a transfer-experiment candidate (KAN-23) if it becomes
   reachable, evaluated with the same extractor.
3. Record LAN, capture hash, label mapping and window rule per capture in the
   KAN-14 manifest; nothing in this audit is a detection result.

## Reproduction

Captures live outside Git in `~/omniguard-data/iot23/<scenario>/`. Hashes:
- `3fb775c0391b6ad313a3f7845e634a277b07c3f6377346c2486ba63e1c22e90c`  CTU-Honeypot-Capture-4-1/2018-10-25-14-06-32-192.168.1.132.pcap
- `f6c2a4808a3fc3d7c01ae7656f1b341a1c7338bcd4d5a371f96280035efcbf79`  CTU-Honeypot-Capture-5-1/2018-09-21-capture.pcap
- `2a32158374fce6635272ff8fc0ff39b88e1e759100a6384b9a2c8b14ad5dc7b6`  CTU-Honeypot-Capture-7-1/2019-07-03-16-41-09-192.168.1.158.pcap
- `c674dc0c8d584fa66e6f00c60df973c5fbacad551c850a76d75ec9952641d00b`  CTU-IoT-Malware-Capture-3-1/2018-05-21_capture.pcap
- `92ec7e2f6658ee4b007d0b816986c46cc0338bc5e2bec6ceaaca566c695e4699`  CTU-IoT-Malware-Capture-34-1/2018-12-21-15-50-14-192.168.1.195.pcap
- `80dcc2602519479ddcde889fa902fee19a76696630811452f8df38888af894f2`  CTU-IoT-Malware-Capture-8-1/2018-07-31-15-15-09-192.168.100.113.pcap
- `aebe40ea0e03b120265a5c7bc140dd9b0d3fe2fce65559e84776b7dd5360e71e`  CTU-Honeypot-Capture-4-1/conn.log.labeled
- `f36db06e7d6ba7364e932a5b003f75835e004b320d70019e8a2f0ba8685d9262`  CTU-Honeypot-Capture-5-1/conn.log.labeled
- `80c3fe2ae1062abf56456f52518bd670f9ec3917b7f85e152b347ac6b6faf880`  CTU-Honeypot-Capture-7-1/conn.log.labeled
- `9851009bbca03e15089fa1a356dd4b5eee4a98161a51703626058a0b507f50d0`  CTU-IoT-Malware-Capture-3-1/conn.log.labeled
- `d69e49b2aae8c1bd33286936531658202dec47d989f0439bad3f8be180467a6e`  CTU-IoT-Malware-Capture-34-1/conn.log.labeled
- `4877ca8f0f01902fbd18d28b7d06cb3d0be082355b7f2c8862c9deef1782eb8a`  CTU-IoT-Malware-Capture-8-1/conn.log.labeled

