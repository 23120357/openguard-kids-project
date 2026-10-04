"""Interactive-session activity and locking helpers used by the visible Tray."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from dataclasses import dataclass

DESKTOP_SWITCHDESKTOP = 0x0100


class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


@dataclass(frozen=True)
class ActivitySample:
    idle_seconds: float
    session_locked: bool


def sample_activity() -> ActivitySample:
    if os.name != "nt":
        raise RuntimeError("Windows activity sampling is only available on Windows")
    return ActivitySample(idle_seconds=_idle_seconds(), session_locked=_session_locked())


def lock_workstation() -> bool:
    if os.name != "nt":
        return False
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.LockWorkStation.restype = wintypes.BOOL
    return bool(user32.LockWorkStation())


def _idle_seconds() -> float:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    info = LASTINPUTINFO(cbSize=ctypes.sizeof(LASTINPUTINFO))
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        raise OSError(ctypes.get_last_error(), "GetLastInputInfo failed")
    kernel32.GetTickCount.restype = wintypes.DWORD
    # LASTINPUTINFO is a 32-bit tick count. DWORD subtraction keeps this correct
    # across the roughly 49-day wraparound boundary.
    elapsed_ms = (kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF
    return max(0.0, elapsed_ms / 1000.0)


def _session_locked() -> bool:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.OpenInputDesktop.restype = wintypes.HANDLE
    user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user32.SwitchDesktop.argtypes = [wintypes.HANDLE]
    user32.SwitchDesktop.restype = wintypes.BOOL
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    desktop = user32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
    if not desktop:
        return True
    try:
        return not bool(user32.SwitchDesktop(desktop))
    finally:
        user32.CloseDesktop(desktop)
