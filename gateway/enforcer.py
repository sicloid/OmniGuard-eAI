"""Bounded nftables enforcement for the owned OmniGuard gateway namespace.

This module is intentionally smaller than the policy layer. It receives an already
authorised device binding and a bounded lease, applies or removes exactly one element
from the owned nftables set, and verifies the kernel state by readback.

It is not the proposed ADR-0002 EnforcementResult wire contract. EnforcerReceipt
is an internal implementation receipt so KAN-31/KAN-33 can distinguish an intended
policy transition from a kernel mutation. No telemetry, model output or user text is
turned into shell code.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from ipaddress import IPv4Address, ip_address
from math import isfinite
from typing import Protocol, Sequence

NFT_FAMILY = "inet"
NFT_TABLE = "omniguard"
NFT_SET = "quarantined_v4"
DEFAULT_ALLOWED_NAMESPACES = frozenset({"og-b"})
COMMAND_TIMEOUT_SECONDS = 5.0
_NAMESPACE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


class EnforcementError(RuntimeError):
    """The requested mutation could not be proved safe or applied."""


class EnforcementAction(StrEnum):
    APPLIED = "APPLIED"
    RELEASED = "RELEASED"
    ALREADY_APPLIED = "ALREADY_APPLIED"
    ALREADY_RELEASED = "ALREADY_RELEASED"


@dataclass(frozen=True)
class DeviceBinding:
    """The R2-owned mapping the enforcer is authorised to mutate."""

    device_id: str
    ipv4: str
    namespace: str = "og-b"

    def __post_init__(self) -> None:
        if not isinstance(self.device_id, str) or not self.device_id.strip():
            raise ValueError("device_id must be nonempty text")
        try:
            parsed = ip_address(self.ipv4)
        except ValueError as exc:
            raise ValueError("ipv4 must be a valid IPv4 address") from exc
        if not isinstance(parsed, IPv4Address):
            raise ValueError("ipv4 must be an IPv4 address")
        if not isinstance(self.namespace, str) or not _NAMESPACE.fullmatch(self.namespace):
            raise ValueError("namespace must be a simple network namespace name")


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class CommandRunner(Protocol):
    def __call__(self, argv: Sequence[str]) -> CommandResult: ...


class SubprocessRunner:
    """Run fixed argv without a shell. stderr is evidence, never executable input."""

    def __init__(self, *, timeout: float = COMMAND_TIMEOUT_SECONDS):
        if isinstance(timeout, bool) or not isinstance(timeout, int | float) or timeout <= 0:
            raise ValueError("timeout must be a positive number")
        self.timeout = float(timeout)

    def __call__(self, argv: Sequence[str]) -> CommandResult:
        try:
            completed = subprocess.run(
                list(argv),
                shell=False,
                text=True,
                encoding="utf-8",
                capture_output=True,
                timeout=self.timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise EnforcementError(f"could not execute enforcement command: {exc}") from exc
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


@dataclass(frozen=True)
class EnforcerReceipt:
    """Internal kernel-application evidence; not a runtime wire envelope."""

    device_id: str
    ipv4: str
    namespace: str
    action: EnforcementAction
    lease_ms: int | None
    readback_active: bool


class NftEnforcer:
    """Mutate only the owned timeout set inside an explicitly allowed netns.

    Re-applying an already active quarantine is a no-op so repeated anomaly evidence
    cannot silently renew the kernel lease. The policy layer must create a new episode
    before a new lease can be applied.
    """

    def __init__(
        self,
        *,
        runner: CommandRunner | None = None,
        allowed_namespaces: frozenset[str] = DEFAULT_ALLOWED_NAMESPACES,
    ):
        if not allowed_namespaces:
            raise ValueError("at least one owned namespace must be allowed")
        for namespace in allowed_namespaces:
            if not _NAMESPACE.fullmatch(namespace):
                raise ValueError(f"unsafe namespace name: {namespace!r}")
        self._runner = runner or SubprocessRunner()
        self._allowed_namespaces = frozenset(allowed_namespaces)

    def quarantine(
        self,
        binding: DeviceBinding,
        *,
        lease_seconds: float,
        max_lease_seconds: float,
    ) -> EnforcerReceipt:
        self._validate_binding(binding)
        lease_ms = self._lease_ms(lease_seconds, max_lease_seconds)
        self._verify_owned_set(binding.namespace)
        if self._contains(binding):
            return EnforcerReceipt(
                binding.device_id,
                binding.ipv4,
                binding.namespace,
                EnforcementAction.ALREADY_APPLIED,
                None,
                True,
            )

        result = self._nft(
            binding.namespace,
            "add",
            "element",
            NFT_FAMILY,
            NFT_TABLE,
            NFT_SET,
            "{",
            binding.ipv4,
            "timeout",
            f"{lease_ms}ms",
            "}",
        )
        self._require_ok(result, "add quarantine element")
        active = self._contains(binding)
        if not active:
            raise EnforcementError("nft add succeeded but kernel readback did not show the element")
        return EnforcerReceipt(
            binding.device_id,
            binding.ipv4,
            binding.namespace,
            EnforcementAction.APPLIED,
            lease_ms,
            True,
        )

    def release(self, binding: DeviceBinding) -> EnforcerReceipt:
        self._validate_binding(binding)
        self._verify_owned_set(binding.namespace)
        if not self._contains(binding):
            return EnforcerReceipt(
                binding.device_id,
                binding.ipv4,
                binding.namespace,
                EnforcementAction.ALREADY_RELEASED,
                None,
                False,
            )

        result = self._nft(
            binding.namespace,
            "delete",
            "element",
            NFT_FAMILY,
            NFT_TABLE,
            NFT_SET,
            "{",
            binding.ipv4,
            "}",
        )
        self._require_ok(result, "delete quarantine element")
        active = self._contains(binding)
        if active:
            raise EnforcementError("nft delete succeeded but kernel readback still shows the element")
        return EnforcerReceipt(
            binding.device_id,
            binding.ipv4,
            binding.namespace,
            EnforcementAction.RELEASED,
            None,
            False,
        )

    def is_quarantined(self, binding: DeviceBinding) -> bool:
        """Read kernel state for startup/reconcile without changing the lease."""
        self._validate_binding(binding)
        self._verify_owned_set(binding.namespace)
        return self._contains(binding)

    def _validate_binding(self, binding: DeviceBinding) -> None:
        if not isinstance(binding, DeviceBinding):
            raise ValueError("binding must be a DeviceBinding")
        if binding.namespace not in self._allowed_namespaces:
            raise EnforcementError(
                f"namespace {binding.namespace!r} is not in the configured owned namespace set"
            )

    @staticmethod
    def _lease_ms(lease_seconds: float, max_lease_seconds: float) -> int:
        for value, name in (
            (lease_seconds, "lease_seconds"),
            (max_lease_seconds, "max_lease_seconds"),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, int | float)
                or not isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{name} must be a positive finite number")
        if lease_seconds > max_lease_seconds:
            raise ValueError("lease_seconds must not exceed max_lease_seconds")
        lease_ms = int(float(lease_seconds) * 1000)
        if lease_ms < 1:
            raise ValueError("lease_seconds is below nftables millisecond resolution")
        return lease_ms

    def _verify_owned_set(self, namespace: str) -> None:
        result = self._nft(namespace, "list", "set", NFT_FAMILY, NFT_TABLE, NFT_SET)
        self._require_ok(
            result,
            "verify owned nftables set; refusing to create tables or mutate a missing set",
        )

    def _contains(self, binding: DeviceBinding) -> bool:
        result = self._nft(
            binding.namespace,
            "get",
            "element",
            NFT_FAMILY,
            NFT_TABLE,
            NFT_SET,
            "{",
            binding.ipv4,
            "}",
        )
        if result.returncode == 0:
            return True
        return False

    def _nft(self, namespace: str, *args: str) -> CommandResult:
        argv = ("ip", "netns", "exec", namespace, "nft", *args)
        if "flush" in args:
            raise EnforcementError("flush operations are never allowed")
        return self._runner(argv)

    @staticmethod
    def _require_ok(result: CommandResult, operation: str) -> None:
        if result.returncode == 0:
            return
        detail = (result.stderr or result.stdout).strip() or f"exit {result.returncode}"
        raise EnforcementError(f"{operation} failed: {detail}")
