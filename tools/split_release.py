"""Split a release artifact into GitHub-safe parts and write SHA256.txt.

GitHub release assets are capped at 2 GiB per file. Parts default to 1.9 GB,
which leaves room for HTTP overhead and keeps each upload below the limit.

Usage:
    python tools/split_release.py release/RoseSI-1.2.0-Setup.exe
    python tools/split_release.py release/RoseSI-1.2.0-Setup.exe --part-size 1900000000
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

DEFAULT_PART_SIZE = 1_900_000_000
SHA_NAME = "SHA256.txt"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def split_file(path: Path, out_dir: Path, part_size: int) -> list[Path]:
    if part_size >= 2 * 1024**3:
        raise SystemExit("part size must be below GitHub's 2 GiB per-asset limit")
    if not path.is_file():
        raise SystemExit(f"not a file: {path}")

    parts: list[Path] = []
    with path.open("rb") as source:
        index = 1
        while True:
            first = source.read(1)
            if not first:
                break
            part = out_dir / f"{path.name}.part{index:03d}"
            with part.open("wb") as target:
                target.write(first)
                remaining = part_size - 1
                while remaining:
                    chunk = source.read(min(8 * 1024 * 1024, remaining))
                    if not chunk:
                        break
                    target.write(chunk)
                    remaining -= len(chunk)
            parts.append(part)
            index += 1
    return parts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--part-size", type=int, default=DEFAULT_PART_SIZE)
    args = parser.parse_args()

    artifact = args.artifact.resolve()
    out_dir = (args.out_dir or artifact.parent).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    parts = split_file(artifact, out_dir, args.part_size)
    lines = [f"{sha256_file(artifact)}  {artifact.name}"]
    for part in parts:
        lines.append(f"{sha256_file(part)}  {part.name}")

    (out_dir / SHA_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"full:  {artifact.name} ({artifact.stat().st_size:,} bytes)")
    for part in parts:
        print(f"part:  {part.name} ({part.stat().st_size:,} bytes)")
    print(f"hash:  {out_dir / SHA_NAME}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
