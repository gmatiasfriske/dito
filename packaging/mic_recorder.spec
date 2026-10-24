# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).resolve().parent
datas = []
binaries = []
hiddenimports = ["numpy", "sounddevice", "_sounddevice_data"]

package_datas, package_binaries, package_hidden = collect_all("sounddevice")
datas += package_datas
binaries += package_binaries
hiddenimports += package_hidden

a = Analysis(
    [str(ROOT / "dito_app" / "mic_recorder.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "torch", "transformers", "scipy", "matplotlib"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="mic_recorder",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
