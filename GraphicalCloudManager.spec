# -*- mode: python ; coding: utf-8 -*-
"""Cross-platform PyInstaller build spec for Graphical Cloud Manager.

Build with:  pyinstaller --noconfirm --clean GraphicalCloudManager.spec

`keyring` discovers its OS backend at runtime via importlib.metadata entry
points, which PyInstaller's static analysis can't see -- so, like the other
mediaswing apps pick their platform's optional-dependency driver explicitly,
we add the platform's keyring backend as a hidden import here.
"""
import sys

if sys.platform == "darwin":
    keyring_backend = "keyring.backends.macOS"
elif sys.platform == "win32":
    keyring_backend = "keyring.backends.Windows"
else:
    keyring_backend = "keyring.backends.SecretService"

a = Analysis(
    ["src/gcm/app.py"],
    pathex=["src"],
    binaries=[],
    datas=[],
    hiddenimports=["keyring.backends", keyring_backend],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="GraphicalCloudManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="GraphicalCloudManager",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="GraphicalCloudManager.app",
        icon=None,
        bundle_identifier="com.mediaswing.graphicalcloudmanager",
    )
