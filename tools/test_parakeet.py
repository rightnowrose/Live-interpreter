"""Parakeet TDT 0.6B JA smoke test; skipped when the model is absent."""
from __future__ import annotations

import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from app.asr import ASREngine  # noqa: E402
from app.config import ASRSettings  # noqa: E402
from app.paths import PARAKEET_MODEL, parakeet_ready  # noqa: E402


def load_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as handle:
        sample_rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0, sample_rate


def main() -> int:
    if not parakeet_ready():
        print("SKIP Parakeet model not downloaded")
        return 0
    audio_path = ROOT / "tests" / "assets" / "sample_ja.wav"
    if not audio_path.exists():
        print("SKIP tests/assets/sample_ja.wav missing")
        return 0
    audio, sample_rate = load_wav(audio_path)
    engine = ASREngine(
        ASRSettings(model=PARAKEET_MODEL, device="auto", language="ja", warmup=True)
    )
    t0 = time.perf_counter()
    engine.load()
    load_ms = (time.perf_counter() - t0) * 1000
    print(f"load {load_ms:.0f}ms backend={engine.backend} device={engine.device}")
    for label, start, length in (("8s", 30, 8), ("4s", 40, 4)):
        chunk = audio[sample_rate * start : sample_rate * (start + length)]
        t1 = time.perf_counter()
        result = engine.transcribe(chunk, beam_size=5, language="ja")
        elapsed = (time.perf_counter() - t1) * 1000
        print(f"{label} wall={elapsed:.0f}ms asr={result.asr_ms:.0f}ms text={result.text}")
        assert result.text.strip(), f"{label} empty transcription"
    # 短句不能用静音补到 8 秒，否则 TDT 会整句退化成 blank。
    for label, start, length in (("1.4s", 23.87, 1.376), ("2.1s", 115.26, 2.112)):
        chunk = audio[sample_rate * int(start) : sample_rate * int(start) + int(sample_rate * length)]
        result = engine.transcribe(chunk, beam_size=5, language="ja")
        print(f"{label} text={result.text}")
        assert result.text.strip(), f"{label} short utterance was dropped"
    engine.unload()
    print("PARAKEET TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
