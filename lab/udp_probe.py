"""Harmless fixed-rate echo probe, confined to the lab namespaces."""

import argparse
import socket
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("sink", "source"))
    args = parser.parse_args()
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        if args.mode == "sink":
            sock.bind(("10.203.2.2", 49000))
            while True:
                data, peer = sock.recvfrom(128)
                print(time.monotonic_ns(), flush=True)
                sock.sendto(data, peer)
        else:
            sock.bind(("10.203.1.2", 49001))
            sock.settimeout(0.1)
            while True:
                sock.sendto(b"omniguard-lab-probe", ("10.203.2.2", 49000))
                try:
                    sock.recvfrom(128)
                except TimeoutError:
                    pass
                time.sleep(0.05)


if __name__ == "__main__":
    main()
