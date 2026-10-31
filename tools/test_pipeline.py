"""端到端管线测试：TTS -> 指定输出设备 -> 环回采集 -> VAD/ASR -> 演示翻译 -> SQLite。

用法：python tools/test_pipeline.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["SI_DATA_DIR"] = tempfile.mkdtemp(prefix="si_pipeline_")
os.environ["PYTHONIOENCODING"] = "utf-8"

import numpy as np  # noqa: E402
from soxr import resample  # noqa: E402

from PySide6.QtCore import QCoreApplication  # noqa: E402

from app.config import ConfigStore  # noqa: E402
from app.db import Database  # noqa: E402
from app.pipeline import Pipeline  # noqa: E402

SPEAKER_ID = os.environ.get("SI_TEST_SPEAKER_ID", "")
MODEL = str(
    Path(os.environ["USERPROFILE"])
    / ".cache/huggingface/hub/models--mobiuslabsgmbh--faster-whisper-large-v3-turbo/snapshots"
    / "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf"
)
SAMPLE = ROOT / "tests" / "assets" / "sample_en.wav"


def load_wav() -> np.ndarray:
    with wave.open(str(SAMPLE), "rb") as w:
        sr = w.getframerate()
        ch = w.getnchannels()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        if ch > 1:
            data = data.reshape(-1, ch).mean(axis=1)
        if sr != 48000:
            data = resample(data, sr, 48000).astype(np.float32)
    return data


def play(data: np.ndarray) -> None:
    import soundcard as sc

    speaker = sc.get_speaker(SPEAKER_ID) if SPEAKER_ID else sc.default_speaker()
    with speaker.player(samplerate=48000, channels=1) as player:
        block = 4800
        for start in range(0, len(data), block):
            player.play(data[start : start + block])
            time.sleep(len(data[start : start + block]) / 48000)


def main() -> None:
    app = QCoreApplication(sys.argv)
    config = ConfigStore()
    config.settings.demo_mode = True
    config.settings.audio.source = "system"
    config.settings.audio.system_device = SPEAKER_ID
    config.settings.asr.model = "large-v3-turbo"
    config.settings.asr.model_path = MODEL
    config.settings.asr.language = "en"
    config.settings.asr.silence_ms = 400
    config.settings.translate.target_lang = "zh"
    config.save()

    db = Database()
    pipeline = Pipeline(config, db)
    events = []

    pipeline.status_changed.connect(lambda s, m: print("STATUS", s, m))
    pipeline.segment_started.connect(lambda d: print("START", d["id"], round(d["t_start"], 2)))
    pipeline.source_partial.connect(lambda i, t: print("PART", i, t))
    pipeline.source_final.connect(
        lambda i, t, m: (print("FINAL", i, round(m["asr_ms"]), t), events.append(("final", t)))
    )
    pipeline.translation_done.connect(
        lambda i, t, m: (
            print("DONE", i, round(m["total_ms"]), t),
            events.append(("done", t, m["total_ms"])),
        )
    )
    pipeline.translation_failed.connect(lambda i, m: print("FAIL", i, m))
    pipeline.toast.connect(lambda m, l: print("TOAST", l, m))
    pipeline.error.connect(lambda m: print("ERROR", m))

    pipeline.start()
    deadline = time.time() + 60
    while not pipeline.running and time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)
        if pipeline._stats.get("state") == "error":
            raise SystemExit("启动失败")
    print("RUNNING, playing audio")
    audio = load_wav()
    threading.Thread(target=play, args=(audio,), daemon=True).start()

    end = time.time() + len(audio) / 48000 + 6
    while time.time() < end:
        app.processEvents()
        time.sleep(0.05)
    print("STOPPING")
    pipeline.stop()
    deadline = time.time() + 20
    while pipeline.running and time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)
    time.sleep(0.5)
    app.processEvents()

    sessions = db.list_sessions()
    print("\nSESSIONS", [(s.id, s.segment_count, round(s.avg_latency_ms)) for s in sessions])
    for session in sessions[:1]:
        for seg in db.session_segments(session.id):
            print("SEG", seg.seq, round(seg.total_ms), seg.src, "=>", seg.dst)
    pipeline.shutdown()
    db.close()
    if not events:
        raise SystemExit("没有产生翻译事件")
    print("\nPIPELINE TEST PASSED", len(events))


if __name__ == "__main__":
    main()
