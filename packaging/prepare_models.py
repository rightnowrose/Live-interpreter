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
    if len(sys.argv) != 2:
        print("usage: prepare_models.py <dist/RoseSI>")
        return 2
    app_dir = Path(sys.argv[1]).resolve()
    if not (app_dir / "RoseSI.exe").is_file():
        print(f"not a built app dir: {app_dir}")
        return 2
    models = app_dir / "models"
    models.mkdir(parents=True, exist_ok=True)

    turbo = Path(paths.resolve_asr_model("large-v3-turbo"))
    if not (turbo / "model.bin").is_file():
        print(f"large-v3-turbo not found: {turbo}")
        return 3
    copy_tree(turbo, models / "large-v3-turbo")
    print(f"copied ASR: {turbo} -> {models / 'large-v3-turbo'}")

    mt = Path(paths.resolve_local_mt_model("hy-mt-1.8b-q4"))
    if not mt.is_file():
        print("HY-MT1.5-1.8B GGUF not found")
        return 4
    mt_dst = models / "HY-MT1.5-1.8B-GGUF" / mt.name
    mt_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(mt, mt_dst)
    print(f"copied MT:  {mt} -> {mt_dst}")

    expected_turbo = models / "large-v3-turbo" / "model.bin"
    print(f"ASR model.bin: {expected_turbo.stat().st_size:,} bytes")
    print(f"MT GGUF:       {mt_dst.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
