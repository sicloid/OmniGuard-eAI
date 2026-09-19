"""Single-device capture-to-enforcement composition for the G8 core path.

The caller owns an isolated lab, a trusted pinned detector, capture lifetime and
an independent sink.  Telemetry is deliberately outside this safety path.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass

from gateway.controller import ControlStep, StateEnforcementController
from gateway.pipeline import PacketCapture, WindowFeaturePipeline


@dataclass(frozen=True)
class CoreCycle:
    """Internal decisions and kernel receipts from one bounded capture read."""

    tick: ControlStep
    observation_loss: ControlStep | None
    windows: tuple[ControlStep, ...]


class GatewayCore:
    """Poll one capture and keep window-health resets in sync with policy N.

    The caller must poll continuously with a finite capture timeout so lease expiry
    is checked even when no packets arrive.  A failed read invalidates observation
    before the original capture error is propagated.  on_control_step records tick
    and observation-loss receipts immediately, including on that exception path.
    Kernel failure remains fatal until the controller is explicitly reconciled.
    """

    def __init__(
        self,
        pipeline: WindowFeaturePipeline,
        controller: StateEnforcementController,
        *,
        utc_clock=time.time,
        monotonic_clock=time.monotonic,
        on_control_step: Callable[[ControlStep], None] | None = None,
    ):
        if not isinstance(pipeline, WindowFeaturePipeline):
            raise TypeError("pipeline must be a WindowFeaturePipeline")
        if not isinstance(controller, StateEnforcementController):
            raise TypeError("controller must be a StateEnforcementController")
        self.pipeline = pipeline
        self.controller = controller
        self.utc_clock = utc_clock
        self.monotonic_clock = monotonic_clock
        self.on_control_step = on_control_step
        self._generation = pipeline.reset_generation

    def _clock(self) -> dict[str, float]:
        return {"now": self.utc_clock(), "mono": self.monotonic_clock()}

    def _sync_loss(self) -> ControlStep | None:
        if self._generation == self.pipeline.reset_generation:
            return None
        self._generation = self.pipeline.reset_generation
        return self.controller.invalidate(**self._clock())

    def poll(self, capture: PacketCapture, *, timeout: float = 0.25) -> CoreCycle:
        tick = self.controller.tick(**self._clock())
        if self.on_control_step is not None:
            self.on_control_step(tick)
        try:
            vectors = self.pipeline.capture_once(capture, timeout)
        except Exception:
            loss = self._sync_loss()
            if loss is not None and self.on_control_step is not None:
                self.on_control_step(loss)
            raise
        loss = self._sync_loss()
        if loss is not None and self.on_control_step is not None:
            self.on_control_step(loss)
        if loss is not None and vectors:
            raise RuntimeError("window reset returned feature vectors; refusing mixed evidence")
        decisions = tuple(self.controller.process(vector, **self._clock()) for vector in vectors)
        return CoreCycle(tick, loss, decisions)
