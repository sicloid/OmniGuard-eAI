"""Independent loopback service control in og-a during gateway containment."""

import argparse
import socket
import time

ADDRESS = ("127.0.0.1", 49310)
MESSAGE = b"local-service-control"


def sink() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as service:
        service.bind(ADDRESS)
        while True:
            data, peer = service.recvfrom(128)
            if data == MESSAGE:
                service.sendto(data, peer)


def source() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.settimeout(0.2)
        while True:
            client.sendto(MESSAGE, ADDRESS)
            try:
                data, _ = client.recvfrom(128)
                if data == MESSAGE:
                    print(time.monotonic_ns(), flush=True)
            except TimeoutError:
                pass
            time.sleep(0.05)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("sink", "source"))
    args = parser.parse_args()
    sink() if args.mode == "sink" else source()


if __name__ == "__main__":
    main()
