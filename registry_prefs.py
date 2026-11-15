"""Pure helpers for Auto HDR registry values.

Windows stores several GPU settings in one UserGpuPreferences string.
These helpers update only the Auto HDR fields and leave the rest intact.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

APP_VERSION = "1.2.0.0"
APP_VERSION_TUPLE = (1, 2, 0, 0)

# Community value this tool already writes to force Auto HDR on.
AUTO_HDR_ENABLE = "2097"
D3D_BEHAVIORS = "BufferUpgradeOverride=1;BufferUpgradeEnable10Bit=1"
OWNED_D3D_MARKER = "BufferUpgradeOverride"
MANAGED_GPU_KEYS = ("AutoHDRStrength", "AppStatus", "AutoHDREnable")
STRENGTH_PRESETS = (("Mild", 30), ("Standard", 50), ("Strong", 80))
GLOBAL_SETTINGS_VALUE = "DirectXUserGlobalSettings"
PROFILE_VERSION = 1


class _LeaveField:
    """Sentinel: leave this registry field unchanged."""


LEAVE = _LeaveField()


@dataclass(frozen=True)
class GameEntry:
    """One game row. Direct3D is keyed by executable name; GPU prefs by full path."""

    key_name: str | None
    exe_path: str | None
    exe_name: str
    strength: int | None
    ten_bit: bool = False
    gpu_preference: int | None = None
    swap_effect: int | None = None
    file_missing: bool = False

    def label(self) -> str:
        if self.strength is None:
            strength = "strength unknown"
        else:
            strength = f"{self.strength}%"
        path = self.exe_path or "path not recorded"
        missing = "    file missing" if self.file_missing else ""
        return f"{self.exe_name}    {strength}    {path}{missing}"

    def gpu_label(self) -> str:
        if self.gpu_preference == 1:
            return "Power saving"
        if self.gpu_preference == 2:
            return "High performance"
        return "Windows"

    def swap_label(self) -> str:
        if self.swap_effect == 1:
            return "On"
        if self.swap_effect == 0:
            return "Off"
        return "Follow Windows"


def normalize_exe_path(path: str) -> str:
    return os.path.normpath(path.replace("/", "\\"))


def exe_filename(path: str) -> str:
    return os.path.basename(normalize_exe_path(path))


def exe_stem(path_or_name: str) -> str:
    """Executable name without a trailing .exe, keeping the original casing."""
    stem, ext = os.path.splitext(exe_filename(path_or_name))
    if ext.lower() == ".exe" and stem:
        return stem
    return exe_filename(path_or_name)


def preference_parts(value: str) -> list[str]:
    return [part.strip() for part in value.split(";") if part.strip()]


def preference_key(part: str) -> str:
    if "=" in part:
        return part.split("=", 1)[0].strip()
    return part.strip()


def get_preference_field(value: str, name: str) -> str | None:
    for part in preference_parts(value):
        if "=" not in part:
            continue
        key, raw = part.split("=", 1)
        if key.strip() == name:
            return raw.strip()
    return None


def format_preference(parts: list[str]) -> str:
    if not parts:
        return ""
    return ";".join(parts) + ";"


def merge_preference_fields(existing: str, updates: dict[str, str]) -> str:
    """Override named fields and append any that were missing. Other fields stay."""
    seen: set[str] = set()
    merged: list[str] = []
    for part in preference_parts(existing):
        key = preference_key(part)
        if key in updates:
            if key not in seen:
                merged.append(f"{key}={updates[key]}")
                seen.add(key)
            continue
        merged.append(part)
    for key, raw in updates.items():
        if key not in seen:
            merged.append(f"{key}={raw}")
    return format_preference(merged)


def strip_preference_fields(existing: str, keys: tuple[str, ...] | set[str]) -> str:
    removed = set(keys)
    kept = [part for part in preference_parts(existing) if preference_key(part) not in removed]
    return format_preference(kept)


def auto_hdr_updates(strength: int) -> dict[str, str]:
    if not isinstance(strength, int) or isinstance(strength, bool) or not 0 <= strength <= 100:
        raise ValueError("HDR strength must be an integer from 0 to 100.")
    return {
        "AutoHDRStrength": str(strength),
        "AppStatus": "1",
        "AutoHDREnable": AUTO_HDR_ENABLE,
    }


def parse_strength(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        strength = int(value)
    except (TypeError, ValueError):
        return None
    if 0 <= strength <= 100:
        return strength
    return None


def is_managed_gpu_value(value: str) -> bool:
    """True for the Auto HDR signature this tool writes."""
    return get_preference_field(value, "AutoHDREnable") == AUTO_HDR_ENABLE


def is_owned_d3d_behaviors(behaviors: str | None) -> bool:
    return bool(behaviors) and OWNED_D3D_MARKER in behaviors


def parse_gpu_preference(value: str | None) -> int | None:
    """1 is power saving, 2 is high performance. Anything else means Windows decides."""
    if value in ("1", "2"):
        return int(value)
    return None


def parse_swap_effect(value: str | None) -> int | None:
    """1 forces flip model on, 0 forces it off. Missing means follow the global setting."""
    if value in ("0", "1"):
        return int(value)
    return None


def ten_bit_enabled(behaviors: str | None) -> bool:
    return get_preference_field(behaviors or "", "BufferUpgradeEnable10Bit") == "1"


def apply_d3d_behaviors(existing: str, ten_bit: bool | None) -> str:
    """Keep unknown behavior tokens. 10-bit is optional; the override marker stays."""
    updated = merge_preference_fields(existing or "", {"BufferUpgradeOverride": "1"})
    if ten_bit is True:
        updated = merge_preference_fields(updated, {"BufferUpgradeEnable10Bit": "1"})
    elif ten_bit is False:
        updated = strip_preference_fields(updated, {"BufferUpgradeEnable10Bit"})
    return updated


def update_game_preference(
    existing: str,
    strength: int,
    gpu_preference: int | None | _LeaveField = LEAVE,
    swap_effect: int | None | _LeaveField = LEAVE,
) -> str:
    """Merge Auto HDR strength. GPU and flip fields change only when a caller sets them."""
    updated = merge_preference_fields(existing, auto_hdr_updates(strength))
    extra: dict[str, str] = {}
    strip: list[str] = []
    if gpu_preference is not LEAVE:
        if gpu_preference in (1, 2):
            extra["GpuPreference"] = str(gpu_preference)
        elif gpu_preference is None:
            strip.append("GpuPreference")
        else:
            raise ValueError("GPU preference must be Windows default, power saving, or high performance.")
    if swap_effect is not LEAVE:
        if swap_effect in (0, 1):
            extra["SwapEffectUpgradeEnable"] = str(swap_effect)
        elif swap_effect is None:
            strip.append("SwapEffectUpgradeEnable")
        else:
            raise ValueError("Flip model must be follow Windows, on, or off.")
    if extra:
        updated = merge_preference_fields(updated, extra)
    if strip:
        updated = strip_preference_fields(updated, strip)
    return updated


def preference_fields(value: str) -> tuple[int | None, int | None, int | None]:
    return (
        parse_strength(get_preference_field(value, "AutoHDRStrength")),
        parse_gpu_preference(get_preference_field(value, "GpuPreference")),
        parse_swap_effect(get_preference_field(value, "SwapEffectUpgradeEnable")),
    )


def global_swap_enabled(value: str | None) -> bool:
    return get_preference_field(value or "", "SwapEffectUpgradeEnable") == "1"


def apply_global_swap(existing: str, enabled: bool) -> str:
    if enabled:
        return merge_preference_fields(existing or "", {"SwapEffectUpgradeEnable": "1"})
    return strip_preference_fields(existing or "", {"SwapEffectUpgradeEnable"})


def profile_document(games: list[GameEntry], global_swap: bool) -> dict:
    exported = []
    for game in games:
        if not game.exe_path:
            continue
        exported.append(
            {
                "path": normalize_exe_path(game.exe_path),
                "strength": 50 if game.strength is None else game.strength,
                "ten_bit": bool(game.ten_bit),
                "gpu_preference": game.gpu_preference if game.gpu_preference in (1, 2) else None,
                "swap_effect": game.swap_effect if game.swap_effect in (0, 1) else None,
            }
        )
    return {"version": PROFILE_VERSION, "global_swap_effect": bool(global_swap), "games": exported}


def parse_profile(document: dict) -> tuple[list[dict], bool | None]:
    if not isinstance(document, dict):
        raise ValueError("Profile must be a JSON object.")
    version = document.get("version", 1)
    if version != PROFILE_VERSION:
        raise ValueError(f"Unsupported profile version: {version}")
    raw_games = document.get("games", [])
    if not isinstance(raw_games, list):
        raise ValueError("Profile games must be a list.")
    games = []
    for item in raw_games:
        if not isinstance(item, dict) or not item.get("path"):
            raise ValueError("Each profile game needs a path.")
        strength = parse_strength(str(item.get("strength", 50)))
        if strength is None:
            raise ValueError(f"Invalid strength for {item.get('path')}.")
        gpu = item.get("gpu_preference", None)
        swap = item.get("swap_effect", None)
        if gpu is not None and gpu not in (1, 2):
            raise ValueError(f"Invalid GPU preference for {item.get('path')}.")
        if swap is not None and swap not in (0, 1):
            raise ValueError(f"Invalid flip model setting for {item.get('path')}.")
        games.append(
            {
                "path": str(item["path"]),
                "strength": strength,
                "ten_bit": bool(item.get("ten_bit", True)),
                "gpu_preference": gpu,
                "swap_effect": swap,
            }
        )
    global_swap = document.get("global_swap_effect", None)
    if global_swap is not None and not isinstance(global_swap, bool):
        raise ValueError("global_swap_effect must be true or false.")
    return games, global_swap
