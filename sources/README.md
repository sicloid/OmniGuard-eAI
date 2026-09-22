# R2 — Şükrü

Implemented: `sources.from_pcap.read_pcap` and shared `PacketNormalizer`.
KAN-27 live adapter: see [LIVE.md](LIVE.md) for Linux capture, loss semantics and
isolated validation. Feature extraction remains Onur's KAN-16.

KAN-66 adds [`sources.benign_capture`](benign_capture.py), a bounded raw-PCAP
collector for controlled, device-scoped benign **evaluation**. It writes evidence
outside Git and does not load a model, change policy, or claim flow-level labels.
Its protocol and acceptance boundary are in
[`docs/KAN64_BENIGN_GENERALIZATION_PROTOCOL.md`](../docs/KAN64_BENIGN_GENERALIZATION_PROTOCOL.md).

```sh
python -m sources.from_pcap capture.pcap --lan 10.203.1.0/24 --devices devices.json
```

`devices.json`: `{"10.203.1.2": "camera-1"}`. Mapping is explicit and must belong
to a configured LAN. Repeat `--lan` for more LANs. Stdout is PacketTuple JSONL;
stderr contains input/emission/filter/error counts. Exit 2 means rejected input;
discard partial output on failure. No packet bytes are emitted.

Supported: classic PCAP (micro/nanosecond, either endianness), Ethernet, up to two
802.1Q/QinQ tags, raw IP, Linux cooked v1/v2; IPv4/IPv6 TCP/UDP metadata.
PCAPNG is rejected explicitly (mixed-interface support requires a future adapter).
IPv6 extension walking is bounded; ESP remains opaque. No reassembly, jumbograms,
checksum validation or source-MAC-based identity inference. NIC offload captures
with zero/truncated IP lengths are rejected rather than treated as valid measurements.

Noninitial fragments emit null ports and zero flags. First fragments missing a
complete transport header also emit null ports. Invalid unfragmented transport
headers fail fast. Outside-LAN, unmapped devices and non-IP traffic are counted
and filtered. LOCAL uses source device identity; INGRESS uses destination identity.
A LAN source sending to a destination excluded by feature policy (multicast,
limited broadcast, link-local, unspecified; see `scope.py`) is LOCAL, not EGRESS, and
is counted in `stats.on_link`. The sample-pack builder relies on the same rule.
SLL/SLL2 src_mac is null because cooked sender address need not be the IP source.

Oracle tests use independently constructed packet bytes and a temporary PCAP,
including Ethernet padding, directions, VLAN, fragments, cooked/raw and IPv6.
Reference: [dpkt PCAP reader](https://dpkt.readthedocs.io/en/latest/_modules/dpkt/pcap.html).

The legacy `on_link` counter and `stays_on_link` predicate describe policy exclusions,
not physical routing. Routable multicast is excluded too. KAN-33/G8 must use independent
sink/forwarding counters for leakage, with missing coverage marked unmeasured.
`on_link` is an additive field in the PCAP/live diagnostic JSON output.
