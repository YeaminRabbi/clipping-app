"""Making sure FFmpeg never outlives the engine.

The desktop app ends the engine by terminating it, which on Windows gives it no chance to stop its own
children: an export or import would carry on unseen, using the CPU and holding its half-written file.
"""

import logging
import sys

log = logging.getLogger("engine.processes")

_job = None  # kept open for as long as the engine lives; Windows ends the group when it closes


def kill_children_with_us() -> bool:
    """Put this process and everything it starts in a group that Windows ends together with it."""
    global _job
    if sys.platform != "win32" or _job is not None:
        return _job is not None
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD),
        ]  # fmt: skip

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("Basic", BasicLimits), ("IoCounters", ctypes.c_uint64 * 6), ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]  # fmt: skip

    kill_on_close, extended_information = 0x2000, 9
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    limits = ExtendedLimits()
    limits.Basic.LimitFlags = kill_on_close
    job = kernel32.CreateJobObjectW(None, None)
    if (
        not job
        or not kernel32.SetInformationJobObject(job, extended_information, ctypes.byref(limits), ctypes.sizeof(limits))
        or not kernel32.AssignProcessToJobObject(job, kernel32.GetCurrentProcess())
    ):
        log.warning("Could not group child processes with the engine (Windows error %s)", ctypes.get_last_error())
        return False
    _job = job
    return True
