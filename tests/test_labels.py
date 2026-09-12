import tempfile
import unittest
from pathlib import Path

from core.schema import Direction, PacketTuple
from data.samplepack.labels import BENIGN, MALICIOUS, LabelError, load_conn_log

HEADER = """#separator \\x09
#set_separator\t,
#empty_field\t(empty)
#unset_field\t-
#path\tconn
#fields\tts\tuid\tid.orig_h\tid.orig_p\tid.resp_h\tid.resp_p\tproto\tservice\tduration\tlabel\tdet_label
#types\ttime\tstring\taddr\tport\taddr\tport\tenum\tstring\tinterval\tstring\tstring
"""


def row(ts, orig, oport, resp, rport, proto, duration, label, det="-"):
    return "\t".join(
        [str(ts), "uid", orig, str(oport), resp, str(rport), proto, "-", str(duration), label, det]
    )


def pkt(ts, src="192.168.1.2", sport=1111, dst="203.0.113.7", dport=80, proto=6):
    return PacketTuple(ts, "dev", None, src, sport, dst, dport, proto, 0, 60, Direction.EGRESS)


IOT23_HEADER = (
    "#separator \\x09\n#unset_field\t-\n"
    "#fields\tts\tuid\tid.orig_h\tid.orig_p\tid.resp_h\tid.resp_p\tproto\tservice\t"
    "duration\ttunnel_parents   label   detailed-label\n"
)


class Iot23FormatTests(unittest.TestCase):
    """The real files pack the last three columns into one space-separated field."""

    def test_space_packed_label_columns_are_expanded(self):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".labeled", delete=False)
        tmp.write(
            IOT23_HEADER
            + "100.0\tuid\t192.168.1.2\t1111\t203.0.113.7\t80\ttcp\t-\t5.0\t"
            + "(empty)   Malicious   PartOfAHorizontalPortScan\n"
        )
        tmp.close()
        self.addCleanup(Path(tmp.name).unlink)
        index = load_conn_log(Path(tmp.name))
        self.assertEqual(index.flow_labels, {"Malicious": 1})
        self.assertEqual(index.label_of(pkt(101.0)), MALICIOUS)


class ConnLogTests(unittest.TestCase):
    def write(self, *rows):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".labeled", delete=False)
        tmp.write(HEADER + "\n".join(rows) + "\n")
        tmp.close()
        self.addCleanup(Path(tmp.name).unlink)
        return load_conn_log(Path(tmp.name))

    def test_fields_are_read_from_the_header_not_fixed_positions(self):
        index = self.write(row(100.0, "192.168.1.2", 1111, "203.0.113.7", 80, "tcp", 5.0, "Benign"))
        self.assertEqual(index.flows, 1)
        self.assertEqual(index.label_of(pkt(101.0)), BENIGN)

    def test_direction_does_not_matter_for_matching(self):
        index = self.write(
            row(100.0, "192.168.1.2", 1111, "203.0.113.7", 80, "tcp", 5.0, "Malicious", "C&C")
        )
        reply = pkt(101.0, src="203.0.113.7", sport=80, dst="192.168.1.2", dport=1111)
        self.assertEqual(index.label_of(reply), MALICIOUS)

    def test_packets_outside_the_flow_window_do_not_match(self):
        index = self.write(row(100.0, "192.168.1.2", 1111, "203.0.113.7", 80, "tcp", 5.0, "Benign"))
        self.assertIsNone(index.label_of(pkt(120.0)))
        self.assertIsNone(index.label_of(pkt(90.0)))
        self.assertEqual(index.label_of(pkt(105.5)), BENIGN)  # within 1 s tolerance

    def test_unset_duration_is_treated_as_an_instant_not_forever(self):
        index = self.write(row(100.0, "192.168.1.2", 1111, "203.0.113.7", 80, "tcp", "-", "Benign"))
        self.assertEqual(index.label_of(pkt(100.2)), BENIGN)
        self.assertIsNone(index.label_of(pkt(130.0)))

    def test_conflicting_labels_for_one_packet_are_unknown_not_benign(self):
        index = self.write(
            row(100.0, "192.168.1.2", 1111, "203.0.113.7", 80, "tcp", 10.0, "Benign"),
            row(100.0, "192.168.1.2", 1111, "203.0.113.7", 80, "tcp", 10.0, "Malicious", "Attack"),
        )
        self.assertIsNone(index.label_of(pkt(105.0)))
        self.assertEqual(index.ambiguous, 1)

    def test_unmatched_packets_are_counted_and_never_benign(self):
        index = self.write(row(100.0, "192.168.1.2", 1111, "203.0.113.7", 80, "tcp", 5.0, "Benign"))
        self.assertIsNone(index.label_of(pkt(101.0, dport=443)))
        self.assertEqual(index.unmatched, 1)
        self.assertEqual(index.matched, 0)

    def test_label_counts_are_reported(self):
        index = self.write(
            row(100.0, "192.168.1.2", 1111, "203.0.113.7", 80, "tcp", 5.0, "Benign"),
            row(200.0, "192.168.1.2", 2222, "203.0.113.8", 80, "udp", 5.0, "Malicious", "Attack"),
        )
        self.assertEqual(index.flow_labels, {"Benign": 1, "Malicious": 1})

    def test_label_case_follows_the_dataset_not_our_spelling(self):
        index = self.write(row(100.0, "192.168.1.2", 1111, "203.0.113.7", 80, "tcp", 5.0, "benign"))
        self.assertEqual(index.label_of(pkt(101.0)), BENIGN)
        self.assertEqual(index.flow_labels, {BENIGN: 1})
        self.assertTrue(index.has_usable_labels)

    def test_a_log_without_verdicts_is_not_usable(self):
        index = self.write(row(100.0, "192.168.1.2", 1111, "203.0.113.7", 80, "tcp", 5.0, "-"))
        self.assertFalse(index.has_usable_labels)

    def test_malformed_file_is_rejected(self):
        for text in ("", "#fields\tts\tuid\n", HEADER + "1\t2\n"):
            tmp = tempfile.NamedTemporaryFile("w", suffix=".labeled", delete=False)
            tmp.write(text)
            tmp.close()
            self.addCleanup(Path(tmp.name).unlink)
            with self.subTest(text=text[:20]), self.assertRaises(LabelError):
                load_conn_log(Path(tmp.name))


if __name__ == "__main__":
    unittest.main()
