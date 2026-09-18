"""Dedicated Linux proof that og-b can reach a parent-namespace UDS without IP routing."""

import argparse
import json
import os
import socket
import struct
from pathlib import Path

from core.schema import DeviceState, StateEvent
from gateway.event_bridge import UnixSocketTransport
from telemetry.framing import read_frame

UCRED = struct.Struct("3i")
EXPECTED_FIELDS = {
    "device_id",
    "previous_state",
    "new_state",
    "reason",
    "timestamp",
    "expires_at",
}


def server(path: Path) -> int:
    if not hasattr(socket, "AF_UNIX") or not hasattr(socket, "SO_PEERCRED"):
        raise RuntimeError("Linux AF_UNIX + SO_PEERCRED required")
    if path.exists():
        if not path.is_socket():
            raise RuntimeError(f"refusing to replace non-socket path {path}")
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)

    previous = os.umask(0o177)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        listener.bind(str(path))
    finally:
        os.umask(previous)
    listener.listen(1)
    listener.settimeout(5.0)
    try:
        connection, _ = listener.accept()
        with connection:
            raw = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, UCRED.size)
            pid, uid, gid = UCRED.unpack(raw)
            body = read_frame(connection.makefile("rb"))
            if body is None:
                raise RuntimeError("gateway closed before sending a frame")
            document = json.loads(body.decode("utf-8"))
            if set(document) != EXPECTED_FIELDS:
                raise RuntimeError("gateway body does not match ADR-0003 section 2.1")
            print(
                json.dumps(
                    {
                        "peer_pid": pid,
                        "peer_uid": uid,
                        "peer_gid": gid,
                        "socket_mode": oct(path.stat().st_mode & 0o777),
                        "event": document,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
    finally:
        listener.close()
        if path.exists() and path.is_socket():
            path.unlink()
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
