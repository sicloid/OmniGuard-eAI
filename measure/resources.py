"""CPU and memory readings, with "not measured" as a first-class result.

No new dependency: `psutil` would mean regenerating both hash-pinned locks, which are
R2's, for numbers the standard library can already provide. Linux is read from
`/proc`, Windows through the psapi call, and anything else reports that it could not
be read. A platform that cannot supply a figure yields `None` and a stated reason; it
never yields 0, because a zero would be averaged into a result as if it were measured.

Two things this module deliberately does not claim:

- **RSS is not attributed to a stage.** It is a process-wide gauge sampled at stage
  boundaries. Allocators do not return memory promptly, so a per-stage RSS delta would
  read as "this stage used this much", which it does not mean. Peak RSS for the run is
  reported where the platform exposes it, because that is the number a Pi's memory
  budget is actually tested against.
- **CPU is attributed per thread, and the remainder is shown.** `time.thread_time()`
  is the calling thread only; `time.process_time()` covers every thread. Telemetry runs
  on its own worker thread (`telemetry/handoff.py`), so reporting only process CPU
  would credit the measured stage with the exporter's work. Both are recorded, and the
  difference is what the rest of the process did during the same window.
"""

import ctypes
import platform
import time
from dataclasses import dataclass

_SYSTEM = platform.system()


@dataclass(frozen=True)
class MemoryReading:
    """A memory sample, or a stated reason why there is none."""

    rss_bytes: int | None
    peak_rss_bytes: int | None
    source: str
    unavailable: str | None = None

    @property
    def measured(self) -> bool:
        return self.rss_bytes is not None


@dataclass(frozen=True)
class CpuReading:
    """Cumulative CPU seconds. `thread_seconds` is None where the platform lacks it."""

    process_seconds: float
    thread_seconds: float | None
    unavailable: str | None = None


def _linux_memory(status_path: str = "/proc/self/status") -> MemoryReading:
    # The path is a parameter so the parser can be tested on a captured sample from a
    # real Linux /proc without a Linux host; the container's format is in the tests.
    values: dict[str, int] = {}
    try:
        with open(status_path, encoding="ascii") as handle:
            for line in handle:
                name, _, rest = line.partition(":")
                if name in ("VmRSS", "VmHWM"):
                    # "VmRSS:    123456 kB" — the kernel reports kibibytes here.
                    values[name] = int(rest.split()[0]) * 1024
    except (OSError, ValueError, IndexError) as error:
        return MemoryReading(None, None, "linux-proc", f"{status_path} unreadable: {error}")
    if "VmRSS" not in values:
        return MemoryReading(None, None, "linux-proc", f"{status_path} has no VmRSS")
    return MemoryReading(values["VmRSS"], values.get("VmHWM"), "linux-proc")


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_uint32),
        ("PageFaultCount", ctypes.c_uint32),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _windows_memory() -> MemoryReading:
    # Working set is the Windows analogue of RSS: resident pages, not committed bytes.
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # argtypes/restype are required, not decoration: without them ctypes defaults
        # the HANDLE to a 32-bit int and the (HANDLE)-1 pseudo-handle arrives truncated,
        # which the call rejects with ERROR_INVALID_HANDLE on 64-bit Windows.
        kernel32.GetCurrentProcess.argtypes = []
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.K32GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_ProcessMemoryCounters),
            ctypes.c_uint32,
        ]
        kernel32.K32GetProcessMemoryInfo.restype = ctypes.c_int
        counters = _ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        ok = kernel32.K32GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        )
        if not ok:
            code = ctypes.get_last_error()
            return MemoryReading(
                None, None, "windows-psapi", f"GetProcessMemoryInfo failed ({code})"
            )
    except (OSError, AttributeError) as error:
        return MemoryReading(None, None, "windows-psapi", f"psapi unavailable: {error}")
    return MemoryReading(counters.WorkingSetSize, counters.PeakWorkingSetSize, "windows-psapi")


def read_memory() -> MemoryReading:
    if _SYSTEM == "Linux":
        return _linux_memory()
    if _SYSTEM == "Windows":
        return _windows_memory()
    return MemoryReading(None, None, f"{_SYSTEM.lower()}-unsupported", f"no reader for {_SYSTEM}")


def read_cpu() -> CpuReading:
    process_seconds = time.process_time()
    try:
        return CpuReading(process_seconds, time.thread_time())
    except (OSError, AttributeError) as error:
        # Documented as possible on some platforms; report the gap rather than
        # substituting process CPU, which would credit other threads to this stage.
        return CpuReading(process_seconds, None, f"thread CPU unavailable: {error}")
