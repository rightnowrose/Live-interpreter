"""Download the Parakeet TDT 0.6B JA ONNX files into the app model directory."""
from __future__ import annotations

import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.paths import PARAKEET_FILES, parakeet_dir  # noqa: E402

BASE = "https://hf-mirror.com/visuall/parakeet-tdt_ctc-0.6b-ja-onnx/resolve/main"


def download(name: str, expected: int) -> None:
    folder = parakeet_dir()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / name
    if target.is_file() and target.stat().st_size >= int(expected * 0.98):
        print(f"OK   {name} ({target.stat().st_size / 1024 / 1024:.0f} MB)")
        return
    part = target.with_suffix(target.suffix + ".part")
    part.unlink(missing_ok=True)
    url = f"{BASE}/{name}"
    print(f"GET  {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "LocalInterpreter/1.3"})
    with urllib.request.urlopen(request, timeout=60) as response, part.open("wb") as handle:
        done = 0
        last = 0.0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)
            done += len(chunk)
            now = time.monotonic()
            if now - last > 0.5:
                last = now
                print(f"     {done / 1024 / 1024:.0f} / {expected / 1024 / 1024:.0f} MB", end="\r")
    if part.stat().st_size < int(expected * 0.98):
        part.unlink(missing_ok=True)
        raise RuntimeError(f"{name} incomplete")
    part.replace(target)
    print(f"\nOK   {name} ({target.stat().st_size / 1024 / 1024:.0f} MB)")


def main() -> int:
    for name, size in PARAKEET_FILES.items():
        download(name, size)
    print(f"Parakeet model ready: {parakeet_dir()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
