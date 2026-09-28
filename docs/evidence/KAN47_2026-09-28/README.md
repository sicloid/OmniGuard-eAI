# KAN-47 localhost FastAPI comparison

The frozen KAN-19 artifact is loaded through the existing SHA-256-pinned loader
both locally and in the optional FastAPI process. `comparison.json` records 100
requests over the same labelled sample-pack vectors and fails if any remote
result differs from the local `DetectionResult`.

This localhost run measures serialization, HTTP and service-process overhead on
this host. It is not a WAN/cloud benchmark and the application gateway remains
on local inference.
