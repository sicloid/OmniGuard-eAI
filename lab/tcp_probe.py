"""Harmless persistent TCP echo probe confined to the OmniGuard lab."""

import argparse
import socket
import time

HOST = "10.203.2.2"
PORT = 49020
SOURCE = "10.203.1.2"
PAYLOAD = b"omniguard-tcp-probe"


def sink() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((HOST, PORT))
        server.listen(1)
        connection, _ = server.accept()
        with connection:
            while True:
                data = connection.recv(128)
                if not data:
                    return
                print(time.monotonic_ns(), flush=True)
                connection.sendall(data)


def source() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        client.bind((SOURCE, 0))
        client.settimeout(2.0)
        client.connect((HOST, PORT))
        client.settimeout(0.1)
        while True:
            try:
                client.sendall(PAYLOAD)
                data = client.recv(128)
                if data == PAYLOAD:
                    print(time.monotonic_ns(), flush=True)
            except TimeoutError:
                pass
            time.sleep(0.05)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("sink", "source"))
    args = parser.parse_args()
    sink() if args.mode == "sink" else source()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
