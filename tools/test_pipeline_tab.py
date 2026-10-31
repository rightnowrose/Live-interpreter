"""标签页模式端到端测试：WebSocket PCM -> VAD/ASR -> 演示翻译。"""

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
os.environ["SI_DATA_DIR"] = tempfile.mkdtemp(prefix="si_tabpipe_")

import numpy as np  # noqa: E402
from websockets.sync.client import connect  # noqa: E402
from PySide6.QtCore import QCoreApplication  # noqa: E402

from app.config import ConfigStore  # noqa: E402
from app.db import Database  # noqa: E402
from app.pipeline import Pipeline  # noqa: E402

MODEL = str(
    Path(os.environ["USERPROFILE"])
    / ".cache/huggingface/hub/models--mobiuslabsgmbh--faster-whisper-large-v3-turbo/snapshots"
    / "0a363e9161cbc7ed1431c9597a8ceaf0c4f78fcf"
)


def load_16k() -> np.ndarray:
    with wave.open(str(ROOT / "tests" / "assets" / "sample_en.wav"), "rb") as w:
        sr = w.getframerate()
        ch = w.getnchannels()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        if ch > 1:
            data = data.reshape(-1, ch).mean(axis=1)
        if sr != 16000:
            from soxr import resample

            data = resample(data, sr, 16000).astype(np.float32)
    return data


def stream_audio(url: str, audio: np.ndarray) -> None:
    time.sleep(0.5)
    with connect(url, open_timeout=5) as ws:
        ws.send('{"type":"hello","title":"测试标签页"}')
        block = 1600  # 100 ms
        for start in range(0, len(audio), block):
            ws.send(audio[start : start + block].astype("<f4").tobytes())
            time.sleep(0.1)
        time.sleep(0.5)


def main() -> None:
    app = QCoreApplication(sys.argv)
    config = ConfigStore()
    config.settings.demo_mode = True
    config.settings.audio.source = "tab"
    config.settings.audio.ws_port = 17868
    config.settings.asr.model_path = MODEL
    config.settings.asr.language = "en"
    config.settings.asr.silence_ms = 400
    config.save()

    db = Database()
    pipeline = Pipeline(config, db)
    events = []
    pipeline.status_changed.connect(lambda s, m: print("STATUS", s, m))
    pipeline.source_final.connect(
        lambda i, t, m: (print("FINAL", round(m["asr_ms"]), t), events.append(t))
    )
    pipeline.translation_done.connect(
        lambda i, t, m: (print("DONE", round(m["total_ms"]), t), events.append(t))
    )
    pipeline.toast.connect(lambda m, l: print("TOAST", l, m))

    pipeline.start()
    deadline = time.time() + 60
    while not pipeline.running and time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)
    print("RUNNING")
    audio = load_16k()
    threading.Thread(
        target=stream_audio, args=("ws://127.0.0.1:17868/audio", audio), daemon=True
    ).start()
    end = time.time() + len(audio) / 16000 + 8
    while time.time() < end:
        app.processEvents()
        time.sleep(0.05)
    pipeline.stop()
    while pipeline.running and time.time() < end + 20:
        app.processEvents()
        time.sleep(0.05)
    pipeline.shutdown()

    sessions = db.list_sessions()
    print("SESSIONS", [(s.segment_count, round(s.avg_latency_ms)) for s in sessions])
    for session in sessions[:1]:
        for seg in db.session_segments(session.id):
            print("SEG", seg.seq, round(seg.total_ms), seg.src, "=>", seg.dst)
    db.close()
    if not events:
        raise SystemExit("没有识别/翻译结果")
    print("TAB PIPELINE PASSED", len(events))


if __name__ == "__main__":
    main()
