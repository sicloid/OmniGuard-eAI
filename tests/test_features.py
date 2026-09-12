import importlib.util
import math
import unittest

from core.features import (
    FEATURE_ORDER,
    FEATURE_SCHEMA_VERSION,
    FeatureError,
    extract_features,
)
from core.schema import Direction, FeatureVector, PacketTuple


def pkt(
    ts,
    dst="198.51.100.1",
    dport=443,
    proto=6,
    flags=0x02,
    length=60,
    direction=Direction.EGRESS,
    device="cam-1",
):
    sport = None if dport is None else 50000
    return PacketTuple(
        ts,
        device,
        None,
        "192.168.1.2",
        sport,
        dst,
        dport,
        proto,
        flags if proto == 6 else 0,
        length,
        direction,
    )


def as_dict(vector: FeatureVector) -> dict[str, float]:
    return dict(zip(vector.feature_order, vector.values, strict=True))


class CatalogueTests(unittest.TestCase):
    def test_catalogue_is_versioned_and_excludes_identity(self):
        self.assertEqual(FEATURE_SCHEMA_VERSION, "features-1")
        self.assertEqual(len(FEATURE_ORDER), len(set(FEATURE_ORDER)))
        for forbidden in ("device", "mac", "src_ip", "dst_ip", "label", "capture"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, FEATURE_ORDER)

    def test_vector_carries_catalogue_and_window(self):
        vector = extract_features("cam-1", 100.0, [pkt(100.0)])
        self.assertEqual(vector.feature_order, FEATURE_ORDER)
        self.assertEqual(vector.feature_schema_version, FEATURE_SCHEMA_VERSION)
        self.assertEqual(
            (vector.device_id, vector.window_start, vector.window_end), ("cam-1", 100.0, 105.0)
        )


class OracleTests(unittest.TestCase):
    def test_hand_computed_window(self):
        packets = [
            pkt(100.0, length=60),  # TCP SYN
            pkt(101.0, length=40, flags=0x10),  # TCP ACK
            pkt(102.0, dst="203.0.113.9", dport=53, proto=17, length=100),  # UDP
            pkt(104.5, dst="203.0.113.9", dport=None, proto=1, length=84),  # ICMP, no ports
        ]
        v = as_dict(extract_features("cam-1", 100.0, packets))
        mean = 284 / 4
        std = math.sqrt(sum((x - mean) ** 2 for x in (60, 40, 100, 84)) / 4)
        self.assertEqual(v["pkt_count"], 4)
        self.assertEqual(v["l3_bytes_sum"], 284)
        self.assertEqual(v["l3_bytes_mean"], mean)
        self.assertTrue(math.isclose(v["l3_bytes_std"], std, rel_tol=1e-12))
        self.assertEqual(v["uniq_dst_ip"], 2)
        self.assertEqual(v["uniq_dst_port"], 2)
        self.assertEqual(v["max_dst_ip_share"], 0.5)
        self.assertEqual((v["tcp_share"], v["udp_share"], v["icmp_share"]), (0.5, 0.25, 0.25))
        self.assertEqual(v["syn_only_share"], 0.25)
        self.assertEqual(v["rst_share"], 0.0)
        self.assertEqual(v["portless_share"], 0.25)
        self.assertEqual(v["active_span_s"], 4.5)

    def test_single_packet_window_is_well_defined(self):
        v = as_dict(extract_features("cam-1", 100.0, [pkt(102.0)]))
        self.assertEqual((v["pkt_count"], v["l3_bytes_std"], v["active_span_s"]), (1, 0.0, 0.0))
        self.assertEqual(v["max_dst_ip_share"], 1.0)

    def test_syn_ack_and_rst_are_distinguished(self):
        packets = [pkt(100.0, flags=0x12), pkt(100.5, flags=0x04), pkt(101.0, flags=0x14)]
        v = as_dict(extract_features("cam-1", 100.0, packets))
        self.assertEqual(v["syn_only_share"], 0.0)
        self.assertEqual(v["rst_share"], 2 / 3)

    def test_icmpv6_counts_as_icmp(self):
        v = as_dict(extract_features("cam-1", 100.0, [pkt(100.0, dport=None, proto=58)]))
        self.assertEqual(v["icmp_share"], 1.0)

    def test_noninitial_fragment_has_null_port_and_is_not_guessed(self):
        fragment = pkt(100.0, dport=None, proto=17)
        v = as_dict(extract_features("cam-1", 100.0, [fragment, pkt(101.0, dport=53, proto=17)]))
        self.assertEqual(v["uniq_dst_port"], 1)
        self.assertEqual(v["portless_share"], 0.5)


class DirectionAndValidityTests(unittest.TestCase):
    def test_only_egress_packets_contribute(self):
        packets = [
            pkt(100.0, direction=Direction.LOCAL, length=999),
            pkt(100.5, direction=Direction.INGRESS, length=999),
            pkt(101.0, length=60),
        ]
        v = as_dict(extract_features("cam-1", 100.0, packets))
        self.assertEqual((v["pkt_count"], v["l3_bytes_sum"]), (1, 60))

    def test_window_without_egress_yields_no_vector(self):
        self.assertIsNone(extract_features("cam-1", 100.0, []))
        self.assertIsNone(extract_features("cam-1", 100.0, [pkt(100.0, direction=Direction.LOCAL)]))

    def test_invalid_input_raises_instead_of_producing_a_vector(self):
        for packets in (
            [pkt(105.0)],  # half-open: end excluded
            [pkt(99.999)],
            [pkt(100.0, device="other")],
        ):
            with self.subTest(packets=packets), self.assertRaises(FeatureError):
                extract_features("cam-1", 100.0, packets)
        with self.assertRaises(FeatureError):
            extract_features("cam-1", 101.0, [pkt(101.0)])  # not epoch-aligned

    def test_input_order_does_not_matter(self):
        packets = [pkt(100.0), pkt(103.0, dport=53, proto=17), pkt(101.0, flags=0x04)]
        forward = extract_features("cam-1", 100.0, packets)
        backward = extract_features("cam-1", 100.0, list(reversed(packets)))
        self.assertEqual(forward, backward)

    def test_values_are_finite_floats(self):
        vector = extract_features("cam-1", 100.0, [pkt(100.0), pkt(101.0, length=1500)])
        self.assertTrue(all(type(x) is float and math.isfinite(x) for x in vector.values))


def _windows_available() -> bool:
    try:
        return importlib.util.find_spec("gateway.windows") is not None
    except ModuleNotFoundError:
        return False


@unittest.skipUnless(_windows_available(), "KAN-28 gateway.windows is not on main yet")
class OfflineLiveParityTests(unittest.TestCase):
    def test_same_vector_through_live_window_buffer(self):
        from gateway.windows import TumblingWindows

        packets = [pkt(100.0), pkt(101.5, dport=53, proto=17), pkt(104.9, flags=0x10)]
        windows = TumblingWindows(100.0)
        for p in packets:
            windows.add(p)
        (window,) = windows.advance(105.0)
        live = extract_features(window.device_id, window.start, window.packets)
        offline = extract_features("cam-1", 100.0, packets)
        self.assertEqual(live, offline)


if __name__ == "__main__":
    unittest.main()
