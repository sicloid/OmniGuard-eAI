"""KAN-31 bounded enforcer safety and no-renewal tests."""

import unittest
from pathlib import Path

from gateway.enforcer import (
    CommandResult,
    DeviceBinding,
    EnforcementAction,
    EnforcementError,
    NftEnforcer,
)


class FakeNft:
    def __init__(self):
        self.active = set()
        self.commands = []
        self.set_exists = True
        self.fail_add = False
        self.lookup_error = None

    def __call__(self, argv):
        argv = tuple(argv)
        self.commands.append(argv)
        words = argv[5:]
        if words[:2] == ("list", "set"):
            return CommandResult(0 if self.set_exists else 1, "", "missing")
        if words[:2] == ("get", "element"):
            if self.lookup_error is not None:
                return CommandResult(2, "", self.lookup_error)
            ip = words[-2]
            if ip in self.active:
                return CommandResult(0, "element present", "")
            return CommandResult(1, "", "No such element")
        if words[:2] == ("add", "element"):
            if self.fail_add:
                return CommandResult(1, "", "synthetic add failure")
            self.active.add(words[-4])
            return CommandResult(0)
        if words[:2] == ("delete", "element"):
            self.active.discard(words[-2])
            return CommandResult(0)
        raise AssertionError(f"unexpected command: {argv}")


class BindingTests(unittest.TestCase):
    def test_ipv6_and_unsafe_namespace_are_refused(self):
        with self.assertRaises(ValueError):
            DeviceBinding("cam-1", "2001:db8::1")
        with self.assertRaises(ValueError):
            DeviceBinding("cam-1", "10.203.1.2", namespace="og-b; nft flush ruleset")

    def test_only_configured_owned_namespace_can_be_mutated(self):
        fake = FakeNft()
        enforcer = NftEnforcer(runner=fake)
        with self.assertRaises(EnforcementError):
            enforcer.is_quarantined(DeviceBinding("cam-1", "10.203.1.2", namespace="other"))


class EnforcerTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeNft()
        self.enforcer = NftEnforcer(runner=self.fake)
        self.binding = DeviceBinding("cam-1", "10.203.1.2")

    def test_quarantine_uses_timeout_and_verifies_readback(self):
        receipt = self.enforcer.quarantine(self.binding, lease_seconds=30.0, max_lease_seconds=60.0)
        self.assertEqual(receipt.action, EnforcementAction.APPLIED)
        self.assertEqual(receipt.lease_ms, 30000)
        self.assertTrue(receipt.readback_active)
        add = next(command for command in self.fake.commands if "add" in command)
        self.assertEqual(add[:5], ("ip", "netns", "exec", "og-b", "nft"))
        self.assertIn("timeout", add)
        self.assertIn("30000ms", add)
        self.assertNotIn("conntrack", add)
        self.assertNotIn("flush", add)

    def test_same_evidence_does_not_renew_an_existing_kernel_lease(self):
        self.fake.active.add("10.203.1.2")
        before = len(self.fake.commands)
        receipt = self.enforcer.quarantine(self.binding, lease_seconds=30.0, max_lease_seconds=60.0)
        new_commands = self.fake.commands[before:]
        self.assertEqual(receipt.action, EnforcementAction.ALREADY_APPLIED)
        self.assertIsNone(receipt.lease_ms)
        self.assertFalse(any("add" in command for command in new_commands))

    def test_release_removes_and_reads_back(self):
        self.fake.active.add("10.203.1.2")
        receipt = self.enforcer.release(self.binding)
        self.assertEqual(receipt.action, EnforcementAction.RELEASED)
        self.assertFalse(receipt.readback_active)
        self.assertNotIn("10.203.1.2", self.fake.active)

    def test_release_is_idempotent_after_kernel_expiry(self):
        receipt = self.enforcer.release(self.binding)
        self.assertEqual(receipt.action, EnforcementAction.ALREADY_RELEASED)
        self.assertFalse(receipt.readback_active)

    def test_lease_must_be_positive_and_bounded(self):
        for lease, maximum in ((0, 30), (-1, 30), (31, 30), (0.0001, 30)):
            with self.subTest(lease=lease, maximum=maximum), self.assertRaises(ValueError):
                self.enforcer.quarantine(
                    self.binding,
                    lease_seconds=lease,
                    max_lease_seconds=maximum,
                )

    def test_missing_owned_set_is_a_hard_failure_not_an_implicit_create(self):
        self.fake.set_exists = False
        with self.assertRaises(EnforcementError):
            self.enforcer.quarantine(self.binding, lease_seconds=30, max_lease_seconds=30)
        self.assertFalse(any("add" in command for command in self.fake.commands))

    def test_failed_add_never_reports_quarantined(self):
        self.fake.fail_add = True
        with self.assertRaises(EnforcementError):
            self.enforcer.quarantine(self.binding, lease_seconds=30, max_lease_seconds=30)

    def test_unexpected_readback_error_is_not_misreported_as_absent(self):
        self.fake.lookup_error = "Operation not permitted"
        with self.assertRaises(EnforcementError):
            self.enforcer.is_quarantined(self.binding)

    def test_lab_ruleset_enables_kernel_timeout_without_host_flush(self):
        root = Path(__file__).resolve().parents[1]
        ruleset = (root / "lab" / "ruleset.nft").read_text(encoding="utf-8")
        helper = (root / "lab" / "quarantine.sh").read_text(encoding="utf-8")
        self.assertIn("flags timeout", ruleset)
        self.assertNotIn("flush ruleset", ruleset)
        self.assertIn("timeout 30s", helper)
        self.assertNotIn("conntrack -D", helper)


if __name__ == "__main__":
    unittest.main()
