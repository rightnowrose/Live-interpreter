"""本地 HY-MT1.5 翻译烟雾测试（需要模型文件与 llama-cpp-python）。

用法：
    venv\\Scripts\\python.exe tools\\test_local_mt.py
"""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import paths
from app.config import TranslateSettings
from app.glossary import GlossaryTerm, TermHit
from app.translator import TranslationService


def main() -> int:
    model = paths.resolve_local_mt_model("hy-mt-1.8b-q4")
    print("model:", model)
    if not model:
        print("FAIL: model not downloaded")
        return 2

    settings = TranslateSettings(
        provider="local",
        local_model="hy-mt-1.8b-q4",
        local_model_path="",
        local_gpu_layers=99,
        target_lang="zh",
        style="口语",
        temperature=0.7,
        max_tokens=0,
    )
    service = TranslationService(settings, "", memory=None)
    ok, reason = service.readiness()
    print("readiness:", ok, reason)
    if not ok:
        return 3

    ok, message = service.test_connection()
    print("test_connection:", ok, message)
    if not ok:
        return 4

    text = "本日の会議では、新しい翻訳モデルの遅延と品質について説明します。"
    hits = [
        TermHit(
            term=GlossaryTerm(
                term_id=1,
                bank_id=1,
                bank_name="test",
                src="翻訳モデル",
                dst="翻译模型",
                aliases=(),
                case_sensitive=False,
                whole_word=False,
                priority=0,
            ),
            start=0,
            end=5,
            matched="翻訳モデル",
        )
    ]
    deltas: list[str] = []
    started = time.perf_counter()
    result = service.translate(
        text, hits, [], "ja", on_delta=lambda piece: deltas.append(piece)
    )
    elapsed = (time.perf_counter() - started) * 1000
    print("translation:", result.text)
    print(
        f"ttfb={result.ttfb_ms:.0f}ms total={result.total_ms:.0f}ms wall={elapsed:.0f}ms "
        f"deltas={len(deltas)} model={result.model}"
    )
    if not result.text.strip():
        return 5
    if "翻译模型" not in result.text:
        print("WARN: glossary term not found in output")
    service.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
