"""Read and write the current-user Auto HDR registry entries.

Both locations live under HKEY_CURRENT_USER, so this does not need elevation.
The first change writes an initial backup. Each later change keeps a one-step undo.
"""

from __future__ import annotations

import json
import os
import winreg
from pathlib import Path

from registry_prefs import (
    GLOBAL_SETTINGS_VALUE,
    LEAVE,
    MANAGED_GPU_KEYS,
    GameEntry,
    apply_d3d_behaviors,
    apply_global_swap,
    exe_filename,
    exe_stem,
    global_swap_enabled,
    is_managed_gpu_value,
    is_owned_d3d_behaviors,
    normalize_exe_path,
    preference_fields,
    ten_bit_enabled,
    update_game_preference,
)

DIRECT3D_PATH = r"Software\Microsoft\Direct3D"
GPU_PREF_PATH = r"Software\Microsoft\DirectX\UserGpuPreferences"
GRAPHICS_SETTINGS_PATH = r"Software\Microsoft\DirectX\GraphicsSettings"
SWAP_CACHE_VALUE = "SwapEffectUpgradeCache"
_STRING_TYPES = (winreg.REG_SZ, winreg.REG_EXPAND_SZ)
_SNAPSHOT_TYPES = (winreg.REG_SZ, winreg.REG_EXPAND_SZ, winreg.REG_DWORD)


def _access(*, read: bool = False, write: bool = False) -> int:
    access = winreg.KEY_WOW64_64KEY
    if read:
        access |= winreg.KEY_READ
    if write:
        access |= winreg.KEY_SET_VALUE
    return access


def app_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = Path(base) / "ForceAutoHDR"
    path.mkdir(parents=True, exist_ok=True)
    return path


def initial_backup_path() -> Path:
    return app_data_dir() / "initial-backup.json"


def undo_path() -> Path:
    return app_data_dir() / "undo.json"


def _enum_subkeys(path: str):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, _access(read=True)) as key:
            index = 0
            while True:
                try:
                    yield winreg.EnumKey(key, index)
                except OSError:
                    return
                index += 1
    except FileNotFoundError:
        return


def _enum_values(path: str):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, _access(read=True)) as key:
            index = 0
            while True:
                try:
                    yield winreg.EnumValue(key, index)
                except OSError:
                    return
                index += 1
    except FileNotFoundError:
        return


def _open_key(path: str):
    try:
        return winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            path,
            0,
            _access(read=True, write=True),
        )
    except FileNotFoundError:
        return winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER,
            path,
            0,
            _access(read=True, write=True),
        )


def _query(path: str, value_name: str):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, _access(read=True)) as key:
            return winreg.QueryValueEx(key, value_name)
    except (FileNotFoundError, OSError):
        return None


def _query_string(path: str, value_name: str) -> str | None:
    found = _query(path, value_name)
    if found is None:
        return None
    value, value_type = found
    if value_type in _STRING_TYPES and isinstance(value, str):
        return value
    return None


def _same_path(left: str, right: str) -> bool:
    return os.path.normcase(normalize_exe_path(left)) == os.path.normcase(normalize_exe_path(right))


def _json_value(value, value_type: int):
    if value_type == winreg.REG_DWORD:
        return int(value)
    return value


def _snapshot_values(path: str) -> list[dict]:
    recorded = []
    for name, value, value_type in _enum_values(path):
        if value_type not in _SNAPSHOT_TYPES:
            continue
        if value_type in _STRING_TYPES and not isinstance(value, str):
            continue
        recorded.append({"name": name, "data": _json_value(value, value_type), "type": int(value_type)})
    return recorded


def capture_snapshot() -> dict:
    direct3d = []
    for key_name in _enum_subkeys(DIRECT3D_PATH):
        direct3d.append({"name": key_name, "values": _snapshot_values(rf"{DIRECT3D_PATH}\{key_name}")})
    cache = _query(GRAPHICS_SETTINGS_PATH, SWAP_CACHE_VALUE)
    if cache is None or cache[1] != winreg.REG_DWORD:
        swap_cache = {"existed": False, "value": None}
    else:
        swap_cache = {"existed": True, "value": int(cache[0])}
    return {
        "gpu_values": _snapshot_values(GPU_PREF_PATH),
        "direct3d": direct3d,
        "swap_cache": swap_cache,
    }


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def ensure_initial_backup() -> None:
    target = initial_backup_path()
    if target.exists():
        return
    _write_json(target, capture_snapshot())


def save_undo_snapshot() -> None:
    _write_json(undo_path(), capture_snapshot())


def undo_available() -> bool:
    return undo_path().is_file()


def _prepare_write() -> None:
    ensure_initial_backup()
    save_undo_snapshot()


def _restore_values(path: str, values: list[dict]) -> None:
    wanted = {item["name"]: item for item in values}
    with _open_key(path) as key:
        current = []
        index = 0
        while True:
            try:
                current.append(winreg.EnumValue(key, index))
            except OSError:
                break
            index += 1
        for name, _value, value_type in current:
            if value_type not in _SNAPSHOT_TYPES:
                continue
            if name not in wanted:
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    pass
        for item in values:
            winreg.SetValueEx(key, item["name"], 0, int(item["type"]), item["data"])


def restore_snapshot(snapshot: dict) -> None:
    _restore_values(GPU_PREF_PATH, snapshot.get("gpu_values", []))
    wanted_keys = {item["name"] for item in snapshot.get("direct3d", [])}
    for key_name in list(_enum_subkeys(DIRECT3D_PATH)):
        if key_name not in wanted_keys:
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, rf"{DIRECT3D_PATH}\{key_name}")
            except OSError:
                pass
    for item in snapshot.get("direct3d", []):
        _restore_values(rf"{DIRECT3D_PATH}\{item['name']}", item.get("values", []))
    cache = snapshot.get("swap_cache") or {"existed": False, "value": None}
    if cache.get("existed"):
        with _open_key(GRAPHICS_SETTINGS_PATH) as key:
            winreg.SetValueEx(key, SWAP_CACHE_VALUE, 0, winreg.REG_DWORD, int(cache["value"]))
    else:
        try:
            with _open_key(GRAPHICS_SETTINGS_PATH) as key:
                winreg.DeleteValue(key, SWAP_CACHE_VALUE)
        except FileNotFoundError:
            pass


def undo_last_change() -> None:
    path = undo_path()
    if not path.is_file():
        raise FileNotFoundError("There is no change to undo.")
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    restore_snapshot(snapshot)
    path.unlink(missing_ok=True)


def _managed_gpu_values():
    for name, value, value_type in _enum_values(GPU_PREF_PATH):
        if name == GLOBAL_SETTINGS_VALUE:
            continue
        if value_type not in _STRING_TYPES or not isinstance(value, str):
            continue
        if is_managed_gpu_value(value):
            yield name, value


def _file_missing(path: str | None) -> bool:
    return bool(path) and not os.path.isfile(path)


def _entry(key_name: str | None, path: str | None, exe_name: str, value: str, behaviors: str | None) -> GameEntry:
    strength, gpu, swap = preference_fields(value)
    return GameEntry(
        key_name=key_name,
        exe_path=path,
        exe_name=exe_name,
        strength=strength,
        ten_bit=ten_bit_enabled(behaviors),
        gpu_preference=gpu,
        swap_effect=swap,
        file_missing=_file_missing(path),
    )


def list_games() -> list[GameEntry]:
    """Games this tool forced on. Other Direct3D keys are left out of the list."""
    prefs = list(_managed_gpu_values())
    entries: list[GameEntry] = []
    matched_paths: set[str] = set()
    for key_name in _enum_subkeys(DIRECT3D_PATH):
        behaviors = _query_string(rf"{DIRECT3D_PATH}\{key_name}", "D3DBehaviors")
        if not is_owned_d3d_behaviors(behaviors):
            continue
        name_value = _query_string(rf"{DIRECT3D_PATH}\{key_name}", "Name") or f"{key_name}.exe"
        stem = exe_stem(name_value).lower() or key_name.lower()
        matches = [
            (path, value)
            for path, value in prefs
            if exe_stem(path).lower() in {stem, key_name.lower()}
        ]
        if matches:
            for path, value in matches:
                matched_paths.add(os.path.normcase(path))
                entries.append(_entry(key_name, path, exe_filename(path) or name_value, value, behaviors))
        else:
            entries.append(
                GameEntry(
                    key_name=key_name,
                    exe_path=None,
                    exe_name=name_value,
                    strength=None,
                    ten_bit=ten_bit_enabled(behaviors),
                    file_missing=False,
                )
            )

    for path, value in prefs:
        if os.path.normcase(path) in matched_paths:
            continue
        entries.append(_entry(None, path, exe_filename(path), value, None))

    entries.sort(key=lambda entry: (entry.exe_name.lower(), (entry.exe_path or "").lower()))
    return entries


def read_global_swap() -> bool:
    return global_swap_enabled(_query_string(GPU_PREF_PATH, GLOBAL_SETTINGS_VALUE))


def _existing_gpu_name(exe_path: str) -> tuple[str, str, int]:
    for name, value, value_type in _enum_values(GPU_PREF_PATH):
        if name == GLOBAL_SETTINGS_VALUE or not _same_path(name, exe_path):
            continue
        if value_type not in _STRING_TYPES or not isinstance(value, str):
            raise OSError(f"GPU preference for {exe_filename(exe_path)} is not a text value.")
        return name, value, value_type
    return normalize_exe_path(exe_path), "", winreg.REG_SZ


def _write_gpu_value(value_name: str, text: str, value_type: int) -> None:
    with _open_key(GPU_PREF_PATH) as key:
        if text:
            winreg.SetValueEx(key, value_name, 0, value_type, text)
        else:
            try:
                winreg.DeleteValue(key, value_name)
            except FileNotFoundError:
                pass


def _write_behaviors(key_name: str, filename: str, ten_bit: bool | None) -> None:
    behavior_path = rf"{DIRECT3D_PATH}\{key_name}"
    existing = _query_string(behavior_path, "D3DBehaviors") or ""
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER,
        behavior_path,
        0,
        _access(write=True),
    ) as key:
        winreg.SetValueEx(key, "Name", 0, winreg.REG_SZ, filename)
        winreg.SetValueEx(key, "D3DBehaviors", 0, winreg.REG_SZ, apply_d3d_behaviors(existing, ten_bit))


def _find_key_name(stem: str) -> str:
    for existing in _enum_subkeys(DIRECT3D_PATH):
        if existing.lower() == stem.lower():
            return existing
    return stem


def upsert_game(
    exe_path: str,
    strength: int,
    *,
    ten_bit: bool | None = None,
    gpu_preference=LEAVE,
    swap_effect=LEAVE,
    previous_path: str | None = None,
    prepare: bool = True,
) -> str:
    """Create or update one game. Returns the executable file name."""
    if prepare:
        _prepare_write()
    exe_path = normalize_exe_path(exe_path)
    if not os.path.isfile(exe_path):
        raise FileNotFoundError(f"Executable not found:\n{exe_path}")

    filename = exe_filename(exe_path)
    if os.path.splitext(filename)[1].lower() != ".exe":
        raise ValueError("Select the game's .exe file.")
    stem = exe_stem(filename)
    if not stem:
        raise ValueError("Could not read the executable name.")

    if ten_bit is None:
        current = _query_string(rf"{DIRECT3D_PATH}\{_find_key_name(stem)}", "D3DBehaviors")
        ten_bit = True if current is None else ten_bit_enabled(current)

    key_name = _find_key_name(stem)
    _write_behaviors(key_name, filename, ten_bit)

    value_name, existing, value_type = _existing_gpu_name(exe_path)
    updated = update_game_preference(existing, strength, gpu_preference, swap_effect)
    _write_gpu_value(value_name, updated, value_type)

    if previous_path and not _same_path(previous_path, exe_path):
        _strip_path(previous_path)
        old_stem = exe_stem(previous_path).lower()
        if old_stem and old_stem != stem.lower() and not _stem_still_has_gpu_pref(old_stem):
            old_key = _find_key_name(old_stem)
            if old_key.lower() == old_stem:
                try:
                    winreg.DeleteKey(winreg.HKEY_CURRENT_USER, rf"{DIRECT3D_PATH}\{old_key}")
                except FileNotFoundError:
                    pass
    return filename


def set_global_swap(enabled: bool, *, prepare: bool = True) -> None:
    if prepare:
        _prepare_write()
    current = _query_string(GPU_PREF_PATH, GLOBAL_SETTINGS_VALUE) or ""
    _write_gpu_value(GLOBAL_SETTINGS_VALUE, apply_global_swap(current, enabled), winreg.REG_SZ)
    with _open_key(GRAPHICS_SETTINGS_PATH) as key:
        winreg.SetValueEx(key, SWAP_CACHE_VALUE, 0, winreg.REG_DWORD, 1 if enabled else 0)


def _stem_still_has_gpu_pref(stem: str) -> bool:
    target = stem.lower()
    for path, _value in _managed_gpu_values():
        if exe_stem(path).lower() == target:
            return True
    return False


def _strip_path(exe_path: str) -> None:
    matches = [
        (name, value, value_type)
        for name, value, value_type in _enum_values(GPU_PREF_PATH)
        if name != GLOBAL_SETTINGS_VALUE and _same_path(name, exe_path)
    ]
    for name, value, value_type in matches:
        if value_type not in _STRING_TYPES or not isinstance(value, str):
            raise OSError(f"GPU preference for {exe_filename(exe_path)} is not a text value.")
        _write_gpu_value(name, strip_auto_hdr(value), value_type)


def strip_auto_hdr(value: str) -> str:
    from registry_prefs import strip_preference_fields

    return strip_preference_fields(value, MANAGED_GPU_KEYS)


def remove_game(entry: GameEntry, *, prepare: bool = True) -> str:
    """Remove Auto HDR for one row. GPU preference and flip model stay on that path."""
    if prepare:
        _prepare_write()
    stems: set[str] = set()
    if entry.exe_path:
        _strip_path(entry.exe_path)
        stems.add(exe_stem(entry.exe_path).lower())
    else:
        stem = (entry.key_name or exe_stem(entry.exe_name)).lower()
        stems.add(stem)
        for path, _value in list(_managed_gpu_values()):
            if exe_stem(path).lower() == stem:
                _strip_path(path)

    if entry.key_name:
        stems.add(entry.key_name.lower())
        if not any(_stem_still_has_gpu_pref(stem) for stem in stems):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, rf"{DIRECT3D_PATH}\{entry.key_name}")
            except FileNotFoundError:
                pass
    return entry.exe_name


def import_profile(games: list[dict], *, remove_missing: bool, global_swap: bool | None) -> str:
    if not games and global_swap is None and not remove_missing:
        raise ValueError("That profile has no games to import.")
    _prepare_write()
    removed = 0
    if remove_missing:
        wanted = {os.path.normcase(normalize_exe_path(item["path"])) for item in games}
        for entry in list_games():
            if entry.exe_path and os.path.normcase(normalize_exe_path(entry.exe_path)) in wanted:
                continue
            remove_game(entry, prepare=False)
            removed += 1
    saved = 0
    skipped: list[str] = []
    for item in games:
        if not os.path.isfile(item["path"]):
            skipped.append(item["path"])
            continue
        upsert_game(
            item["path"],
            item["strength"],
            ten_bit=item["ten_bit"],
            gpu_preference=item["gpu_preference"],
            swap_effect=item["swap_effect"],
            prepare=False,
        )
        saved += 1
    if global_swap is not None:
        set_global_swap(global_swap, prepare=False)
    message = f"Imported {saved} game{'s' if saved != 1 else ''}."
    if removed:
        message += f" Removed {removed}."
    if skipped:
        message += f" Skipped {len(skipped)} missing file{'s' if len(skipped) != 1 else ''}."
    return message


def add_games(paths: list[str], strength: int) -> str:
    if not paths:
        raise ValueError("No executables to add.")
    _prepare_write()
    for path in paths:
        upsert_game(path, strength, ten_bit=None, prepare=False)
    count = len(paths)
    return f"Saved Auto HDR for {count} game{'s' if count != 1 else ''}."


def set_strength_for_all(strength: int) -> str:
    _prepare_write()
    saved = 0
    skipped = 0
    for entry in list_games():
        if not entry.exe_path or entry.file_missing:
            skipped += 1
            continue
        upsert_game(entry.exe_path, strength, ten_bit=None, prepare=False)
        saved += 1
    if saved == 0:
        raise ValueError("No saved games have an executable path to update.")
    message = f"Updated strength for {saved} game{'s' if saved != 1 else ''}."
    if skipped:
        message += f" Skipped {skipped} without a file."
    return message

