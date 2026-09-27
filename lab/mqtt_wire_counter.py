"""Count the bytes that actually cross the MQTT connection, in both directions.

KAN-43 asks for the real wire volume, and the card is explicit that a theoretical
payload size is not a network cost. The application byte figures in
`telemetry/accounting.py` are what the host *offered* to the client; this relay is
what the socket *carried*: PUBLISH packets out, PUBACK and CONNACK in, plus every
keepalive the client decided to send.

It is a byte relay and nothing else. It does not parse, buffer by message, or modify
what passes through, so the totals are the connection's own bytes rather than a model
of them. Run it between the publisher and the broker:

    python -m lab.mqtt_wire_counter --listen 127.0.0.1:18831 \\
        --broker 127.0.0.1:1883 --out ~/omniguard-data/runs/kan43/wire.json

**What it does not count:** IP and TCP headers, retransmissions, and TLS record
overhead if the connection is encrypted. It counts TCP payload bytes, which is the
layer the MQTT packets live in. A link-level figure needs a capture, not this.
"""

import argparse
import json
import socket
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

BUFFER = 65536


@dataclass
class DirectionCounts:
    """Bytes one way, split at the marks the caller set."""

    total: int = 0
    # How many recv() calls this relay made. An artefact of the relay's own buffering:
    # it is not a packet count and not how the broker saw the connection segmented.
    relay_recv_calls: int = 0
    segments: dict[str, int] = field(default_factory=dict)


@dataclass
class WireCounts:
    to_broker: DirectionCounts = field(default_factory=DirectionCounts)
    from_broker: DirectionCounts = field(default_factory=DirectionCounts)
    connections: int = 0
    current_segment: str = "connect"


class MqttWireCounter:
    """A counting TCP relay. One thread per direction, per accepted connection."""

    def __init__(self, listen: tuple[str, int], broker: tuple[str, int]):
        self.listen_address = listen
        self.broker_address = broker
        self.counts = WireCounts()
        self._lock = threading.Lock()
        self._server: socket.socket | None = None
        self._threads: list[threading.Thread] = []
        self._stopping = threading.Event()

    def mark(self, segment: str) -> None:
        """Name the phase the following bytes belong to.

        The connection handshake costs bytes once, while PUBLISH traffic repeats per
        event. Averaging the two together would quietly charge every event a share of
        a cost it did not cause, so the phases are counted apart and reported apart.

        A mark is exact only at a protocol synchronisation point. Bytes are attributed
        to the segment that is current when the relay reads them, so a mark set while a
        packet is in flight can land that packet on either side, and one recv() can
        span both. The relay counts before it forwards, so once the client has seen
        the peer's reply to the last packet of a phase (CONNACK for CONNECT, PUBACK
        for the last PUBLISH), every byte of that phase has been counted in both
        directions and nothing of the next one has been sent. Marks belong there. The
        only traffic a synchronised mark cannot pin down is what neither side asked
        for — a keepalive PINGREQ/PINGRESP — so a sealed run reconciles each segment
        against the derived packet sizes and reports any residue instead of hiding it.
        """
        if not isinstance(segment, str) or not segment.strip():
            raise ValueError("a segment name must be nonempty text")
        with self._lock:
            self.counts.current_segment = segment

    def _count(self, direction: DirectionCounts, amount: int) -> None:
        with self._lock:
            direction.total += amount
            direction.relay_recv_calls += 1
            segment = self.counts.current_segment
            direction.segments[segment] = direction.segments.get(segment, 0) + amount

    @property
    def port(self) -> int:
        if self._server is None:
            raise RuntimeError("the relay is not listening yet")
        return self._server.getsockname()[1]

    def start(self) -> None:
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind(self.listen_address)
        self._server.listen(8)
        thread = threading.Thread(target=self._accept_forever, daemon=True)
        thread.start()
        self._threads.append(thread)

    def _accept_forever(self) -> None:
        while not self._stopping.is_set():
            try:
                client, _ = self._server.accept()
            except OSError:
                return
            with self._lock:
                self.counts.connections += 1
            thread = threading.Thread(target=self._serve, args=(client,), daemon=True)
            thread.start()
            self._threads.append(thread)

    def _serve(self, client: socket.socket) -> None:
        try:
            upstream = socket.create_connection(self.broker_address)
        except OSError:
            client.close()
            return
        pump_out = threading.Thread(
            target=self._pump, args=(client, upstream, self.counts.to_broker), daemon=True
        )
        pump_in = threading.Thread(
            target=self._pump, args=(upstream, client, self.counts.from_broker), daemon=True
        )
        pump_out.start()
        pump_in.start()
        self._threads.extend((pump_out, pump_in))
        pump_out.join()
        pump_in.join()

    def _pump(self, source: socket.socket, sink: socket.socket, counts: DirectionCounts) -> None:
        try:
            while True:
                chunk = source.recv(BUFFER)
                if not chunk:
                    break
                self._count(counts, len(chunk))
                sink.sendall(chunk)
        except OSError:
            # A broken connection is an outcome of the run, not of the counting; the
            # bytes already counted stay counted and the report says how many.
            pass
        finally:
            for side in (source, sink):
                try:
                    side.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            source.close()
            sink.close()

    def stop(self) -> None:
        self._stopping.set()
        if self._server is not None:
            self._server.close()
        for thread in self._threads:
            thread.join(timeout=2)

    def report(self) -> dict:
        with self._lock:
            return {
                "counted": "TCP payload bytes on the MQTT connection",
                "not_counted": ["IP/TCP headers", "retransmissions", "TLS record overhead"],
                "listen": f"{self.listen_address[0]}:{self.listen_address[1]}",
                "broker": f"{self.broker_address[0]}:{self.broker_address[1]}",
                **asdict(self.counts),
            }


def _address(text: str) -> tuple[str, int]:
    host, _, port = text.rpartition(":")
    if not host or not port.isdigit():
        raise argparse.ArgumentTypeError(f"expected host:port, got {text!r}")
    return host, int(port)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen", type=_address, required=True)
    parser.add_argument("--broker", type=_address, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    counter = MqttWireCounter(args.listen, args.broker)
    counter.start()
    print(f"relaying {args.listen} -> {args.broker}; Ctrl-C to stop")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        counter.stop()
        args.out.write_text(
            json.dumps(counter.report(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
