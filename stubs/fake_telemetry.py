from core.schema import SCHEMA_VERSION, DeviceState, StateEvent, TelemetryPayload


def fake_telemetry(run_id: str = "stub-run") -> tuple[TelemetryPayload, ...]:
    """Synthetic transitions only; no gateway decision or firewall is executed."""
    states = (
        DeviceState.NORMAL,
        DeviceState.SUSPICIOUS,
        DeviceState.QUARANTINED,
        DeviceState.NORMAL,
    )
    return tuple(
        TelemetryPayload(
            SCHEMA_VERSION,
            run_id,
            f"{run_id}:{index}",
            StateEvent("fixture-device", before, after, "synthetic_fixture", timestamp, None),
        )
        for index, (before, after, timestamp) in enumerate(
            zip(states, states[1:], (10.0, 20.0, 50.0), strict=False)
        )
    )
