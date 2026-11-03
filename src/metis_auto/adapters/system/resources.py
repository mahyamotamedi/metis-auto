"""Peak memory of this process, on Windows, Linux and macOS (no extra library).

Windows: ``PeakWorkingSetSize`` from ``GetProcessMemoryInfo`` (psapi) through
ctypes. Elsewhere: ``resource.getrusage`` (``ru_maxrss`` is KiB on Linux,
bytes on macOS). Returns None when it cannot be measured; callers report
"not measured", never zero. Used by: the dev-slice builder, benchmarks.
"""

from __future__ import annotations

import sys


def peak_rss_bytes() -> int | None:
    if sys.platform == "win32":
        return _windows_peak()
    try:
        import resource
    except ImportError:  # pragma: no cover - other platforms
        return None
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak) if sys.platform == "darwin" else int(peak) * 1024


def _windows_peak() -> int | None:  # pragma: no cover - exercised on Windows
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    counters = Counters()
    counters.cb = ctypes.sizeof(Counters)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(Counters),
        wintypes.DWORD,
    ]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    handle = kernel32.GetCurrentProcess()
    if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
        return None
    return int(counters.PeakWorkingSetSize)


def peak_rss_mb() -> float | None:
    peak = peak_rss_bytes()
    return None if peak is None else round(peak / (1024 * 1024), 1)
