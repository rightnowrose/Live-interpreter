"""Copy the bundled models into dist/RoseSI/models.

Run after PyInstaller onedir build:
    python packaging/prepare_models.py dist/RoseSI
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import paths  # noqa: E402


def copy_tree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, symlinks=False)


def main() -> int:
    args = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
    lite = "--lite" in sys.argv[1:]
    if len(args) != 1:
        print("usage: prepare_models.py <dist/RoseSI> [--lite]")
        return 2
    app_dir = Path(args[0]).resolve()
    if not (app_dir / "RoseSI.exe").is_file():
        print(f"not a built app dir: {app_dir}")
        return 2
    models = app_dir / "models"
    models.mkdir(parents=True, exist_ok=True)

    turbo = models / "large-v3-turbo"
    if turbo.exists():
        shutil.rmtree(turbo)

    if lite:
        for name in (paths.PARAKEET_MODEL, "HY-MT1.5-1.8B-GGUF"):
            target = models / name
            if target.exists():
                shutil.rmtree(target)
        cudnn = Path(paths.data_dir()) / "cudnn"
        if cudnn.is_dir():
            copy_tree(cudnn, app_dir / "cudnn")
            dll_bytes = sum(p.stat().st_size for p in (app_dir / "cudnn").iterdir() if p.is_file())
            print(f"copied cuDNN: {cudnn} -> {app_dir / 'cudnn'} ({dll_bytes:,} bytes)")
        else:
            print(f"warning: cuDNN folder not found: {cudnn}; Parakeet will fall back to CPU")
        print(f"Lite build: no ASR/MT models bundled under {models}")
        return 0

    parakeet = Path(paths.parakeet_dir())
    missing = [
        name
        for name, expected in paths.PARAKEET_FILES.items()
        if not (parakeet / name).is_file()
        or (parakeet / name).stat().st_size < int(expected * paths.PARAKEET_MIN_BYTES)
    ]
    if missing:
        print(f"Parakeet model incomplete at {parakeet}: {', '.join(missing)}")
        return 3
    copy_tree(parakeet, models / paths.PARAKEET_MODEL)
    print(f"copied ASR: {parakeet} -> {models / paths.PARAKEET_MODEL}")

    mt = Path(paths.resolve_local_mt_model("hy-mt-1.8b-q4"))
    if not mt.is_file():
        print("HY-MT1.5-1.8B GGUF not found")
        return 4
    mt_dst = models / "HY-MT1.5-1.8B-GGUF" / mt.name
    mt_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(mt, mt_dst)
    print(f"copied MT:  {mt} -> {mt_dst}")

    cudnn = Path(paths.data_dir()) / "cudnn"
    if cudnn.is_dir():
        copy_tree(cudnn, app_dir / "cudnn")
        dll_bytes = sum(p.stat().st_size for p in (app_dir / "cudnn").iterdir() if p.is_file())
        print(f"copied cuDNN: {cudnn} -> {app_dir / 'cudnn'} ({dll_bytes:,} bytes)")
    else:
        print(f"warning: cuDNN folder not found: {cudnn}; Parakeet will fall back to CPU")

    parakeet_files = models / paths.PARAKEET_MODEL
    parakeet_bytes = sum(p.stat().st_size for p in parakeet_files.iterdir() if p.is_file())
    print(f"Parakeet total: {parakeet_bytes:,} bytes")
    print(f"MT GGUF:       {mt_dst.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
