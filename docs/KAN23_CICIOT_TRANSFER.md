# KAN-23 — CICIoT2023 external EGRESS attack transfer

The experiment keeps the IoT-23-trained models fixed and scores a separately
reported CICIoT2023 Backdoor EGRESS stress pack. The pack contains 2,480 windows
from 51 mapped devices. Its malicious label is inherited from the dataset folder;
it is not flow-level ground truth, so the result is a transfer stress test rather
than a deployment recall estimate.

| IoT-23-trained model | Window recall | Devices reaching N=2 | Device recall | Malicious-time blocked |
|---|---:|---:|---:|---:|
| Frozen KAN-19 RF | 25.56% | 9 / 51 | 17.65% | 21.58% |
| KAN-67 ExtraTrees candidate | 6.41% | 2 / 51 | 3.92% | 6.31% |

The candidate's CIC benign development FPR is much better than KAN-19, but this
stress result is worse. It is therefore not adopted automatically. KAN-69 must
preserve the strong IoT-23 attack evidence, evaluate fresh Pi benign traffic and
repeat G8 before changing runtime pins.

The two flood captures were rejected for this EGRESS experiment: 99.50% of the
SYN capture and 99.63% of the UDP capture are LOCAL under the shared LAN direction
contract. Reclassifying that traffic as EGRESS would change the feature meaning.
All 60 PCAPs remain in the hash inventory.
