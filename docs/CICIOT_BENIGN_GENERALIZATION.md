# CICIoT2023 external benign generalization

The raw 116 GB CICIoT2023 PCAP inventory produced 322,393 benign five-second
windows from 59 stable device identities. The split in
`model/ciciot_benign_spec.json` was committed before either role was scored:
48 devices are development evidence and 11 devices are a one-shot holdout.
A MAC stays in one role across all four source PCAPs.

The frozen KAN-19 Random Forest, threshold 0.9798815486832 and DevicePolicy
N=2/300 s do not generalize to this source:

| Role | Devices | Windows | Window FPR | False quarantines | Quarantines / observed device-hour |
|---|---:|---:|---:|---:|---:|
| Development (KAN-65) | 48 | 243,559 | 19.55% | 1,710 | 5.06 |
| One-shot holdout (KAN-70) | 11 | 78,834 | 21.97% | 532 | 4.86 |

These are external-source results, not deployment prevalence estimates. They show
that strong IoT-23 validation and malware holdout results did not protect against
device/domain shift. The holdout result is reported unchanged and must not be used
to tune a replacement model. Replacement development may use only the declared
CICIoT development devices; the ongoing Raspberry Pi capture supplies fresh
post-selection benign evidence.

## Existing KAN-67 candidate on development devices

The previously trained regularized ExtraTrees candidate was then reproduced on the
same 48 development devices. A preliminary development-only probe had already been
seen, so this is explicitly reproducibility evidence rather than blind confirmation.
The candidate reduced window FPR to 0.957%, false quarantines to 65, and false
quarantines per observed device-hour to 0.192. It was not scored on the consumed
CICIoT holdout. Runtime adoption remains gated on fresh Pi evidence and G8 regression.

## Source audit and adoption decision

CICIoT2023 replaces the previously proposed UNSW-IoTraffic source for this project
because the team now has owner-authorized raw PCAP access and the user explicitly
requested that the downloaded corpus be used. This is a documented source change,
not deletion of the original requirement.

- Source: UNB/CIC IoT Dataset 2023; research use under the access granted by the owner.
- Raw inventory: 60 PCAPs, 116,007,104,493 bytes, each SHA-256 pinned.
- Accepted benign input: four `Benign_Final` PCAPs totaling 6,997,844,681 bytes.
- Shared extractor input: raw PCAP only; prepared CSV features are not used.
- Identity: observed Ethernet source MAC. Ambiguous IP/MAC ownership is excluded.
- Direction: 4,760,725 EGRESS packets after the shared LAN/on-link rules; 484,688
  multicast, broadcast, link-local or unspecified packets were policy-excluded.
- Labels: folder-level declared benign assumption, stated in every capture manifest;
  there is no flow-level benign ground truth.
- Split: 59 stable devices, allocated before scoring; no aggregate is mixed with
  IoT-23 as if the sources represented one population.

The downloaded attack PCAPs stay inventoried but are not admitted merely from their
folder names. Selected Mirai traffic is predominantly LOCAL under the project's
EGRESS semantics, so relabelling it as outbound botnet evidence would invalidate the
feature contract.
