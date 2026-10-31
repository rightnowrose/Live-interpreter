"""生成 UI 截图（离屏）。用法：QT_QPA_PLATFORM=offscreen python tools/screenshot.py"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("SI_DATA_DIR", str(Path(__file__).resolve().parents[1] / "testdata_ui"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.config import ConfigStore  # noqa: E402
from app.db import Database  # noqa: E402
from app.pipeline import Pipeline  # noqa: E402
from app.ui.overlay import OverlayWindow  # noqa: E402
from app.ui.kana import KanaWindow  # noqa: E402
from app.ui.theme import apply_theme  # noqa: E402
from app.ui.workbench import WorkbenchWindow  # noqa: E402


def wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main() -> None:
    out = Path(__file__).resolve().parents[1] / "docs" / "screenshots"
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)
    apply_theme(app)
    config = ConfigStore()
    db = Database()
    pipeline = Pipeline(config, db)
    overlay = OverlayWindow(config)
    workbench = WorkbenchWindow(pipeline, db, config)
    overlay.show()
    workbench.show()
    wait(400)

    samples = [
        ("a1", "The latency is mainly determined by the VAD silence duration.", "延迟主要由 VAD 的静音确认时长决定。"),
        ("a2", "Terminology is injected only when the current sentence hits an entry.", "术语只在当前句子命中条目时才会注入。"),
    ]
    for seg_id, src, dst in samples:
        overlay.add_segment({"id": seg_id, "src": src, "state": "done"})
        overlay.set_source(seg_id, src, partial=False)
        overlay.set_translation(seg_id, dst, state="done")
        workbench.dashboard.add_item({"id": seg_id, "src": src, "dst": dst, "state": "done"})
    overlay.add_segment(
        {
            "id": "a3",
            "src": "A maximum segment length prevents long monologues from inflating latency.",
            "state": "output",
        }
    )
    overlay.set_source("a3", "A maximum segment length prevents long monologues from inflating latency.", partial=False)
    overlay.set_translation(
        "a3",
        "最大段长可以防止长独白把延迟无限拉长，",
        state="output",
        via_tm=True,
        terms=[{"src": "maximum segment length", "dst": "最大段长"}],
    )
    workbench.dashboard.add_item(
        {
            "id": "a3",
            "src": "A maximum segment length prevents long monologues from inflating latency.",
            "dst": "最大段长可以防止长独白把延迟无限拉长，",
            "state": "output",
        }
    )
    workbench.dashboard.set_stats(
        {"asr_ms": 520, "ttfb_ms": 380, "e2e_ms": 1150, "segments": 3, "audio_source": "系统声音 · Realtek", "language": "英语"}
    )
    workbench.dashboard.set_status("running", "同传中")
    workbench._on_status("running", "同传中")
    overlay.set_status("running", "同传中")
    overlay.set_stats({"asr_ms": 520, "ttfb_ms": 380, "e2e_ms": 1150})
    overlay.set_level(0.62)
    workbench.show_page("dashboard")
    wait(500)
    overlay.grab().save(str(out / "overlay.png"))
    workbench.grab().save(str(out / "workbench_dashboard.png"))

    workbench.show_page("terms")
    wait(300)
    workbench.grab().save(str(out / "workbench_terms.png"))

    db.upsert_tm("The latency is mainly determined by the VAD silence duration.", "延迟主要由 VAD 的静音确认时长决定。", tgt_lang="zh")
    db.upsert_tm("Terminology is injected only when the current sentence hits an entry.", "术语只在当前句子命中条目时才会注入。", tgt_lang="zh")
    workbench.corpus.reload()
    workbench.show_page("corpus")
    wait(300)
    workbench.grab().save(str(out / "workbench_corpus.png"))

    candidate_ids = [
        db.upsert_candidate(
            src="今回の会議では、新しい翻訳モデルの遅延と品質について説明します。",
            dst="在本次会议中，我们将说明新翻译模型的延迟和质量。",
            src_lang="ja",
            tgt_lang="zh",
            quality=0.92,
            occurrences=2,
            duration_s=4.2,
            chars=31,
            mt_model="deepseek-flash",
            asr_model="large-v3-turbo",
            terms=[{"src": "翻訳モデル", "dst": "翻译模型"}],
            flags=["term_hit"],
            asr_avg_logprob=-0.22,
            asr_no_speech_prob=0.02,
        ),
        db.upsert_candidate(
            src="この機能はまだ実験段階ですので、ご注意ください。",
            dst="这个功能还在实验阶段，请注意。",
            src_lang="ja",
            tgt_lang="zh",
            quality=0.88,
            occurrences=1,
            duration_s=3.1,
            chars=23,
            mt_model="deepseek-flash",
            asr_model="large-v3-turbo",
            flags=["low_asr"],
            asr_avg_logprob=-0.71,
            asr_no_speech_prob=0.08,
        ),
    ]
    workbench.corpus.reload()
    workbench.corpus.tabs.setCurrentIndex(1)
    wait(300)
    workbench.grab().save(str(out / "workbench_corpus_pending.png"))
    workbench.corpus.tabs.setCurrentIndex(0)
    db.delete_candidates(candidate_ids)
    workbench.corpus.reload()

    if db.session_exists("demo_session"):
        db.delete_session("demo_session")
    db.create_session("demo_session", "10-23 14:20 同传", "en", "zh", "系统声音 · Realtek", "large-v3-turbo / cuda / int8_float16")
    db.add_segment("demo_session", "d1", 1, 0.0, 3.2, samples[0][1], 420, [])
    db.update_segment_translation("d1", samples[0][2], 360, 1280, False)
    db.add_segment("demo_session", "d2", 2, 3.6, 7.1, samples[1][1], 390, [])
    db.update_segment_translation("d2", samples[1][2], 330, 1105, False)
    db.finish_session("demo_session", 31.0)
    workbench.history.reload()
    workbench.show_page("history")
    wait(300)
    workbench.grab().save(str(out / "workbench_history.png"))

    workbench.export.reload()
    workbench.show_page("export")
    wait(300)
    workbench.grab().save(str(out / "workbench_export.png"))

    workbench.show_page("settings")
    wait(300)
    workbench.grab().save(str(out / "workbench_settings.png"))

    config.settings.translate.provider = "local"
    live_model = (
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "LocalInterpreter"
        / "models"
        / "HY-MT1.5-1.8B-GGUF"
        / "HY-MT1.5-1.8B-Q4_K_M.gguf"
    )
    config.settings.translate.local_model_path = str(live_model) if live_model.is_file() else ""
    config.save()
    workbench.settings.load()
    wait(300)
    workbench.toast.hide()
    workbench.grab().save(str(out / "workbench_settings_local.png"))

    workbench.show_page("dashboard")
    workbench.dashboard.refresh_engine_info()
    wait(300)
    workbench.toast.hide()
    workbench.grab().save(str(out / "workbench_dashboard_local.png"))

    kana = KanaWindow()
    kana.resize(680, 780)
    kana.show()
    wait(300)
    kana.grab().save(str(out / "kana_window_full.png"))
    kana.close()

    workbench._on_status("running", "同传中")
    workbench._toggle_sidebar()
    wait(300)
    workbench.grab().save(str(out / "workbench_collapsed.png"))
    workbench._toggle_sidebar()
    wait(200)

    print("saved", out)
    pipeline.shutdown()
    db.close()


if __name__ == "__main__":
    main()
