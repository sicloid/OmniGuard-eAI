"""Per-stage latency and CPU, with the cost of measuring reported alongside.

The pipeline stages named by the V3 review on KAN-42 are measured separately, because
a single end-to-end number cannot say whether a Pi is short of CPU in feature
extraction or in inference. Platform cost (the broker, the database, Grafana) is not
in this process at all and is reported separately by the platform cards; nothing here
silently folds it in.

Three honesty rules are built into the shape of the data rather than left to a README:

- Every figure is either measured or absent with a reason. There is no 0 default.
- `measurement_overhead` is the time this harness spent taking readings around the
  stage window — before it opens and after it closes, so `elapsed` stays the stage's
  own time. It is reported rather than dropped because a harness that adds 8% on top
  of a stage has changed what the surrounding system saw, even though the 8% is not
  inside the latency figure.
- Counters that belong to other components — kernel packet drops from
  `sources/live.py`, telemetry queue overflow from `telemetry/handoff.py` — are
  supplied by the caller, not invented here. When the caller does not supply one it
  stays `None` and is reported as not measured.
"""

from dataclasses import dataclass, field

from measure.clocks import Clock, Duration, UnixInstant
from measure.resources import CpuReading, MemoryReading, read_cpu, read_memory

# The stages the architecture review asked to see apart. A run need not use them all.
STAGES = ("capture", "features", "inference", "policy", "enforcer", "exporter")


@dataclass(frozen=True)
class StageMeasurement:
    """One timed pass through one stage."""

    stage: str
    elapsed: Duration
    measurement_overhead: Duration
    process_cpu_seconds: float
    thread_cpu_seconds: float | None
    rss_bytes_start: int | None
    rss_bytes_end: int | None
    peak_rss_bytes: int | None
    unavailable: tuple[str, ...] = ()

    @property
    def other_thread_cpu_seconds(self) -> float | None:
        """CPU burned by every other thread of this process during the window, or None.

        Not noise to subtract away, and not attributable to any one component: the
        telemetry worker runs here, but so can a native library's worker threads — the
        RF implementation among them. It says work happened beside the stage, not who
        did it. Attributing it to the exporter would be a claim this reading cannot
        support (R2, PR #32).
        """
        if self.thread_cpu_seconds is None:
            return None
        return max(0.0, self.process_cpu_seconds - self.thread_cpu_seconds)

    @property
    def overhead_ratio(self) -> float | None:
        """Measuring cost per unit of stage time. Not a fraction contained in `elapsed`.

        The readings are taken before the window opens and after it closes, so the
        overhead is additional to `elapsed`, not part of it: a ratio of 0.05 means the
        harness added 5% on top of the stage, and the wall cost of the measured pass is
        `elapsed + measurement_overhead`. Reading it as "5% of the reported latency was
        the harness" would understate the stage by exactly that much.
        """
        if self.elapsed.seconds <= 0:
            return None
        return self.measurement_overhead.seconds / self.elapsed.seconds

    @property
    def measured_span_seconds(self) -> float:
        """Wall time this pass actually took, stage plus the readings around it."""
        return self.elapsed.seconds + self.measurement_overhead.seconds


class StageTimer:
    """Context manager measuring one stage. Records even when the stage raises."""

    def __init__(self, recorder: RunRecorder, stage: str):
        if stage not in STAGES:
            raise ValueError(f"unknown stage {stage!r}; expected one of {', '.join(STAGES)}")
        self.recorder, self.stage = recorder, stage
        self._clock = recorder.clock

    def __enter__(self) -> StageTimer:
        overhead_start = self._clock.monotonic()
        self._cpu_start: CpuReading = read_cpu()
        self._memory_start: MemoryReading = read_memory()
        self._started = self._clock.monotonic()
        self._overhead = self._started - overhead_start
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        ended = self._clock.monotonic()
        cpu_end, memory_end = read_cpu(), read_memory()
        overhead_end = self._clock.monotonic()
        # The closing readings happen after the stage, so their cost is added to the
        # declared overhead even though it falls outside the elapsed window.
        overhead = self._overhead + (overhead_end - ended)

        unavailable = []
        for reading in (self._cpu_start, cpu_end):
            if reading.unavailable:
                unavailable.append(reading.unavailable)
        for reading in (self._memory_start, memory_end):
            if reading.unavailable:
                unavailable.append(reading.unavailable)

        thread_seconds = None
        if self._cpu_start.thread_seconds is not None and cpu_end.thread_seconds is not None:
            thread_seconds = cpu_end.thread_seconds - self._cpu_start.thread_seconds

        self.recorder.record(
            StageMeasurement(
                stage=self.stage,
                elapsed=ended - self._started,
                measurement_overhead=overhead,
                process_cpu_seconds=cpu_end.process_seconds - self._cpu_start.process_seconds,
                thread_cpu_seconds=thread_seconds,
                rss_bytes_start=self._memory_start.rss_bytes,
                rss_bytes_end=memory_end.rss_bytes,
                peak_rss_bytes=memory_end.peak_rss_bytes,
                unavailable=tuple(dict.fromkeys(unavailable)),
            ),
            failed=exc_type is not None,
        )
        # Never swallow the stage's exception: a failed run is kept, not hidden.
        return False


@dataclass
class RunCounters:
    """Counters owned by other components. None means not supplied, never zero."""

    kernel_packet_drops: int | None = None
    pipeline_queue_overflows: int | None = None
    telemetry_queue_overflows: int | None = None
    telemetry_events_dropped: int | None = None

    def missing(self) -> tuple[str, ...]:
        return tuple(name for name, value in vars(self).items() if value is None)


@dataclass
class RunRecorder:
    """Collects stage measurements for one run."""

    clock: Clock = field(default_factory=Clock)
    counters: RunCounters = field(default_factory=RunCounters)
    measurements: list[StageMeasurement] = field(default_factory=list)
    failed_stages: list[str] = field(default_factory=list)
    started_at: UnixInstant | None = None

    def __post_init__(self) -> None:
        if self.started_at is None:
            self.started_at = self.clock.now()

    def stage(self, name: str) -> StageTimer:
        return StageTimer(self, name)

    def record(self, measurement: StageMeasurement, *, failed: bool = False) -> None:
        self.measurements.append(measurement)
        if failed:
            self.failed_stages.append(measurement.stage)

    def by_stage(self) -> dict[str, list[StageMeasurement]]:
        grouped: dict[str, list[StageMeasurement]] = {}
        for measurement in self.measurements:
            grouped.setdefault(measurement.stage, []).append(measurement)
        return grouped

    def summary(self) -> dict:
        """A plain dict for the manifest. Absent figures stay absent."""
        stages = {}
        for name, measurements in sorted(self.by_stage().items()):
            elapsed = [m.elapsed.seconds for m in measurements]
            thread_cpu = [m.thread_cpu_seconds for m in measurements]
            peaks = [m.peak_rss_bytes for m in measurements if m.peak_rss_bytes is not None]
            stages[name] = {
                "passes": len(measurements),
                "elapsed_seconds_total": sum(elapsed),
                "elapsed_seconds_max": max(elapsed),
                "measurement_overhead_seconds": sum(
                    m.measurement_overhead.seconds for m in measurements
                ),
                # Overhead is taken outside the elapsed window, so the two add up rather
                # than one containing the other. Published so nobody has to guess which.
                "measured_span_seconds_total": sum(m.measured_span_seconds for m in measurements),
                "process_cpu_seconds": sum(m.process_cpu_seconds for m in measurements),
                "thread_cpu_seconds": (
                    None if any(v is None for v in thread_cpu) else sum(thread_cpu)
                ),
                "peak_rss_bytes": max(peaks) if peaks else None,
                "unavailable": sorted({reason for m in measurements for reason in m.unavailable}),
            }
        return {
            "stages": stages,
            "failed_stages": sorted(set(self.failed_stages)),
            "counters": vars(self.counters).copy(),
            "counters_not_supplied": list(self.counters.missing()),
        }
