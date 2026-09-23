# Bounded real G8→G10 outage evidence — 20 September 2026

Run `python3 docs/evidence/G10_2026-09-20_raw/verify.py` from the repository
root. It checks the copied exact-byte logs and writes a JSON report. The source
was an isolated local integration checkout at commit `ce5bdbf` (PR #41 head
`05d64af` combined with then-current main `b2ae7d0`). The run ID is
`g10-outage-84739b9f83f5429e8e945447685de614`. The original frozen RF model
and prepared IoT-23 capture stay outside Git. `SHA256SUMS` pins the six raw
inputs so a reviewer can detect changes to the copied evidence.

The G8 controller logged two policy events and two kernel receipts. During an
isolated broker outage the host adapter accepted two frames with Linux
`SO_PEERCRED` verification, the worker spooled both, and no event was dropped.
After the broker and host publisher restarted, the original two IDs received
PUBACK; the consumer stored two rows with no DB failure or unacked message.
`verify.py` compares every stored StateEvent field against the controller log,
checks the associated kernel readback, and reconciles all observed counts.

The first transition was applied to nftables; at release the kernel's bounded
lease had already expired, so the receipt is `ALREADY_RELEASED` with inactive
readback. TCP and UDP sink delivery during the validated block interval was
zero, with real source attempts recorded in `validation.json`.

This is one declared development-validation capture and one local run. The
pairing uses unique event payloads and sequence; no shared durable
decision/application correlation key exists in the current schema. These files
do not constitute independent review, general completeness, a Pi result, or a
passed KAN-50 gate. The full source model/capture, Docker outputs, and spool
bytes remain in the local ignored run directory documented in Jira KAN-50.
