"""Metadata-only packet normalization shared by offline and future live adapters."""

import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from ipaddress import ip_address, ip_network

import dpkt

from core.schema import Direction, PacketTuple, nonempty
from sources.scope import stays_on_link


class PacketError(ValueError):
    """Malformed/truncated packet: do not silently use it as a complete observation."""


class UnsupportedLinkType(ValueError):
    pass


@dataclass
class PacketStats:
    records: int = 0
    emitted: int = 0
    non_ip: int = 0
    outside_lan: int = 0
    unmapped_device: int = 0
    malformed: int = 0
    # Emitted packets from a LAN device to an on-link destination outside the LAN
    # prefixes (multicast, limited broadcast, link-local, unspecified): LOCAL, not EGRESS.
    on_link: int = 0


class PacketNormalizer:
    """Explicit IP→device map; never invent a device identity from an IP or MAC."""

    def __init__(self, lan_cidrs: Sequence[str], devices: Mapping[str, str]):
        if not isinstance(devices, Mapping):
            raise ValueError("devices must be a JSON object mapping IP to device_id")
        self.lans = tuple(ip_network(cidr) for cidr in lan_cidrs)
        if not self.lans:
            raise ValueError("at least one LAN CIDR is required")
        self.devices = {}
        for address, device in devices.items():
            nonempty(device, "device_id")
            ip = ip_address(address)
            if not self._in_lan(ip):
                raise ValueError("device mapping must belong to the configured LAN")
            self.devices[ip] = device
        self.stats = PacketStats()

    def _in_lan(self, ip):
        return any(ip.version == network.version and ip in network for network in self.lans)

    def parse(self, timestamp: float, frame: bytes, linktype: int = 1) -> PacketTuple | None:
        self.stats.records += 1
        try:
            return self._parse(timestamp, frame, linktype)
        except (dpkt.UnpackError, struct.error, ValueError) as exc:
            if isinstance(exc, UnsupportedLinkType):
                raise
            self.stats.malformed += 1
            raise PacketError(str(exc)) from exc

    def _parse(self, timestamp, frame, linktype):
        mac = None
        if linktype == 1:  # DLT_EN10MB, including up to two VLAN tags
            if len(frame) < 14:
                raise PacketError("short Ethernet header")
            mac = ":".join(f"{byte:02x}" for byte in frame[6:12])
            ethertype = struct.unpack_from("!H", frame, 12)[0]
            offset = 14
            for _ in range(2):
                if ethertype not in (0x8100, 0x88A8):
                    break
                if len(frame) < offset + 4:
                    raise PacketError("short VLAN header")
                ethertype = struct.unpack_from("!H", frame, offset + 2)[0]
                offset += 4
            if ethertype in (0x8100, 0x88A8):
                raise PacketError("more than two VLAN tags unsupported")
            raw = frame[offset:]
        elif linktype in (12, 101):  # platform DLT_RAW / LINKTYPE_RAW
            if not frame:
                raise PacketError("empty raw IP record")
            raw = frame
            ethertype = {4: 0x0800, 6: 0x86DD}.get(raw[0] >> 4, 0)
        elif linktype == 113:  # Linux cooked v1; sender address is not always src_mac
            if len(frame) < 16:
                raise PacketError("short SLL header")
            ethertype = struct.unpack_from("!H", frame, 14)[0]
            raw = frame[16:]
        elif linktype == 276:  # Linux cooked v2
            if len(frame) < 20:
                raise PacketError("short SLL2 header")
            ethertype = struct.unpack_from("!H", frame)[0]
            raw = frame[20:]
        else:
            raise UnsupportedLinkType(f"unsupported linktype {linktype}")
        if ethertype not in (0x0800, 0x86DD):
            self.stats.non_ip += 1
            return None

        if ethertype == 0x0800:
            if len(raw) < 20 or raw[0] >> 4 != 4:
                raise PacketError("invalid IPv4 header")
            header_length = (raw[0] & 15) * 4
            length = struct.unpack_from("!H", raw, 2)[0]
            if header_length < 20 or length < header_length or len(raw) < length:
                raise PacketError("invalid/truncated IPv4 length")
            packet = dpkt.ip.IP(raw[:length])
            src, dst = ip_address(packet.src), ip_address(packet.dst)
            protocol = packet.p
            fragment = struct.unpack_from("!H", raw, 6)[0]
            noninitial = bool(fragment & 0x1FFF)
            fragmented = bool(fragment & 0x3FFF)
            transport = raw[header_length:length]
        else:
            if len(raw) < 40 or raw[0] >> 4 != 6:
                raise PacketError("invalid IPv6 header")
            length = 40 + struct.unpack_from("!H", raw, 4)[0]
            if length == 40 and raw[6] != 59:
                raise PacketError("IPv6 jumbograms/offloaded zero lengths unsupported")
            if len(raw) < length:
                raise PacketError("truncated IPv6 packet")
            src, dst = ip_address(raw[8:24]), ip_address(raw[24:40])
            protocol, offset = raw[6], 40
            noninitial = fragmented = False
            extensions = 0
            while protocol in (0, 43, 44, 51, 60):
                extensions += 1
                if extensions > 8 or offset + 2 > length:
                    raise PacketError("invalid/too many IPv6 extension headers")
                nxt = raw[offset]
                if protocol == 44:
                    size = 8
                    if offset + size > length:
                        raise PacketError("truncated IPv6 fragment header")
                    fragment = struct.unpack_from("!H", raw, offset + 2)[0]
                    noninitial, fragmented = bool(fragment >> 3), bool(fragment & 0xFFF9)
                else:
                    size = (
                        (raw[offset + 1] + 2) * 4 if protocol == 51 else (raw[offset + 1] + 1) * 8
                    )
                if offset + size > length:
                    raise PacketError("truncated IPv6 extension")
                offset += size
                protocol = nxt
                if noninitial:
                    break
            transport = raw[offset:length]

        src_lan, dst_lan = self._in_lan(src), self._in_lan(dst)
        if not src_lan and not dst_lan:
            self.stats.outside_lan += 1
            return None
        # Multicast, limited broadcast, link-local and unspecified destinations never leave
        # the link, so a LAN source sending to one is LOCAL even outside the LAN prefixes.
        on_link = src_lan and not dst_lan and stays_on_link(dst)
        direction = (
            Direction.LOCAL
            if (src_lan and dst_lan) or on_link
            else (Direction.EGRESS if src_lan else Direction.INGRESS)
        )
        device_id = self.devices.get(src if src_lan else dst)
        if device_id is None:
            self.stats.unmapped_device += 1
            return None
        src_port = dst_port = None
        flags = 0
        if not noninitial and protocol in (6, 17):
            minimum = 20 if protocol == 6 else 8
            if len(transport) < minimum:
                if not fragmented:
                    raise PacketError("truncated transport header")
                # A first fragment can lack a complete transport header; do not guess.
            else:
                if protocol == 6:
                    tcp = dpkt.tcp.TCP(transport)
                    if tcp.off < 5 or tcp.off * 4 > len(transport):
                        raise PacketError("invalid TCP data offset")
                    src_port, dst_port, flags = tcp.sport, tcp.dport, tcp.flags
                else:
                    udp = dpkt.udp.UDP(transport)
                    if udp.ulen < 8 or (not fragmented and udp.ulen > len(transport)):
                        raise PacketError("invalid UDP length")
                    src_port, dst_port = udp.sport, udp.dport
        result = PacketTuple(
            timestamp,
            device_id,
            mac,
            str(src),
            src_port,
            str(dst),
            dst_port,
            protocol,
            flags,
            length,
            direction,
        )
        if on_link:
            self.stats.on_link += 1
        self.stats.emitted += 1
        return result
