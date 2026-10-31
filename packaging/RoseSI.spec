# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller onedir spec for RoseSI.

Models are copied into dist/RoseSI/models after the build by
packaging/build.ps1; they are not embedded in _internal to avoid duplication.
"""

from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

root = Path(SPECPATH)
project = root.parent

datas = [
    (str(project / "app" / "ui" / "assets"), "app/ui/assets"),
    (str(project / "extension"), "extension"),
    (str(project / "packaging" / "models.json"), "."),
    (str(project / "README.md"), "."),
    (str(project / "THIRD_PARTY_NOTICES.md"), "."),
    (str(project / "LICENSES"), "LICENSES"),
]

# faster-whisper ships the Silero VAD ONNX asset.
datas += collect_data_files("faster_whisper")

hiddenimports = [
    "app.asr_parakeet",
    "_cffi_backend",
    "cffi",
    "faster_whisper",
    "ctranslate2",
    "av",
    "tokenizers",
    "onnxruntime",
    "llama_cpp",
    "soundcard",
    "ahocorasick",
    "soxr",
    "websockets",
    "httpx",
    "httpcore",
    "h11",
    "certifi",
    "huggingface_hub",
    "filelock",
    "tqdm",
    "fsspec",
    "openpyxl",
    "openpyxl.cell._writer",
]

for pkg in ("faster_whisper", "ctranslate2", "llama_cpp"):
    try:
        hiddenimports += collect_submodules(pkg)
    except Exception:
        pass

binaries = []
for pkg in ("ctranslate2", "llama_cpp", "av", "tokenizers", "onnxruntime", "soxr"):
    try:
        binaries += collect_dynamic_libs(pkg)
    except Exception:
        pass

# CTranslate2 and llama.cpp both need the CUDA runtime. End users generally do
# not have the CUDA toolkit installed, so ship the three DLLs next to the app.
cuda_bin = Path(r"G:\cuda12.8\bin")
for name in ("cudart64_12.dll", "cublas64_12.dll", "cublasLt64_12.dll"):
    dll = cuda_bin / name
    if dll.is_file():
        binaries.append((str(dll), "."))

a = Analysis(
    [str(project / "main.py")],
    pathex=[str(project)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "scipy",
        "pandas",
        "IPython",
        "pytest",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtQuick",
        "PySide6.QtQml",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RoseSI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project / "packaging" / "app.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="RoseSI",
)
