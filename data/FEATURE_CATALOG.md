# Feature catalogue v1 — `features-1`

Owner: R1 (Onur). Cards: KAN-15 (catalogue) and KAN-16 (extractor).
Implementation: `core/features.py`. Tests: `tests/test_features.py`.

Status: **v1 proposal pending the KAN-13 data audit.** The catalogue is fixed
here so the extractor, the model artifact (`feature_order` in `model.meta.json`)
and R2's `DetectorSpec` share one definition. The KAN-13 audit may remove
features that leak collection conditions. Any change to names, order, units or
definitions bumps `FEATURE_SCHEMA_VERSION`, and an artifact trained on an old
version is rejected by `model.artifact.load_model`.

## Scope and inputs

- Input: the `PacketTuple`s of **one device** in **one** 5-second, half-open,
  epoch-aligned window `[window_start, window_start + 5)` (see `SCHEMA.md`).
- Only `Direction.EGRESS` packets contribute. INGRESS and LOCAL packets in the
  same window are ignored; they are not an error.
- Only header metadata already present in `PacketTuple` is used. No payload
  bytes are read, stored or needed.
- `n` = number of EGRESS packets in the window, always ≥ 1 when a vector exists.

## Features (order is significant)

| # | Name | Unit | Definition |
|---|---|---|---|
| 1 | `pkt_count` | packets | `n` |
| 2 | `l3_bytes_sum` | bytes | Σ `packet_length` (L3 IP length, excludes Ethernet) |
| 3 | `l3_bytes_mean` | bytes | `l3_bytes_sum / n` |
| 4 | `l3_bytes_std` | bytes | population standard deviation of `packet_length` |
| 5 | `uniq_dst_ip` | count | number of distinct `dst_ip` |
| 6 | `uniq_dst_port` | count | number of distinct non-null `dst_port` |
| 7 | `max_dst_ip_share` | ratio [0,1] | packets to the most-contacted `dst_ip` / `n` |
| 8 | `tcp_share` | ratio [0,1] | packets with protocol 6 / `n` |
| 9 | `udp_share` | ratio [0,1] | packets with protocol 17 / `n` |
| 10 | `icmp_share` | ratio [0,1] | packets with protocol 1 (ICMP) or 58 (ICMPv6) / `n` |
| 11 | `syn_only_share` | ratio [0,1] | TCP packets with SYN (0x02) set and ACK (0x10) clear / `n` |
| 12 | `rst_share` | ratio [0,1] | TCP packets with RST (0x04) set / `n` |
| 13 | `portless_share` | ratio [0,1] | packets whose `dst_port` is null / `n` |
| 14 | `active_span_s` | seconds | last − first EGRESS timestamp in the window; 0 when `n = 1` |

Every share is divided by `n`, never by a sub-count that can be zero. So every
feature is defined for every window that yields a vector, and no imputation is
needed. All values are emitted as finite Python floats.

**Why these:** they describe *how much* a device sends (1–4), *to how many places*
(5–7), *with which protocol mix* (8–10), and *how connections behave* (11–14).
Scans, floods and botnet propagation change these at the gateway without any
payload inspection. The set is deliberately small (14), because each feature is a
per-window cost on a resource-constrained gateway. KAN-20 ablation measures
which ones earn their cost.

## Excluded on purpose

- `device_id`, `src_mac`, `src_ip`, `dst_ip` as values: identity, not behaviour;
  they would let a model memorise the testbed. IPs are used only for counting.
- Raw port numbers as numeric values: ports are categorical, and their numeric
  distance is meaningless. Only the count of distinct ports is used.
- Labels, capture/file names, run IDs: never features (see `SCHEMA.md`, V3 KAN-15).
- Ready-made CICIoT2023 CSV features: the live gateway cannot reproduce them from
  `PacketTuple`. Training must use this extractor on PCAP-derived windows.

Caveat for evaluation: permitted metadata such as distinct destination counts
can still reveal collection conditions (for example, a testbed's fixed victim
set). Leakage is checked with capture-grouped splits (KAN-17), not assumed away.

## Edge cases

| Situation | Behaviour |
|---|---|
| No EGRESS packet in the window | `extract_features` returns `None`. "No outbound traffic" is not a zero vector and not a NORMAL score. |
| Packet outside `[start, start + 5)` | `FeatureError`. The end is exclusive: a packet at `start + 5` belongs to the next window. |
| Packet from another `device_id` | `FeatureError`. |
| `window_start` not a multiple of 5 | `FeatureError`. |
| ICMP / ICMPv6 | Ports are null and counted in `portless_share`; not counted in `uniq_dst_port`. |
| Noninitial IP fragment | Ports are null (set by the R2 source adapter, never guessed); counted as portless. |
| TCP SYN+ACK | Not SYN-only (ACK set). |
| Input order | Irrelevant. Features are computed from sets, sums and min/max. |

Capture loss, queue overflow and stale windows are detected upstream (R2
`TumblingWindows` invalidation, ADR-0002 ObservationHealth). Such windows must
not reach the extractor as if they were complete.

## Numerical tolerance

The same code runs offline and live, so parity is exact on one platform.
Across platforms (x86_64 vs ARM64, KAN-53), compare counts exactly and
means/std/shares/span with `math.isclose(rel_tol=1e-9, abs_tol=1e-12)`.

## Versioning

`FEATURE_SCHEMA_VERSION = "features-1"`. A new version is required for any
change to the set, order, units, direction policy or edge-case behaviour. The
model artifact records the version and order it was trained on. A mismatch
refuses loading instead of silently mis-ordering inputs.
