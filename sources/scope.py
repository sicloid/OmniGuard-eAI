"""Destination exclusions for EGRESS features; shared by live capture and the pack builder.

This is a feature-selection policy, not a routing or containment guarantee. All
multicast is excluded, including routable IPv4 multicast and globally scoped IPv6
multicast. PacketNormalizer represents policy-excluded LAN-source traffic as LOCAL.
The historical names ON_LINK_DESTINATIONS and stays_on_link mean policy exclusion;
they do not prove that traffic cannot leave the link. KAN-33/G8 must measure leakage
independently of Direction.EGRESS, with explicit protocol/address-family coverage.

Broadcast needs care per address family:

- A LAN's own subnet broadcast (192.168.1.255 in 192.168.1.0/24) needs no rule here.
  It is inside the configured prefix, so LAN membership already makes it LOCAL.
- /31 (RFC 3021) and /32 networks have no broadcast address. Every address in them is
  a host, LOCAL through the same membership, and nothing is reinterpreted as broadcast.
- IPv6 has no broadcast. The policy excludes ff00::/8 multicast and fe80::/10
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
    """True for a feature-policy exclusion, regardless of actual multicast routing."""
    return any(
        destination.version == network.version and destination in network for network in _ON_LINK
    )
