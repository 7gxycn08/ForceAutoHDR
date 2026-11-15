# -*- mode: python ; coding: utf-8 -*-
"""Windowed one-file build. UPX is off because it increases antivirus false positives."""

import os

icon = "Resources/hdr.ico" if os.path.exists(os.path.join("Resources", "hdr.ico")) else None

a = Analysis(
    ["ForceAutoHDR.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ForceAutoHDR",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version="file_version_info.txt",
    icon=icon,
)
