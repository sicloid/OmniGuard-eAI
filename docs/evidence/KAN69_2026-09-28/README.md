# KAN-69 candidate G8 regression evidence

The regularized ExtraTrees candidate was loaded through the production hash-pinned
artifact boundary and replayed with the audited IoT-23 8-1 prepared PCAP in the
owned A→B→C namespace lab.

- model SHA-256: `5c8909d717e79ca30b667140894ef0a1661835cf298437b956fbe5e95b5f843a`
- metadata SHA-256: `3e0246b0c899d88eefe8fe99d348ad628b36bec95b9e7e003b3a942134e12c29`
- prepared PCAP SHA-256: `fc4aa4b9bbdc89a7845fa0fb8b0fd19ce13f71c82a25346e390ad7863ac917ee`

The orderly run produced an anomalous decision, applied nftables quarantine,
blocked independent TCP and UDP sinks, kept the local service available, released
on the finite lease, recorded zero kernel capture drops and restored the parent
network state. The SIGKILL run proved that the kernel block survived controller
death and expired by kernel TTL, after which both sinks recovered. Both validation
reports bind the ready event to the candidate artifact hashes.

This proves runtime compatibility and enforcement regression. It does not by itself
accept the candidate as the active model: the fresh Pi benign evaluation and the
external CIC attack-transfer limitation remain part of the decision.
