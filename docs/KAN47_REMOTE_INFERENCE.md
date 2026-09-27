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
vectors. All 100 HTTP results exactly matched local inference. Local latency was
5.99 ms p50 / 7.57 ms p95; FastAPI localhost latency was 7.18 ms p50 / 8.77 ms
p95. The raw report pins the model, metadata and pack in
`docs/evidence/KAN47_2026-09-28/comparison.json`.

These figures isolate one local service-process comparison. They do not include
WAN latency, TLS, multiple clients or managed-cloud behavior and do not justify
moving enforcement inference off the gateway.
