"""ADR-0003 host side of the gateway Unix socket bridge.

The gateway produces `StateEvent` documents; this adapter receives them on an
`AF_UNIX` stream, turns each frame back into a validated 0.1.0 `StateEvent`, and
hands it to the telemetry sink. Identity, sequence, envelope and topic are
assigned host-side by the publisher, so nothing the gateway sends is trusted to
carry them.

Two failure classes are kept apart, because they are not equally recoverable:

*Framing* errors (an oversized declaration, a truncated body) mean the stream
boundary itself is lost. There is no way to tell where the next frame begins, so
the connection is closed. Continuing to read would be guessing.

*Content* errors (a body that is not JSON, or a document that is not a valid
0.1.0 StateEvent) leave framing intact. The frame is counted and refused, and
the connection stays open, because one bad message from a producer is not a
reason to drop the ones behind it.

Platform reality, stated rather than assumed. `SO_PEERCRED` is Linux-only, and
CPython on Windows does not expose `AF_UNIX` at all, so on Windows this adapter
cannot bind a socket and cannot identify a peer. `AdapterCounters.peer_verification`
carries that fact into every report: it only reads `VERIFIED` where the
credentials were actually read and checked. Nothing here lets a Windows run be
written up as peer-verified.
"""

import json
import os
import socket
import struct
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from core.schema import DeviceState, StateEvent
from telemetry.framing import FrameError, FrameTooLarge, IncompleteFrame, read_frame
from telemetry.outcomes import HandoffOutcome

SOCKET_MODE = 0o600
DEFAULT_TIMEOUT_SECONDS = 5.0
EVENT_FIELDS = (
    "device_id",
    "expires_at",
    "new_state",
    "previous_state",
    "reason",
    "timestamp",
)

HAS_UNIX_SOCKETS = hasattr(socket, "AF_UNIX")
HAS_PEER_CREDENTIALS = hasattr(socket, "SO_PEERCRED")
# struct ucred: pid, uid, gid.
UCRED = struct.Struct("3i")


class AdapterError(RuntimeError):
    """The adapter cannot run as configured, or the platform cannot honour it."""


class DecodeError(ValueError):
    """A frame body could not be read as a document."""


class InvalidEvent(DecodeError):
    """The document parsed but is not a usable 0.1.0 StateEvent."""


class PeerVerification(StrEnum):
    """Whether the peer behind a connection was actually identified.

    `UNAVAILABLE` is not a mild version of `VERIFIED`. It means the platform
    gave no credentials, so no claim about the peer can be made at all.
    """

    VERIFIED = "VERIFIED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class PeerIdentity:
    pid: int
    uid: int
    gid: int


@dataclass(frozen=True)
class AdapterCounters:
    """What the adapter saw. Every refusal is counted, never silently swallowed."""

    connections: int = 0
    rejected_peers: int = 0
    frames: int = 0
    accepted: int = 0
    refused_by_sink: int = 0
    oversized_frames: int = 0
    incomplete_frames: int = 0
    malformed_frames: int = 0
    undecodable_bodies: int = 0
    invalid_events: int = 0
    read_timeouts: int = 0
    peer_verification: PeerVerification = PeerVerification.UNAVAILABLE


class Sink(Protocol):
    """Anything that takes an event without blocking; `TelemetryHandoff` is one."""

    def submit(self, event: StateEvent, *, now: float) -> HandoffOutcome: ...


def decode_state_event(body: bytes) -> StateEvent:
    """Rebuild a 0.1.0 StateEvent, refusing anything that is not exactly one.

    Unknown fields are refused rather than ignored. An extra key means the
    producer is speaking a contract this consumer was not reviewed against, and
    quietly dropping it is how a semantic change slips in unnoticed.
    """
    try:
        document = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise DecodeError(f"body is not UTF-8 JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise DecodeError("body must be a JSON object")
    unknown = sorted(set(document) - set(EVENT_FIELDS))
    if unknown:
        raise InvalidEvent(f"unknown field(s): {', '.join(unknown)}")
    missing = [field for field in EVENT_FIELDS if field not in document]
    if missing:
        raise InvalidEvent(f"missing field(s): {', '.join(missing)}")
    try:
        return StateEvent(
            document["device_id"],
            DeviceState(document["previous_state"]),
            DeviceState(document["new_state"]),
            document["reason"],
            document["timestamp"],
            document["expires_at"],
        )
    except (TypeError, ValueError) as exc:
        raise InvalidEvent(f"not a valid 0.1.0 StateEvent: {exc}") from exc


def peer_credentials(connection) -> PeerIdentity | None:
    """Read `SO_PEERCRED`, or None where the platform does not provide it."""
    if not HAS_PEER_CREDENTIALS:
        return None
    raw = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, UCRED.size)
    pid, uid, gid = UCRED.unpack(raw)
    return PeerIdentity(pid, uid, gid)


class UnixSocketAdapter:
    """Receive framed StateEvents from the gateway and hand them to the sink.

    `clock` is injected for the same reason the spool takes `now`: this module
    does not read a clock, so event time and monotonic time cannot be mixed by
    accident and the tests are not timing-dependent.
    """

    def __init__(
        self,
        path: Path,
        sink: Sink,
        *,
        clock,
        allowed_uids: frozenset[int] | None = None,
        require_peer_credentials: bool = True,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ):
        if not callable(clock):
            raise AdapterError("clock must be callable")
        if require_peer_credentials and not HAS_PEER_CREDENTIALS:
            raise AdapterError(
                "SO_PEERCRED is unavailable on this platform, so no peer can be "
                "identified; pass require_peer_credentials=False to run anyway "
                "and the result is reported as UNAVAILABLE, never as verified"
            )
        self._path = Path(path)
        self._sink = sink
        self._clock = clock
        self._allowed_uids = allowed_uids
        self._require_peer_credentials = require_peer_credentials
        self._timeout = float(timeout)
        self._counters = AdapterCounters()
        self._server: socket.socket | None = None
        self._stopping = False

    @property
    def counters(self) -> AdapterCounters:
        return self._counters

    @property
    def path(self) -> Path:
        return self._path

    def _count(self, field: str, amount: int = 1) -> None:
        self._counters = replace(self._counters, **{field: getattr(self._counters, field) + amount})

    # --- stream half: no socket needed, so it is tested on every platform ---

    def handle_body(self, body: bytes) -> bool:
        """Decode one frame body and offer it to the sink. False means refused."""
        self._count("frames")
        try:
            event = decode_state_event(body)
        except InvalidEvent:
            self._count("invalid_events")
            return False
        except DecodeError:
            self._count("undecodable_bodies")
            return False
        outcome = self._sink.submit(event, now=self._clock())
        if outcome is not HandoffOutcome.ACCEPTED:
            # The sink overflowed or is stopped. That is a loss at the boundary,
            # counted here as well as there; a receiver that keeps reading is
            # not evidence that anything is being delivered.
            self._count("refused_by_sink")
            return False
        self._count("accepted")
        return True

    def serve_stream(self, stream) -> None:
        """Read frames until the stream ends cleanly or framing is lost.

        Returning is not success: the counters say what happened. A framing
        error ends the loop because the next frame boundary is unknowable.
        """
        while True:
            try:
                body = read_frame(stream)
            except FrameTooLarge:
                self._count("oversized_frames")
                return
            except IncompleteFrame:
                self._count("incomplete_frames")
                return
            except FrameError:
                self._count("malformed_frames")
                return
            if body is None:
                return
            self.handle_body(body)

    # --- socket half: Linux only, and it says so instead of pretending ---

    def bind(self) -> None:
        """Create the listening socket at 0600, refusing to clobber a real file."""
        if not HAS_UNIX_SOCKETS:
            raise AdapterError(
                "this Python has no socket.AF_UNIX, so the gateway bridge cannot "
                "be bound here; the socket half runs on the Linux host only"
            )
        if self._path.exists():
            if not self._path.is_socket():
                raise AdapterError(
                    f"{self._path} exists and is not a socket; refusing to remove it"
                )
            self._path.unlink()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        # The mode is set by umask at creation. Binding first and chmod'ing after
        # would leave a window where the socket is reachable by anyone.
        previous = os.umask(0o777 & ~SOCKET_MODE)
        try:
            server.bind(os.fspath(self._path))
        finally:
            os.umask(previous)
        server.listen(1)
        server.settimeout(self._timeout)
        self._server = server

    def accept_once(self) -> None:
        """Serve exactly one connection, if one arrives before the timeout."""
        if self._server is None:
            raise AdapterError("bind() before serving")
        try:
            connection, _ = self._server.accept()
        except TimeoutError:
            self._count("read_timeouts")
            return
        with connection:
            connection.settimeout(self._timeout)
            self._count("connections")
            if not self._admit(connection):
                return
            try:
                self.serve_stream(connection.makefile("rb"))
            except TimeoutError:
                self._count("read_timeouts")

    def serve_forever(self) -> None:
        while not self._stopping:
            self.accept_once()

    def stop(self) -> None:
        self._stopping = True

    def _admit(self, connection) -> bool:
        """Decide whether this peer may speak, and record how confident we are."""
        identity = peer_credentials(connection)
        if identity is None:
            self._counters = replace(self._counters, peer_verification=PeerVerification.UNAVAILABLE)
            return not self._require_peer_credentials
        self._counters = replace(self._counters, peer_verification=PeerVerification.VERIFIED)
        allowed = self._allowed_uids
        if allowed is None:
            allowed = frozenset({os.geteuid()})
        if identity.uid not in allowed:
            self._count("rejected_peers")
            return False
        return True

    def close(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
        if HAS_UNIX_SOCKETS and self._path.exists() and self._path.is_socket():
            self._path.unlink()
