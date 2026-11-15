"""Find game executables from local libraries, running processes, and shortcuts.

Nothing here contacts the network. Missing stores are skipped.
"""

from __future__ import annotations

import os
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from registry_prefs import exe_stem, normalize_exe_path

SKIP_EXE_NAMES = frozenset(
    {
        "steam.exe",
        "steamservice.exe",
        "steamwebhelper.exe",
        "steamerrorreporter.exe",
        "unitycrashhandler32.exe",
        "unitycrashhandler64.exe",
        "easyanticheat.exe",
        "easyanticheat_eos.exe",
        "start_protected_game.exe",
        "epicgameslauncher.exe",
        "epicwebhelper.exe",
        "galaxyclient.exe",
        "galaxyclient helper.exe",
        "battle.net.exe",
        "agent.exe",
        "upc.exe",
        "ubisoftconnect.exe",
        "unins000.exe",
        "uninstall.exe",
        "dxsetup.exe",
        "vc_redist.x64.exe",
        "vc_redist.x86.exe",
        "oalinst.exe",
        "crashpad_handler.exe",
        "crashreporter.exe",
        "python.exe",
        "pythonw.exe",
    }
)
SKIP_DIR_NAMES = frozenset(
    {
        "redist",
        "redistributables",
        "_redist",
        "installer",
        "__installer",
        "easyanticheat",
        "battleye",
        "crashreporter",
        "engine",
    }
)
CREATE_NO_WINDOW = 0x08000000


@dataclass(frozen=True)
class InstalledGame:
    source: str
    name: str
    exe_path: str

    def label(self) -> str:
        return f"{self.source}: {self.name} — {os.path.basename(self.exe_path)} — {self.exe_path}"


def is_skipped_executable(path: str) -> bool:
    return os.path.basename(path).lower() in SKIP_EXE_NAMES


def is_system_executable(path: str) -> bool:
    windir = os.path.normcase(os.environ.get("WINDIR", r"C:\Windows"))
    norm = os.path.normcase(normalize_exe_path(path))
    prefixes = (
        windir + "\\system32\\",
        windir + "\\syswow64\\",
        windir + "\\winsxs\\",
        windir + "\\systemapps\\",
    )
    return any(norm.startswith(prefix) for prefix in prefixes)


def tokenize_vdf(text: str) -> list[str]:
    tokens: list[str] = []
    index = 0
    length = len(text)
    while index < length:
        char = text[index]
        if char.isspace():
            index += 1
            continue
        if char in "{}":
            tokens.append(char)
            index += 1
            continue
        if char == '"':
            index += 1
            buffer: list[str] = []
            while index < length:
                if text[index] == "\\" and index + 1 < length:
                    buffer.append(text[index + 1])
                    index += 2
                    continue
                if text[index] == '"':
                    index += 1
                    break
                buffer.append(text[index])
                index += 1
            tokens.append("".join(buffer))
            continue
        start = index
        while index < length and not text[index].isspace() and text[index] not in "{}":
            index += 1
        tokens.append(text[start:index])
    return tokens


def parse_vdf(text: str) -> dict:
    tokens = tokenize_vdf(text)
    cursor = 0

    def parse_object() -> dict:
        nonlocal cursor
        obj: dict = {}
        while cursor < len(tokens) and tokens[cursor] != "}":
            key = tokens[cursor]
            cursor += 1
            if cursor >= len(tokens):
                break
            if tokens[cursor] == "{":
                cursor += 1
                value = parse_object()
                if cursor < len(tokens) and tokens[cursor] == "}":
                    cursor += 1
            else:
                value = tokens[cursor]
                cursor += 1
            obj[key] = value
        return obj

    if tokens and tokens[0] == "{":
        cursor = 1
        return parse_object()
    return parse_object()


def steam_library_paths(vdf_text: str) -> list[str]:
    parsed = parse_vdf(vdf_text)
    root = parsed.get("libraryfolders", parsed)
    if not isinstance(root, dict):
        return []
    paths = []
    for value in root.values():
        if isinstance(value, dict) and value.get("path"):
            paths.append(os.path.normpath(value["path"]))
    return paths


def manifest_install(vdf_text: str) -> tuple[str, str] | None:
    parsed = parse_vdf(vdf_text)
    state = parsed.get("AppState", parsed)
    if not isinstance(state, dict):
        return None
    name = state.get("name") or ""
    installdir = state.get("installdir") or ""
    if not name or not installdir:
        return None
    if installdir.lower() == "steamworks common redistributables":
        return None
    return name, installdir


def name_tokens(display_name: str) -> set[str]:
    cleaned = []
    token = []
    for char in display_name.lower():
        if char.isalnum():
            token.append(char)
        elif token:
            cleaned.append("".join(token))
            token = []
    if token:
        cleaned.append("".join(token))
    return {item for item in cleaned if len(item) >= 3}


def rank_executables(paths: list[str], display_name: str, sizes: dict[str, int] | None = None) -> list[str]:
    tokens = name_tokens(display_name)
    scored: list[tuple[int, str]] = []
    for path in paths:
        if is_skipped_executable(path):
            continue
        stem = exe_stem(path).lower()
        score = 0
        if stem in tokens:
            score += 50
        for token in tokens:
            if token in stem:
                score += 20
        size = 0 if sizes is None else sizes.get(path, 0)
        if sizes is None:
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
        if size >= 1_000_000:
            score += 10
        score -= path.count("\\") + path.count("/")
        scored.append((score, path))
    scored.sort(key=lambda item: (-item[0], item[1].lower()))
    if not scored:
        return []
    if len(scored) == 1 or scored[0][0] - scored[1][0] >= 25:
        return [scored[0][1]]
    return [path for _score, path in scored[:4]]


def find_executables(folder: str, display_name: str, max_depth: int = 4) -> list[str]:
    if not os.path.isdir(folder):
        return []
    found: list[str] = []
    root_depth = folder.rstrip("\\/").count(os.sep)
    for current, dirs, files in os.walk(folder):
        depth = current.rstrip("\\/").count(os.sep) - root_depth
        if depth > max_depth:
            dirs.clear()
            continue
        dirs[:] = [name for name in dirs if name.lower() not in SKIP_DIR_NAMES]
        for filename in files:
            if filename.lower().endswith(".exe") and not is_skipped_executable(filename):
                found.append(os.path.join(current, filename))
    return rank_executables(found, display_name)


def epic_executable(manifest: dict) -> tuple[str, str] | None:
    name = str(manifest.get("DisplayName") or "Epic game")
    location = str(manifest.get("InstallLocation") or "")
    launch = str(manifest.get("LaunchExecutable") or "")
    if manifest.get("bIsIncompleteInstall") in (True, "true", "True"):
        return None
    if not location or not launch:
        return None
    return name, normalize_exe_path(os.path.join(location, launch))


def gog_entry(values: dict) -> tuple[str, str] | None:
    lowered = {str(key).lower(): value for key, value in values.items()}
    name = str(lowered.get("gamename") or "GOG game")
    exe = str(lowered.get("exe") or "")
    folder = str(lowered.get("path") or "")
    if exe and not os.path.isabs(exe) and folder:
        exe = os.path.join(folder, exe)
    if not exe or is_skipped_executable(exe):
        return None
    return name, normalize_exe_path(exe)


def parse_microsoft_game_config(xml_text: str, config_dir: str) -> tuple[str, str] | None:
    root = ET.fromstring(xml_text)
    visuals = root.find(".//ShellVisuals")
    name = "Xbox game"
    if visuals is not None and visuals.attrib.get("DefaultDisplayName"):
        name = visuals.attrib["DefaultDisplayName"]
    executable = root.find(".//ExecutableList/Executable")
    if executable is None or not executable.attrib.get("Name"):
        return None
    exe_name = executable.attrib["Name"]
    full = exe_name if os.path.isabs(exe_name) else os.path.join(config_dir, exe_name)
    if is_skipped_executable(full):
        return None
    return name, normalize_exe_path(full)


def gaming_root_folder(drive: str, content: bytes) -> str | None:
    if content.startswith(b"\xff\xfe") or content.startswith(b"\xfe\xff"):
        text = content.decode("utf-16", errors="ignore")
    elif b"\x00" in content[:8]:
        text = content.decode("utf-16-le", errors="ignore")
    else:
        text = content.decode("utf-8", errors="ignore")
    text = text.replace("\x00", "").strip()
    if not text:
        return None
    if not os.path.isabs(text):
        text = os.path.join(drive, text)
    return os.path.normpath(text)


def _add(found: list[InstalledGame], warnings: list[str], source: str, name: str, path: str) -> None:
    if not path or is_skipped_executable(path) or is_system_executable(path):
        return
    if not os.path.isfile(path):
        return
    found.append(InstalledGame(source, name, normalize_exe_path(path)))


def _steam_games(found: list[InstalledGame], warnings: list[str]) -> None:
    steam = _steam_path()
    if not steam:
        return
    libraries = [steam]
    vdf_path = os.path.join(steam, "steamapps", "libraryfolders.vdf")
    try:
        if os.path.isfile(vdf_path):
            libraries.extend(steam_library_paths(Path(vdf_path).read_text(encoding="utf-8", errors="replace")))
    except OSError as exc:
        warnings.append(f"Steam libraries could not be read ({exc}).")
    seen = set()
    for library in libraries:
        library = os.path.normpath(library)
        key = os.path.normcase(library)
        if key in seen or not os.path.isdir(library):
            continue
        seen.add(key)
        apps = os.path.join(library, "steamapps")
        if not os.path.isdir(apps):
            continue
        try:
            names = os.listdir(apps)
        except OSError:
            continue
        for filename in names:
            if not filename.lower().startswith("appmanifest_") or not filename.lower().endswith(".acf"):
                continue
            manifest_path = os.path.join(apps, filename)
            try:
                parsed = manifest_install(Path(manifest_path).read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            if parsed is None:
                continue
            game_name, installdir = parsed
            folder = os.path.join(apps, "common", installdir)
            for exe in find_executables(folder, game_name):
                _add(found, warnings, "Steam", game_name, exe)


def _steam_path() -> str | None:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
            value, _type = winreg.QueryValueEx(key, "SteamPath")
            if value and os.path.isdir(value):
                return os.path.normpath(value)
    except OSError:
        pass
    for candidate in (r"C:\Program Files (x86)\Steam", r"C:\Program Files\Steam"):
        if os.path.isdir(candidate):
            return candidate
    return None


def _epic_games(found: list[InstalledGame], warnings: list[str]) -> None:
    import json

    root = os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "Epic", "EpicGamesLauncher", "Data", "Manifests")
    if not os.path.isdir(root):
        return
    try:
        names = os.listdir(root)
    except OSError as exc:
        warnings.append(f"Epic manifests could not be read ({exc}).")
        return
    for filename in names:
        if not filename.lower().endswith(".item"):
            continue
        try:
            manifest = json.loads(Path(os.path.join(root, filename)).read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue
        parsed = epic_executable(manifest)
        if parsed:
            _add(found, warnings, "Epic", parsed[0], parsed[1])


def _gog_games(found: list[InstalledGame], warnings: list[str]) -> None:
    import winreg

    roots = (
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\GOG.com\Games"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\GOG.com\Games"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\GOG.com\Games"),
    )
    for hive, path in roots:
        try:
            with winreg.OpenKey(hive, path) as key:
                index = 0
                while True:
                    try:
                        sub = winreg.EnumKey(key, index)
                    except OSError:
                        break
                    index += 1
                    try:
                        with winreg.OpenKey(key, sub) as game_key:
                            values = {}
                            value_index = 0
                            while True:
                                try:
                                    name, data, _type = winreg.EnumValue(game_key, value_index)
                                except OSError:
                                    break
                                value_index += 1
                                if isinstance(data, str):
                                    values[name] = data
                    except OSError:
                        continue
                    parsed = gog_entry(values)
                    if parsed:
                        _add(found, warnings, "GOG", parsed[0], parsed[1])
        except OSError:
            continue


def _xbox_roots() -> list[str]:
    roots = []
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        drive = f"{letter}:\\"
        if not os.path.exists(drive):
            continue
        marker = os.path.join(drive, ".GamingRoot")
        if os.path.isfile(marker):
            try:
                folder = gaming_root_folder(drive, Path(marker).read_bytes())
            except OSError:
                folder = None
            if folder and os.path.isdir(folder):
                roots.append(folder)
        flat = os.path.join(drive, "XboxGames")
        if os.path.isdir(flat):
            roots.append(flat)
    return roots


def _xbox_games(found: list[InstalledGame], warnings: list[str]) -> None:
    seen = set()
    for root in _xbox_roots():
        key = os.path.normcase(os.path.normpath(root))
        if key in seen:
            continue
        seen.add(key)
        try:
            game_names = os.listdir(root)
        except OSError as exc:
            warnings.append(f"Xbox folder {root} could not be read ({exc}).")
            continue
        for game_name in game_names:
            folder = os.path.join(root, game_name)
            if not os.path.isdir(folder):
                continue
            for config in (
                os.path.join(folder, "MicrosoftGame.config"),
                os.path.join(folder, "Content", "MicrosoftGame.config"),
            ):
                if not os.path.isfile(config):
                    continue
                try:
                    parsed = parse_microsoft_game_config(
                        Path(config).read_text(encoding="utf-8", errors="replace"),
                        os.path.dirname(config),
                    )
                except (OSError, ET.ParseError):
                    continue
                if parsed:
                    _add(found, warnings, "Xbox", parsed[0], parsed[1])


def scan_installed_games() -> tuple[list[InstalledGame], list[str]]:
    found: list[InstalledGame] = []
    warnings: list[str] = []
    for scanner in (_steam_games, _epic_games, _gog_games, _xbox_games):
        try:
            scanner(found, warnings)
        except OSError as exc:
            warnings.append(str(exc))
    unique: list[InstalledGame] = []
    seen = set()
    for game in sorted(found, key=lambda item: (item.name.lower(), item.exe_path.lower())):
        key = os.path.normcase(game.exe_path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(game)
    return unique, warnings


def running_executables() -> list[tuple[str, str]]:
    import ctypes
    from ctypes import wintypes

    TH32CS_SNAPPROCESS = 0x00000002
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == wintypes.HANDLE(-1).value:
        raise OSError("Could not list running processes.")
    found: list[tuple[str, str]] = []
    seen = set()
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return []
        while True:
            pid = entry.th32ProcessID
            name = entry.szExeFile
            if pid and pid != os.getpid() and name.lower().endswith(".exe") and not is_skipped_executable(name):
                handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                if handle:
                    try:
                        buffer = ctypes.create_unicode_buffer(32768)
                        size = wintypes.DWORD(len(buffer))
                        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                            path = normalize_exe_path(buffer.value)
                            key = os.path.normcase(path)
                            if key not in seen and not is_system_executable(path) and os.path.isfile(path):
                                seen.add(key)
                                found.append((name, path))
                    finally:
                        kernel32.CloseHandle(handle)
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snapshot)
    found.sort(key=lambda item: item[0].lower())
    return found


def resolve_shortcut(path: str) -> str:
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    env = os.environ.copy()
    env["FORCEHDR_LNK"] = path
    script = (
        "$shell = New-Object -ComObject WScript.Shell; "
        "$shortcut = $shell.CreateShortcut($env:FORCEHDR_LNK); "
        "Write-Output $shortcut.TargetPath"
    )
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=20,
        env=env,
        creationflags=CREATE_NO_WINDOW,
        check=False,
    )
    target = ""
    if completed.stdout:
        lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        if lines:
            target = lines[-1]
    if completed.returncode != 0 or not target:
        detail = (completed.stderr or "").strip()
        raise OSError(detail or "Could not read that shortcut.")
    target = normalize_exe_path(target)
    if os.path.splitext(target)[1].lower() != ".exe":
        raise ValueError(f"That shortcut opens {target or 'a non-executable target'}, not a game executable.")
    if not os.path.isfile(target):
        raise FileNotFoundError(f"Shortcut target was not found:\n{target}")
    return target
