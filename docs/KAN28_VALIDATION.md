# KAN-28 validation — 2026-09-12

KAN-28 connects Linux `LiveCapture` output to bounded, epoch-aligned, per-device
five-second windows and the shared pure extractor. It adds no runtime wire fields
and does not implement detector or policy state.

## Automated checks

Python 3.14.7 ran the full suite:

```text
python -m unittest discover -s tests -v
Ran 133 tests in 1.083s
OK
```

Ruff lint and format checks passed for all 45 files. Four focused pipeline tests
prove offline/extractor equality, no idle or non-EGRESS benign vector, whole-window
invalidation and recovery after capture failure, and independent device outputs.

## Real Linux capture evidence

`bash lab/run_live_docker.sh` ran in a disposable container with three isolated
network namespaces. It did not use host networking, a Docker socket mount, a default
route, or host ruleset changes.

```json
{
  "window_pipeline": {
    "sent": 4,
    "first_window_packets": 3,
    "feature_packet_count": 3.0,
    "feature_l3_bytes": 180.0,
    "kernel_drops": 0
  },
  "overflow": {
    "detected_drops": 9991
  }
}
```

The first three 60-byte L3 UDP packets were captured in one complete epoch window.
The fourth packet crossed the half-open boundary, closed the first window and stayed
in the next one. The resulting shared-extractor values matched the independent packet
oracle. The existing overflow phase continued to reject detected socket loss.

The local raw evidence is under `artifacts/live-capture.11f8hcYX/` and is ignored by
Git. This run proves the x86_64 Linux integration path; it does not claim ARM64/Pi,
trained-model performance, N policy, enforcement, or G5/G8/G10 completion.

## Follow-up review correction

PR #18 remains incomplete and has no team review. The evidence above measures
packet-driven closure, not safe idle closure. Repeated `None` reads leave a pending
window open; a much later packet can return an old vector without stale eligibility
information. Idle/stale/gap handling and startup/shutdown health propagation require
additional implementation and tests. Raw capture overflow and a mocked pipeline
exception do not by themselves prove end-to-end loss propagation. See the
[reproduction and remaining acceptance](https://github.com/sicloid/OmniGuard-eAI/pull/18#issuecomment-5646848250).
