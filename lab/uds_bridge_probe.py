"""Dedicated Linux proof that og-b can reach a parent-namespace UDS without IP routing."""

import argparse
import json
import os
import socket
from dataclasses import asdict
from pathlib import Path

from core.schema import DeviceState, StateEvent
from gateway.event_bridge import UnixSocketTransport, state_event_document
from telemetry.outcomes import HandoffOutcome
from telemetry.uds import PeerVerification, UnixSocketAdapter


class RecordingSink:
    """Probe-only host sink: accepted events prove the real adapter decoded them."""

    def __init__(self):
        self.events = []

    def submit(self, event: StateEvent, *, now: float) -> HandoffOutcome:
        self.events.append((event, now))
        return HandoffOutcome.ACCEPTED


def server(path: Path) -> int:
    if not hasattr(socket, "AF_UNIX") or not hasattr(socket, "SO_PEERCRED"):
        raise RuntimeError("Linux AF_UNIX + SO_PEERCRED required")
    sink = RecordingSink()
    adapter = UnixSocketAdapter(
        path,
        sink,
        clock=lambda: 1_700_000_000.0,
        allowed_uids=frozenset({os.geteuid()}),
        require_peer_credentials=True,
        timeout=5.0,
    )
    try:
        adapter.bind()
        adapter.accept_once()
        counters = adapter.counters
        if counters.peer_verification is not PeerVerification.VERIFIED:
            raise RuntimeError("adapter did not verify the Unix peer")
        if counters.connections != 1 or counters.accepted != 1 or len(sink.events) != 1:
            raise RuntimeError(f"adapter did not accept exactly one event: {counters}")
        outgoing, _now = sink.events[0]
        mode = oct(path.stat().st_mode & 0o777)
        report_counters = asdict(counters)
        report_counters["peer_verification"] = counters.peer_verification.value
        print(
            json.dumps(
                {
                    "socket_mode": mode,
                    "adapter": report_counters,
                    "event": state_event_document(outgoing),
                },
                sort_keys=True,
            ),
            flush=True,
        )
    finally:
        adapter.close()
    return 0


def gateway(path: Path) -> int:
    outgoing = StateEvent(
        "lab-camera",
        DeviceState.NORMAL,
        DeviceState.SUSPICIOUS,
        "uds bridge integration probe",
        1_700_000_000.0,
        None,
    )
    UnixSocketTransport(path, timeout=2.0).send(outgoing)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("server", "gateway"))
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    return server(args.path) if args.mode == "server" else gateway(args.path)


if __name__ == "__main__":
    raise SystemExit(main())
