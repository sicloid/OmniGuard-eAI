# KAN-47 FastAPI remote-inference comparison

The FastAPI surface is an optional experiment after G8/G10. It accepts exactly
the existing `FeatureVector` contract and returns the same `DetectionResult`
fields as the local detector. Unknown request fields and incompatible vectors
are rejected; inference errors never become a NORMAL result.

This path is not wired into the production gateway. Local inference remains the
default and the containment path has no HTTP or cloud dependency. The remote
surface exists only to compare serialization, transport and service overhead
against the same pinned detector.

Create an app with `gateway.remote_inference.create_app(detector)` after loading
the model through the existing hash-pinned loader, then serve that object with
Uvicorn. Any benchmark must record model/metadata hashes, client/server host,
request count, failures and latency distribution; a localhost result is not a
WAN or managed-cloud estimate.

## Recorded localhost comparison — 28 September 2026

One hundred requests used the pinned KAN-19 model and the sealed sample-pack
vectors. All 100 HTTP results exactly matched local inference. The
review-complete v2 run measured 6.47 ms p50 / 8.40 ms p95 locally and 7.73 ms
p50 / 9.94 ms p95 through FastAPI on localhost. Client and server shared the
same host CPU without cgroup isolation. The report records the URL, host roles,
Python 3.14.7, FastAPI 0.117.1 and Uvicorn 0.37.0, as well as the model,
metadata and pack hashes. It and its SHA-256 sidecar are in
`docs/evidence/KAN47_2026-09-28/comparison-v2.json`; v1 is retained for audit
history and is superseded for reporting.

These figures isolate one local service-process comparison. They do not include
WAN latency, TLS, multiple clients or managed-cloud behavior and do not justify
moving enforcement inference off the gateway.
