"""Live-flow checks: semantic hold, stable preview, translation backpressure.

These are pure-Python checks; no model is loaded.
"""
from __future__ import annotations

import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.asr import ASRWorker
from app.config import ConfigStore
from app.db import Database
from app.pipeline import Pipeline
from app.translator import TranslationCancelled, TranslationResult


def test_semantic_hold() -> None:
    worker = ASRWorker.__new__(ASRWorker)
    worker._preview_lock = threading.Lock()
    worker._preview_seg = "seg"
    worker._preview_text = "今日は晴れで"

    assert worker._should_hold_endpoint("seg") is True, "non-final particle should hold"
    worker._preview_text = "今日は晴れです"
    assert worker._should_hold_endpoint("seg") is False, "です is final"
    worker._preview_text = "今日は晴れです。"
    assert worker._should_hold_endpoint("seg") is False, "trailing period stripped"
    worker._preview_text = "今日は晴れ"
    assert worker._should_hold_endpoint("seg") is False, "no named non-final ending"
    worker._preview_text = "今日は晴れだけど"
    assert worker._should_hold_endpoint("seg") is True, "けど is non-final"
    worker._preview_text = "短い"
    assert worker._should_hold_endpoint("seg") is False, "too short to judge"


def test_stable_preview() -> None:
    worker = ASRWorker.__new__(ASRWorker)
    worker._preview_lock = threading.Lock()
    worker._preview_prev = ""
    worker._preview_text = ""
    assert worker._stable_preview("今日は晴れ") == "今日は晴れ"
    assert worker._stable_preview("今日は晴れです") == "今日は晴れです"
    # Divergent rewrite with only a 3-char common prefix keeps the previous stable text.
    assert worker._stable_preview("今日は雨です") == "今日は晴れです"
    assert worker._stable_preview("今日は雨です") == "今日は晴れです"


class _FakeTranslator:
    def __init__(self) -> None:
        self.started: list[str] = []
        self.cancelled: list[str] = []
        self.lock = threading.Lock()

    def translate(
        self,
        text: str,
        hits,
        context,
        source_lang,
        cancel_event=None,
        on_delta=None,
        allow_tm=True,
    ):
        with self.lock:
            self.started.append(text)
        for _ in range(16):
            if cancel_event is not None and cancel_event.is_set():
                with self.lock:
                    self.cancelled.append(text)
                raise TranslationCancelled()
            time.sleep(0.05)
        if on_delta:
            on_delta("译文")
        return TranslationResult(
            text="译文", ttfb_ms=100.0, total_ms=200.0, model="fake"
        )


def test_translation_backpressure() -> None:
    data_dir = Path(tempfile.mkdtemp(prefix="si_live_flow_"))
    config = ConfigStore(data_dir / "config.json")
    config.settings.translate.auto_learn_mode = "off"
    config.settings.translate.use_tm = False
    config.settings.translate.max_pending = 2
    db = Database(data_dir / "data.db")
    db.create_session("s1", "test", "ja", "zh", "test", "")
    pipeline = Pipeline(config, db)
    pipeline._session_id = "s1"
    pipeline._translator = _FakeTranslator()
    pipeline._executor = ThreadPoolExecutor(max_workers=2)
    pipeline._translation_issue = lambda: ""
    states: list[tuple[str, str]] = []
    pipeline.segment_state.connect(lambda sid, state: states.append((sid, state)))

    for index in range(3):
        pipeline._on_final(
            f"s{index}",
            f"これはテスト{index}です。",
            {
                "start": index * 2.0,
                "end": index * 2.0 + 1.8,
                "asr_ms": 100.0,
                "language": "ja",
                "avg_logprob": -0.2,
            },
        )
        time.sleep(0.03)

    deadline = time.monotonic() + 6.0
    while time.monotonic() < deadline and len(pipeline._translation_queue):
        time.sleep(0.05)
    assert len(pipeline._translation_queue) == 0, "queue should drain"
    assert "これはテスト0です。" in pipeline._translator.cancelled
    assert ("s0", "skipped") in states
    pipeline._executor.shutdown(wait=True)
    db.close()


if __name__ == "__main__":
    test_semantic_hold()
    test_stable_preview()
    test_translation_backpressure()
    print("LIVE FLOW TESTS PASSED")
