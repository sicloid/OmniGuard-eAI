# KAN-27 — Linux live PacketTuple adapter

`LiveCapture` opens an explicitly named Ethernet interface in the **current network
namespace**, using AF_PACKET ingress and kernel nanosecond timestamps. It calls the
same PacketNormalizer as the classic PCAP reader. Use the gateway LAN interface
(`og-b0` in the isolated lab), before the ordinary forwarding quarantine rule.
Outgoing frames are excluded to avoid observing a second copy on that interface.

```sh
python -m sources.live --interface og-b0 --lan 10.203.1.0/24 \
  --devices /path/to/devices.json --duration 10
```

Run that command only in the intended lab namespace with CAP_NET_RAW. Do not grant
capture privilege to the model process. The adapter does not manage namespaces,
change firewall rules, load a model or write captures. Stdout is PacketTuple JSONL;
stderr reports readiness and normalizer/socket statistics. Error exit 2 rejects
the observation; interruption exits 130. Preserve the error and invalidate affected
windows instead of interpreting partial stdout as complete data.

## Scope and bounds

Linux with time64 timestamp socket support; Ethernet only, not loopback/cooked or
Windows. The implementation uses SO_TIMESTAMPNS_NEW with two signed 64-bit fields.
Float UTC seconds match PacketTuple/PCAP semantics; float conversion does not retain
all nanosecond precision. No userspace receive-time fallback is used. Timestamp
regression/reordering, missing timestamps or truncated control data are fatal.

The receive request defaults to 1 MiB; Linux can clamp/double it. The actual
SO_RCVBUF value is reported. Each read is bounded at 128 KiB and truncation fails.
There is no application queue; a slow stdout consumer can overflow the socket.
The adapter accumulates reset-on-read PACKET_STATISTICS and rejects detected drops,
including at clean shutdown. This counter covers the socket only: NIC, driver,
upstream loss, XDP and hardware offload remain outside that evidence.

The raw frame temporarily contains payload in memory. Only metadata is exported;
this is **not** a header-only capture implementation. Existing IPv4/IPv6 length,
fragment and mapping behavior remains the shared normalizer's responsibility.
Device mapping is explicit and static; this adapter does not establish identity
freshness or trust. No BPF/promiscuous-mode or host interface configuration changes.

## Window integration boundary

`read(timeout)` returns a tuple or None for timeout/filtered traffic. None is **not**
a trustworthy idle watermark: queued delivery and upstream loss require a separate
observation protocol. Read errors are sticky; restart explicitly after recording
loss and invalidating policy evidence. Callers must not carry an N streak across
an unknown interval. The versioned ObservationHealth record and complete capture →
window health wire encoding remains separate contract work. KAN-63 design review
is complete. No new wire field is added.

`read_progress(timeout)` additionally distinguishes real socket timeout from
filtered frames. It emits a pre-receive UTC cutoff minus 100 ms only after timeout,
loss checks and UTC/monotonic offset checks. A queued packet is read instead of
advancing. Offset drift above 100 ms, clock sampling uncertainty above 10 ms,
packets older than one second or over 100 ms in the future fail the session.
Subsequent timestamps below the emitted cutoff also fail. This depends on the
same ordered kernel-timestamp assumption as `read`; it is not an upstream-loss
guarantee. Use `WindowFeaturePipeline.close_capture` to propagate shutdown loss
and discard the final partial interval.

## Validation

```sh
.venv/bin/python -m unittest discover -s tests -p test_live.py -v
bash lab/run_live_docker.sh
```

The Docker command is dedicated-host-only, amd64, and uses a pinned Python 3.14.7
image. It creates isolated A→B→C namespaces inside a network-none disposable
container, with no host network/PID/socket/bind mounts. It checks known benign UDP
source counts, independent sink counts, L3 lengths and source MAC, including when
quarantine drops forwarding. A separate deliberately starved 4 KiB socket must
report overflow. Parent container rules/routes and namespace cleanup are checked.
Evidence is under ignored `artifacts/live-capture.*`; no packet capture is committed.
This is source-adapter evidence, not a trained-RF/G8 gate or ARM64 performance test.

Unit tests use independently assembled Ethernet/IPv4/UDP bytes for PCAP/live tuple
parity, plus loss, truncation, timestamp, filtering, setup/cleanup and platform
errors. Hosted CI needs no capture privileges; privileged integration stays local.

References: [Linux packet sockets](https://man7.org/linux/man-pages/man7/packet.7.html)
and [kernel timestamping](https://docs.kernel.org/networking/timestamping.html).
