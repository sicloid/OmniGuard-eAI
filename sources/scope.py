"""Which destinations stay on the local link; shared by live capture and the pack builder.

A packet from a LAN device is EGRESS only when its destination is routed out of the
house. Multicast, the limited broadcast, link-local and unspecified destinations never
leave the link, so `PacketNormalizer` marks them LOCAL even though they fall outside
the configured LAN prefixes. Live windows and the offline sample pack therefore see
the same EGRESS set.

Broadcast needs care per address family:

- A LAN's own subnet broadcast (192.168.1.255 in 192.168.1.0/24) needs no rule here.
  It is inside the configured prefix, so LAN membership already makes it LOCAL.
- /31 (RFC 3021) and /32 networks have no broadcast address. Every address in them is
  a host, LOCAL through the same membership, and nothing is reinterpreted as broadcast.
- IPv6 has no broadcast. Its on-link traffic is ff00::/8 multicast and fe80::/10
  link-local; an all-ones interface identifier is an ordinary host address.
- A directed broadcast to a prefix that is not configured cannot be recognised without
  that prefix's mask, so it stays EGRESS. Configure the real LAN prefix instead.
"""

from ipaddress import IPv4Address, IPv6Address, ip_network

ON_LINK_DESTINATIONS = (
    "224.0.0.0/4",
    "255.255.255.255/32",
    "169.254.0.0/16",
    "0.0.0.0/32",
    "ff00::/8",
    "fe80::/10",
    "::/128",
)
_ON_LINK = tuple(ip_network(prefix) for prefix in ON_LINK_DESTINATIONS)


def stays_on_link(destination: IPv4Address | IPv6Address) -> bool:
    """True for destinations that never leave the local link, whatever the LAN prefix."""
    return any(
        destination.version == network.version and destination in network for network in _ON_LINK
    )
