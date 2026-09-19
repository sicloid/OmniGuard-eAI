# Demo and cleanup runbook (KAN-58 preparation)

This runbook describes a clean-checkout demonstration without implying that an
unpassed gate has passed. The demo operator must record the exact Git commit,
host architecture, Python version, Docker image digests, model/data pins and
paths to raw run evidence before presenting a metric. Keep personal captures,
credentials and model binaries outside Git and slides.

## Choose the path before starting

1. **Pi path:** use only when KAN-44/46/53 contain actual Pi 5 ARM64, network
   management, load and throttling evidence. Check that Tailscale is management
   only and advertises no `10.203.1.0/24` or `10.203.2.0/24` lab route. Keep Pi
   measurements in a separately labelled result set.
2. **Laptop fallback:** use the dedicated CachyOS/amd64 Docker lab and label the
   environment Linux x86_64. It avoids any Pi/Tailscale dependency, but a full
   core demo still requires the real G8 gate. The current synthetic RF smoke is
   a wiring illustration only.
3. **Partial prototype:** when G8 or G10 is missing, show the independently
   validated pieces with an explicit `not passed` status. Do not present stub,
   synthetic, Compose-health or CI results as the missing end-to-end gate.

## Preflight (clean checkout)

Run [the reproducibility sequence](REPRODUCE.md) through the locked environment,
unit tests and Ruff. Confirm the intended model and capture hashes independently
and that all source/provenance paths exist. Check the Jira status of KAN-49,
KAN-50, KAN-54 and KAN-53, and display any missing gate as a limitation on the
opening slide. Do not select a model, threshold, N or lease after looking at the
final/holdout results.

Record these outputs in the run directory before any live operation:

```sh
git rev-parse HEAD
uname -srmo
.venv/bin/python --version
docker version --format '{{.Server.Version}}'
docker compose version
```

For the Pi path, record `uname -m`, `/etc/os-release`, actual Python/package
versions, thermal/throttling and system load immediately before and after the
run. An unavailable reading is `missing`, not `normal`. KAN-46 decides whether
the run is valid; never silently omit a throttled result.

## Demonstration order

1. Explain the trust and network boundary: owned A→B→C lab, local RF inference,
   reversible nftables lease and independent UDS telemetry path. No managed cloud
   or public replay route is involved.
2. Run `bash lab/run_docker.sh` for established TCP/UDP network enforcement and
   cleanup. Run `bash lab/run_live_docker.sh` for capture health and
   `bash lab/run_replay_docker.sh` for prepared replay/t0 mechanics. Point to the
   generated `artifacts/` logs and name the scope of each proof.
3. If PR #41 is merged, run `bash lab/run_g8_synthetic_docker.sh` as a clearly
   labelled wiring smoke. Show the synthetic model ID and TCP/UDP sink counts;
   state that it is **not** the real RF/IoT-23 gate.
4. Only when the real pinned model and audited traffic are available, execute
   the G8 run under its reviewed runbook. Show raw detection, StateEvent,
   nftables readback, independent TCP/UDP sink stop, release restoration,
   process-kill/kernel-TTL and local service observations. A StateEvent alone
   is not enforcement proof.
5. Start the self-hosted Compose stack with the sequence in
   [REPRODUCE.md](REPRODUCE.md). If KAN-50 has passed, follow its accepted
   runbook to trace one real gateway event through UDS→MQTT→PostgreSQL→Grafana,
   including duplicate/outage/recovery. Otherwise show only the platform smoke
   and label G10 pending.
6. Present KAN-54 frozen results only when the exact run set and all failed or
   censored attempts are included. Separate laptop and Pi observations. Discuss
   per-capture benign false positives, observation loss, finite quarantine and
   incomplete generalisation without a deployment-quality claim.

## Fault handling

- A model hash/version mismatch, capture drop, stale clock, unexpected namespace
  identity, failed kernel readback or missing sink record invalidates that run.
- Stop and preserve its logs. Do not reuse the same result directory or replace
  it with only a successful retry. A kernel block that persists after process
  death must expire within the configured bound; otherwise the gate fails.
- If a live controller faults, reconcile the owned kernel state before rearming
  and verify the independent sink again. Do not clear host firewall/conntrack.

## Cleanup and final checks

The Docker lab runners remove their own disposable containers and copy `/tmp`
evidence to ignored `artifacts/`. For a **direct-host** lab, first stop source,
sink and capture processes, then run `sudo bash lab/teardown_netns.sh`; the
teardown refuses occupied/unowned namespaces. Verify `ip netns list` has no
owned `og-a`, `og-b`, `og-c` and compare parent rules/routes with the preflight
snapshots. Never flush the host ruleset or run broad Docker prune commands.

For the platform, use:

```sh
docker compose -f platform/compose.yaml down
```

This preserves named volumes and ignored credentials for the next run. The
project's published ports are loopback-only. Record any intentionally retained
container/service separately. The run ends with the evidence directory, gate
statuses, unresolved limitations and the names of reviewers who witnessed it.

KAN-58 closes only after both the Pi path or documented unavailable-Pi fallback
and this cleanup sequence are exercised from a clean checkout. KAN-59 still
requires an actual team Q&A rehearsal; a written runbook does not replace it.
