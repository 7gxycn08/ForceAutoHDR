"""Read whether this PC can actually show Auto HDR. Never changes the display."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass

QDC_ONLY_ACTIVE_PATHS = 0x00000002
DISPLAYCONFIG_PATH_ACTIVE = 0x00000001
DISPLAYCONFIG_DEVICE_INFO_GET_ADVANCED_COLOR_INFO = 9
ERROR_SUCCESS = 0


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]


class DISPLAYCONFIG_PATH_SOURCE_INFO(ctypes.Structure):
    _fields_ = [
        ("adapterId", LUID),
        ("id", wintypes.UINT),
        ("modeInfoIdx", wintypes.UINT),
        ("statusFlags", wintypes.UINT),
    ]


class DISPLAYCONFIG_RATIONAL(ctypes.Structure):
    _fields_ = [("Numerator", wintypes.UINT), ("Denominator", wintypes.UINT)]


class DISPLAYCONFIG_PATH_TARGET_INFO(ctypes.Structure):
    _fields_ = [
        ("adapterId", LUID),
        ("id", wintypes.UINT),
        ("modeInfoIdx", wintypes.UINT),
        ("outputTechnology", wintypes.UINT),
        ("rotation", wintypes.UINT),
        ("scaling", wintypes.UINT),
        ("refreshRate", DISPLAYCONFIG_RATIONAL),
        ("scanLineOrdering", wintypes.UINT),
        ("targetAvailable", wintypes.BOOL),
        ("statusFlags", wintypes.UINT),
    ]


class DISPLAYCONFIG_PATH_INFO(ctypes.Structure):
    _fields_ = [
        ("sourceInfo", DISPLAYCONFIG_PATH_SOURCE_INFO),
        ("targetInfo", DISPLAYCONFIG_PATH_TARGET_INFO),
        ("flags", wintypes.UINT),
    ]


class DISPLAYCONFIG_MODE_INFO(ctypes.Structure):
    # Only the buffer size matters. Windows writes its own mode records into this array.
    _fields_ = [("blob", ctypes.c_byte * 256)]


class DISPLAYCONFIG_GET_ADVANCED_COLOR_INFO(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.UINT),
        ("size", wintypes.UINT),
        ("adapterId", LUID),
        ("id", wintypes.UINT),
        ("value", wintypes.UINT),
        ("colorEncoding", wintypes.UINT),
        ("bitsPerColorChannel", wintypes.UINT),
    ]


@dataclass(frozen=True)
class DisplayStatus:
    windows_11: bool
    windows_label: str
    display_count: int | None
    hdr_capable: int | None
    hdr_enabled: int | None
    detail: str

    def line(self) -> str:
        parts = [self.windows_label]
        if self.hdr_capable is None:
            parts.append(self.detail or "HDR status unavailable")
        else:
            capable = f"{self.hdr_capable} HDR-capable display" if self.hdr_capable == 1 else f"{self.hdr_capable} HDR-capable displays"
            if self.hdr_enabled:
                state = "HDR is on"
            else:
                state = "HDR is off"
            parts.append(f"{capable} of {self.display_count}, {state}")
        if not self.windows_11:
            parts.append("Auto HDR needs Windows 11")
        return " · ".join(parts)


def windows_label() -> tuple[bool, str]:
    version = sys.getwindowsversion()
    windows_11 = version.build >= 22000
    name = "Windows 11" if windows_11 else "Windows 10" if version.major >= 10 else "Windows"
    return windows_11, f"{name} build {version.build}"


def query_display_status() -> DisplayStatus:
    windows_11, label = windows_label()
    try:
        capable, enabled, count = _query_hdr_displays()
    except OSError as exc:
        return DisplayStatus(windows_11, label, None, None, None, str(exc))
    if count == 0:
        return DisplayStatus(windows_11, label, 0, 0, 0, "No active displays")
    return DisplayStatus(windows_11, label, count, capable, enabled, "")


def _query_hdr_displays() -> tuple[int, int, int]:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.QueryDisplayConfig.argtypes = [
        wintypes.UINT,
        ctypes.POINTER(wintypes.UINT),
        ctypes.POINTER(DISPLAYCONFIG_PATH_INFO),
        ctypes.POINTER(wintypes.UINT),
        ctypes.POINTER(DISPLAYCONFIG_MODE_INFO),
        ctypes.c_void_p,
    ]
    user32.QueryDisplayConfig.restype = ctypes.c_long
    user32.DisplayConfigGetDeviceInfo.argtypes = [ctypes.c_void_p]
    user32.DisplayConfigGetDeviceInfo.restype = ctypes.c_long

    user32.GetDisplayConfigBufferSizes.argtypes = [
        wintypes.UINT,
        ctypes.POINTER(wintypes.UINT),
        ctypes.POINTER(wintypes.UINT),
    ]
    user32.GetDisplayConfigBufferSizes.restype = ctypes.c_long

    path_count = wintypes.UINT(0)
    mode_count = wintypes.UINT(0)
    result = user32.GetDisplayConfigBufferSizes(
        QDC_ONLY_ACTIVE_PATHS,
        ctypes.byref(path_count),
        ctypes.byref(mode_count),
    )
    if result != ERROR_SUCCESS:
        raise OSError(f"Could not query displays (code {result}).")
    if path_count.value == 0:
        return 0, 0, 0

    paths = (DISPLAYCONFIG_PATH_INFO * path_count.value)()
    modes = (DISPLAYCONFIG_MODE_INFO * max(mode_count.value, 1))()
    result = user32.QueryDisplayConfig(
        QDC_ONLY_ACTIVE_PATHS,
        ctypes.byref(path_count),
        paths,
        ctypes.byref(mode_count),
        modes,
        None,
    )
    if result != ERROR_SUCCESS:
        raise OSError(f"Could not query displays (code {result}).")

    capable = 0
    enabled = 0
    seen = 0
    for index in range(path_count.value):
        path = paths[index]
        if not (path.flags & DISPLAYCONFIG_PATH_ACTIVE):
            continue
        info = DISPLAYCONFIG_GET_ADVANCED_COLOR_INFO()
        info.type = DISPLAYCONFIG_DEVICE_INFO_GET_ADVANCED_COLOR_INFO
        info.size = ctypes.sizeof(info)
        info.adapterId = path.targetInfo.adapterId
        info.id = path.targetInfo.id
        info_result = user32.DisplayConfigGetDeviceInfo(ctypes.byref(info))
        if info_result != ERROR_SUCCESS:
            continue
        seen += 1
        if info.value & 0x1:
            capable += 1
        if info.value & 0x2:
            enabled += 1
    if seen == 0:
        raise OSError("Displays are active, but HDR capability could not be read.")
    return capable, enabled, seen
