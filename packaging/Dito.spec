# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).resolve().parent
datas = [(str(ROOT / "dito.ico"), ".")]
binaries = []
hiddenimports = [
    "tkinter",
    "transformers",
    "torch",
    "torchaudio",
    "accelerate",
    "safetensors",
    "huggingface_hub",
    "tokenizers",
    "numpy",
    "scipy",
    "sounddevice",
    "soundfile",
    "keyboard",
    "pyperclip",
    "noisereduce",
    "psutil",
    "PIL",
    "imageio_ffmpeg",
    "crisperwhisper",
]

for package in ("crisperwhisper", "imageio_ffmpeg", "sounddevice",
                "noisereduce"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

recorder = ROOT / "dist" / "recorder" / "mic_recorder.exe"
if recorder.is_file():
    binaries.append((str(recorder), "."))

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "pytest", "IPython", "notebook"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Dito",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(ROOT / "dito.ico"),
    version=str(ROOT / "packaging" / "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Dito",
)
