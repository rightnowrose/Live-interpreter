"""Kotoba-Whisper v2.0-fast 日文识别测试。"""

from __future__ import annotations

import os
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
from faster_whisper import WhisperModel  # noqa: E402

KOTOBA = Path(os.environ["LOCALAPPDATA"]) / "LocalInterpreter/models/kotoba-whisper-v2.0-faster"
TURBO = Path(os.environ["USERPROFILE"]) / ".cache/huggingface/hub/models--mobiuslabsgmbh--faster-whisper-large-v3-turbo/snapshots/0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf"
SAMPLE = ROOT / "tests" / "assets" / "sample_ja.wav"


def load(seconds: float = 30.0) -> np.ndarray:
    with wave.open(str(SAMPLE), "rb") as w:
        sr = w.getframerate()
        frames = min(w.getnframes(), int(sr * seconds))
        audio = np.frombuffer(w.readframes(frames), dtype=np.int16).astype(np.float32) / 32768
    assert sr == 16000
    return audio


def run(name: str, path: Path, audio: np.ndarray) -> None:
    print(f"\n=== {name} ===", flush=True)
    t0 = time.perf_counter()
    model = WhisperModel(str(path), device="cuda", compute_type="int8_float16")
    print(f"load {time.perf_counter() - t0:.2f}s", flush=True)
    t1 = time.perf_counter()
    segments, info = model.transcribe(
        audio,
        language="ja",
        beam_size=5,
        vad_filter=True,
        condition_on_previous_text=False,
        without_timestamps=True,
        temperature=0.0,
    )
    text = "".join(seg.text for seg in segments).strip()
    print(f"decode {time.perf_counter() - t1:.2f}s lang={info.language}", flush=True)
    print(text, flush=True)


def main() -> None:
    audio = load(30)
    print("audio seconds", len(audio) / 16000)
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    if which in ("turbo", "both"):
        run("turbo", TURBO, audio)
    if which in ("kotoba", "both"):
        run("kotoba", KOTOBA, audio)


if __name__ == "__main__":
    main()
