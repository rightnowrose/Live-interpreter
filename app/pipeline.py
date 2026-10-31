"""Real-time interpretation pipeline: audio -> VAD/ASR -> glossary -> streaming translation -> storage."""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any

from PySide6.QtCore import QObject, Signal

from . import audio, paths
from .asr import ASREngine, ASRWorker
from .candidates import evaluate_candidate
from .config import ConfigStore, language_name
from .db import Database
from .glossary import GlossaryMatcher, build_matcher, hits_to_dicts
from .models import LiveSegment, new_id
from .tm import TranslationMemory
from .translator import TranslationCancelled, TranslationError, TranslationService

log = logging.getLogger(__name__)


class Pipeline(QObject):
    segment_started = Signal(dict)
    source_partial = Signal(str, str)
    source_final = Signal(str, str, dict)
    translation_delta = Signal(str, str)
    translation_done = Signal(str, str, dict)
    translation_failed = Signal(str, str)
    segment_state = Signal(str, str)
    segment_dropped = Signal(str)
    glossary_hits = Signal(str, list)
    status_changed = Signal(str, str)
    level_changed = Signal(float)
    toast = Signal(str, str)
    session_started = Signal(dict)
    session_finished = Signal(dict)
    stats_changed = Signal(dict)
    candidates_changed = Signal(int)
    error = Signal(str)

    def __init__(self, config: ConfigStore, db: Database, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.db = db
        self._lock = threading.RLock()
        self._matcher: GlossaryMatcher = build_matcher(db)
        self._memory = self._make_memory()
        self._translator = self._make_translator()
        self._segments: dict[str, LiveSegment] = {}
        self._context: deque[tuple[str, str]] = deque(maxlen=8)
        self._cancel_events: dict[str, threading.Event] = {}
        self._translation_queue: list[tuple[str, float, LiveSegment]] = []
        self._skipped_translations: set[str] = set()
        self._seq = 0
        self._session_id = ""
        self._session_start = 0.0
        self._capture_start = 0.0
        self._running = False
        self._booting = False
        self._stop_requested = False
        self._executor: ThreadPoolExecutor | None = None
        self._engine: ASREngine | None = None
        self._worker: ASRWorker | None = None
        self._capture: audio.CaptureBase | None = None
        self._boot_thread: threading.Thread | None = None
        self._stop_thread: threading.Thread | None = None
        self._audio_label = ""
        self._stats: dict[str, Any] = {
            "asr_ms": 0.0,
            "ttfb_ms": 0.0,
            "e2e_ms": 0.0,
            "segments": 0,
            "queue": 0,
            "lag_ms": 0.0,
            "audio_source": "",
            "language": "",
        }
        self._no_key_notified = False
        self._glossary_size = self._matcher.size

    # ------------------------------------------------------------------ config
    def _make_memory(self) -> TranslationMemory:
        return TranslationMemory(
            self.db,
            self.config.settings.translate.target_lang,
            threshold=self.config.settings.translate.fuzzy_threshold,
            min_quality=self.config.settings.translate.tm_fuzzy_min_quality,
        )

    def _make_translator(self) -> TranslationService:
        service = TranslationService(
            self.config.settings.translate, self.config.api_key, self._memory
        )
        service.demo_mode = bool(self.config.settings.demo_mode)
        return service

    def _translation_issue(self) -> str:
        """当前配置下不能翻译的原因；空字符串表示可翻译。"""
        settings = self.config.settings
        if settings.demo_mode:
            return ""
        translate = settings.translate
        if (translate.provider or "deepseek").strip().lower() in ("local", "hy-mt", "offline"):
            if not paths.resolve_local_mt_model(
                translate.local_model, translate.local_model_path
            ):
                return (
                    "本地翻译模型未下载：请到「设置 → 翻译服务」下载 HY-MT1.5 1.8B，"
                    "或在「模型文件」中指定 GGUF 路径。"
                )
            return ""
        if not self.config.has_api_key:
            return "未配置 DeepSeek API Key，请在设置中填写。"
        return ""

    def reload_glossary(self, silent: bool = False) -> None:
        self._matcher = build_matcher(self.db)
        self._glossary_size = self._matcher.size
        if not silent:
            self.toast.emit(f"术语库已更新：{self._glossary_size} 条启用术语", "info")

    def reload_translation(self) -> None:
        old = self._translator
        self._memory = self._make_memory()
        self._translator = self._make_translator()
        try:
            old.close()
        except Exception:
            pass
        self._no_key_notified = False

    def apply_settings(self) -> None:
        target = self.config.settings.translate.target_lang
        if getattr(self._memory, "tgt_lang", target) != target:
            self.reload_translation()
        else:
            self._translator.update_settings(
                self.config.settings.translate, self.config.api_key
            )
            self._translator.demo_mode = bool(self.config.settings.demo_mode)
            self._memory.threshold = self.config.settings.translate.fuzzy_threshold
            self._memory.min_quality = self.config.settings.translate.tm_fuzzy_min_quality
        self._matcher = build_matcher(self.db)
        self._glossary_size = self._matcher.size

    @property
    def running(self) -> bool:
        return self._running

    @property
    def booting(self) -> bool:
        return self._booting

    @property
    def session_id(self) -> str:
        return self._session_id

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        if self._running or self._booting:
            return
        if self._stop_thread and self._stop_thread.is_alive():
            return
        self._audio_label = self._source_label()
        self._stop_requested = False
        self._booting = True
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="translate")
        self._set_status("loading", "正在准备引擎…")
        self._boot_thread = threading.Thread(target=self._boot, name="pipeline-boot", daemon=True)
        self._boot_thread.start()

    def _boot(self) -> None:
        try:
            settings = self.config.settings
            if settings.audio.source == "tab":
                self._set_status("loading", "等待浏览器扩展连接…")
            if not audio.available() and settings.audio.source != "tab":
                raise RuntimeError("音频组件不可用：缺少 soundcard")

            self._engine = ASREngine(settings.asr)
            if not self._engine.loaded:
                self._set_status("loading", "正在加载本地 Whisper 模型…")
                self._engine.load(lambda msg: self._set_status("loading", msg))
            if self._stop_requested:
                self._booting = False
                self._set_status("idle", "已取消启动")
                return

            if not self._translation_issue() and self._translator.provider == "local":
                self._set_status("loading", "正在加载本地翻译模型…")
                try:
                    self._translator.warmup()
                except Exception as exc:
                    log.exception("本地翻译模型预热失败")
                    self.toast.emit(f"本地翻译模型加载失败：{exc}", "warn")

            self._session_id = new_id()
            self._session_start = time.monotonic()
            self._capture_start = self._session_start
            self._seq = 0
            with self._lock:
                self._segments.clear()
                self._context.clear()
                self._cancel_events.clear()
            self._stats.update(
                {
                    "asr_ms": 0.0,
                    "ttfb_ms": 0.0,
                    "e2e_ms": 0.0,
                    "segments": 0,
                    "audio_source": self._audio_label,
                    "language": language_name(settings.asr.language),
                }
            )
            self.db.create_session(
                self._session_id,
                datetime.now().strftime("%m-%d %H:%M 同传"),
                settings.asr.language,
                settings.translate.target_lang,
                self._audio_label,
                f"{settings.asr.model} / {self._engine.device} / {self._engine.compute_type}",
            )

            self._worker = ASRWorker(
                self._engine,
                settings.asr,
                on_start=self._on_utterance_start,
                on_partial=self._on_partial,
                on_final=self._on_final,
                on_drop=self._on_drop,
                on_error=self._on_asr_error,
                on_status=lambda msg: self._set_status("running", msg),
            )
            self._worker.start()

            self._capture = audio.create_capture(
                settings.audio,
                on_audio=self._on_audio,
                on_level=self._on_level,
                on_error=self._on_audio_error,
                on_status=lambda msg: self._set_status("running", msg),
            )
            self._capture.start()
            self._running = True
            self._booting = False
            self._stats["state"] = "running"
            self.stats_changed.emit(dict(self._stats))
            self._set_status("running", "同传中")
            self.session_started.emit(
                {
                    "id": self._session_id,
                    "title": datetime.now().strftime("%m-%d %H:%M 同传"),
                    "audio_source": self._audio_label,
                }
            )
            if self._translation_issue():
                self.toast.emit(
                    self._translation_issue() + " 当前只识别、不翻译。", "warn"
                )
            log.info("同传已启动 source=%s", self._audio_label)
        except Exception as exc:
            log.exception("启动失败")
            self._booting = False
            self._running = False
            self._cleanup()
            self._set_status("error", f"启动失败：{exc}")
            self.toast.emit(f"启动失败：{exc}", "error")
            self.error.emit(str(exc))

    def stop(self) -> None:
        if not (self._running or self._booting):
            return
        self._stop_requested = True
        self._set_status("stopping", "正在结束…")
        if self._stop_thread and self._stop_thread.is_alive():
            return
        self._stop_thread = threading.Thread(target=self._shutdown, name="pipeline-stop", daemon=True)
        self._stop_thread.start()

    def _shutdown(self) -> None:
        session_id = self._session_id
        try:
            if self._capture:
                self._capture.stop()
            if self._worker:
                self._worker.stop(timeout=8.0)
        except Exception:
            log.exception("停止采集/识别失败")
        self._running = False
        self._booting = False
        with self._lock:
            for event in self._cancel_events.values():
                event.set()
            self._cancel_events.clear()
            self._translation_queue.clear()
            self._skipped_translations.clear()
            self._stats["queue"] = 0
            self._stats["lag_ms"] = 0.0
        executor = self._executor
        self._executor = None
        if executor is not None:
            try:
                # 等待正在进行中的翻译结束/取消，避免退出时数据库被关闭后仍有写入。
                executor.shutdown(wait=True, cancel_futures=True)
            except Exception:
                log.exception("等待翻译线程结束失败")
        duration = time.monotonic() - self._session_start if self._session_start else 0.0
        if session_id:
            try:
                self.db.finish_session(session_id, duration)
            except Exception:
                log.exception("保存会话失败")
            try:
                pending = self.db.candidate_count(status="pending", session_id=session_id)
            except Exception:
                pending = 0
            if pending:
                self.toast.emit(
                    f"本次会话新增 {pending} 条语料候选，可在「语料库 → 待审核」中查看。",
                    "info",
                )
            self.session_finished.emit(
                {
                    "id": session_id,
                    "duration_s": duration,
                    "segments": self._stats.get("segments", 0),
                    "candidates": pending,
                }
            )
        self._session_id = ""
        self._capture = None
        self._worker = None
        self._set_status("idle", "已停止")
        self.stats_changed.emit(dict(self._stats))

    def _cleanup(self) -> None:
        if self._capture:
            try:
                self._capture.stop()
            except Exception:
                pass
        if self._worker:
            try:
                self._worker.stop(timeout=3.0)
            except Exception:
                pass
        self._capture = None
        self._worker = None

    # ------------------------------------------------------------------ callbacks
    def _on_audio(self, block) -> None:
        if self._worker is not None:
            self._worker.feed(block)

    def _on_level(self, level: float) -> None:
        self.level_changed.emit(float(level))

    def _on_audio_error(self, message: str) -> None:
        self.toast.emit(message, "error")
        self._set_status("error", message)
        self.error.emit(message)
        if self._running or self._booting:
            self.stop()

    def _on_asr_error(self, message: str) -> None:
        self.toast.emit(message, "error")
        self.error.emit(message)

    def _on_utterance_start(self, seg_id: str, start_s: float) -> None:
        if not self._session_id:
            return
        with self._lock:
            if seg_id in self._segments:
                return
            self._seq += 1
            seg = LiveSegment(
                id=seg_id, seq=self._seq, t_start=round(start_s, 3), state="listening"
            )
            self._segments[seg_id] = seg
        self.segment_started.emit(seg.as_dict())
        self._set_status("running", "聆听中…")

    def _on_partial(self, seg_id: str, text: str, meta: dict) -> None:
        if not self._session_id:
            return
        with self._lock:
            seg = self._segments.get(seg_id)
            emit_started = False
            if seg is None:
                self._seq += 1
                seg = LiveSegment(
                    id=seg_id,
                    seq=self._seq,
                    t_start=float(meta.get("start", 0.0)),
                    state="listening",
                )
                self._segments[seg_id] = seg
                emit_started = True
            seg.src = text
            seg.t_end = float(meta.get("end", seg.t_end))
            seg.state = "transcribing"
            snapshot = seg.as_dict()
        if emit_started:
            self.segment_started.emit(snapshot)
        self.source_partial.emit(seg_id, text)
        self.segment_state.emit(seg_id, "transcribing")
        self._stats["asr_ms"] = float(meta.get("asr_ms", 0.0))
        self.stats_changed.emit(dict(self._stats))

    def _on_final(self, seg_id: str, text: str, meta: dict) -> None:
        if not self._session_id:
            return
        if not text:
            self._on_drop(seg_id)
            return
        with self._lock:
            seg = self._segments.get(seg_id)
            emit_started = False
            if seg is None:
                self._seq += 1
                seg = LiveSegment(
                    id=seg_id,
                    seq=self._seq,
                    t_start=float(meta.get("start", 0.0)),
                    state="translating",
                )
                self._segments[seg_id] = seg
                emit_started = True
            seg.src = text
            seg.t_start = float(meta.get("start", seg.t_start))
            seg.t_end = float(meta.get("end", seg.t_end))
            seg.asr_ms = float(meta.get("asr_ms", 0.0))
            seg.state = "translating"
            snapshot = seg.as_dict()
            self._stats["asr_ms"] = seg.asr_ms
            self._stats["segments"] = int(self._stats.get("segments", 0)) + 1
            hits = self._matcher.match(text)
            seg.terms = hits_to_dicts(hits)
            speech_end_mono = self._capture_start + seg.t_end
        if emit_started:
            self.segment_started.emit(snapshot)
        self.source_final.emit(seg_id, text, meta)
        self.segment_state.emit(seg_id, "translating")
        self.stats_changed.emit(dict(self._stats))
        if hits:
            self.glossary_hits.emit(seg_id, seg.terms)
        try:
            if not self.db.session_exists(self._session_id):
                # 会话记录被清理/数据库被外部修改时自动补建，避免片段外键失败。
                self.db.create_session(
                    self._session_id,
                    datetime.now().strftime("%m-%d %H:%M 同传"),
                    self.config.settings.asr.language,
                    self.config.settings.translate.target_lang,
                    self._audio_label,
                    f"{self.config.settings.asr.model} / {self._engine.device if self._engine else ''}",
                )
            self.db.add_segment(
                self._session_id,
                seg_id,
                seg.seq,
                seg.t_start,
                seg.t_end,
                text,
                seg.asr_ms,
                seg.terms,
            )
        except Exception:
            log.exception("写入片段失败")

        issue = self._translation_issue()
        if issue:
            self.translation_failed.emit(seg_id, issue)
            self.segment_state.emit(seg_id, "error")
            if not self._no_key_notified:
                self._no_key_notified = True
                self.toast.emit(issue, "warn")
            return

        context_limit = int(self.config.settings.translate.context_sentences)
        context = list(self._context)[-context_limit:] if context_limit > 0 else []
        cancel = threading.Event()
        max_pending = max(1, int(self.config.settings.translate.max_pending or 2))
        skipped: list[str] = []
        with self._lock:
            while len(self._translation_queue) >= max_pending:
                old_id, _old_end, _old_seg = self._translation_queue.pop(0)
                old_cancel = self._cancel_events.get(old_id)
                if old_cancel is not None:
                    old_cancel.set()
                self._skipped_translations.add(old_id)
                skipped.append(old_id)
            self._cancel_events[seg_id] = cancel
            self._translation_queue.append((seg_id, speech_end_mono, seg))
            self._update_queue_stats_locked()
        for old_id in skipped:
            self.translation_failed.emit(old_id, "翻译积压，已跳过")
            self.segment_state.emit(old_id, "skipped")
        if skipped:
            self.toast.emit("翻译积压，已优先处理最新片段。", "warn")
        self.stats_changed.emit(dict(self._stats))
        executor = self._executor
        if executor is None:
            self._translation_finished(seg_id)
            return
        try:
            executor.submit(
                self._translate_job, seg, hits, context, speech_end_mono, cancel, meta
            )
        except RuntimeError:
            pass

    def _update_queue_stats_locked(self) -> None:
        self._stats["queue"] = len(self._translation_queue)
        if self._translation_queue:
            oldest = min(item[1] for item in self._translation_queue)
            self._stats["lag_ms"] = max(0.0, (time.monotonic() - oldest) * 1000.0)
        else:
            self._stats["lag_ms"] = 0.0

    def _translation_finished(self, seg_id: str) -> None:
        with self._lock:
            self._translation_queue = [
                item for item in self._translation_queue if item[0] != seg_id
            ]
            self._skipped_translations.discard(seg_id)
            self._update_queue_stats_locked()
        self.stats_changed.emit(dict(self._stats))

    def _on_drop(self, seg_id: str) -> None:
        with self._lock:
            self._segments.pop(seg_id, None)
        self.segment_dropped.emit(seg_id)

    def _collect_candidate(self, seg: LiveSegment, hits, result, meta: dict) -> None:
        translate = self.config.settings.translate
        mode = (translate.auto_learn_mode or "candidates").strip().lower()
        if mode == "off" or result.via_tm:
            return
        try:
            if self.db.candidate_count(
                session_id=self._session_id or None
            ) >= max(1, int(translate.candidate_max_per_session or 200)):
                return
            draft = evaluate_candidate(
                seg.src,
                seg.dst,
                meta.get("language") or self.config.settings.asr.language,
                translate.target_lang,
                hits,
                duration_s=max(0.0, seg.t_end - seg.t_start),
                mt_model=result.model,
                asr_model=self.config.settings.asr.model,
                session_id=self._session_id or None,
                asr_avg_logprob=meta.get("avg_logprob"),
                asr_no_speech_prob=meta.get("no_speech_prob"),
                min_chars=max(2, int(translate.auto_learn_min_chars or 6)),
                max_chars=max(10, int(translate.auto_learn_max_chars or 80)),
            )
            if draft is None:
                return
            candidate_id = self.db.upsert_candidate(
                src=draft.src,
                dst=draft.dst,
                src_lang=draft.src_lang,
                tgt_lang=draft.tgt_lang,
                quality=draft.quality,
                session_id=draft.session_id,
                duration_s=draft.duration_s,
                chars=draft.chars,
                mt_model=draft.mt_model,
                asr_model=draft.asr_model,
                terms=draft.terms,
                flags=draft.flags,
                asr_avg_logprob=draft.asr_avg_logprob,
                asr_no_speech_prob=draft.asr_no_speech_prob,
            )
            if candidate_id:
                self.candidates_changed.emit(self.db.candidate_count(status="pending"))
        except Exception:
            log.exception("写入语料候选失败")

    def _translate_job(
        self,
        seg: LiveSegment,
        hits,
        context,
        speech_end_mono: float,
        cancel,
        meta: dict | None = None,
    ) -> None:
        first_delta_at: list[float | None] = [None]

        def on_delta(delta: str) -> None:
            if not delta:
                return
            if first_delta_at[0] is None:
                first_delta_at[0] = time.monotonic()
                self.segment_state.emit(seg.id, "output")
            seg.dst += delta
            self.translation_delta.emit(seg.id, seg.dst)

        try:
            if cancel.is_set():
                raise TranslationCancelled()
            result = self._translator.translate(
                seg.src,
                hits,
                context,
                self.config.settings.asr.language,
                cancel_event=cancel,
                on_delta=on_delta,
            )
            if first_delta_at[0] is None and result.text:
                first_delta_at[0] = time.monotonic()
                seg.dst = result.text
                self.translation_delta.emit(seg.id, seg.dst)
            seg.dst = _clean_translation(seg.dst or result.text)
            seg.ttfb_ms = result.ttfb_ms
            seg.total_ms = (
                (first_delta_at[0] - speech_end_mono) * 1000 if first_delta_at[0] else 0.0
            )
            seg.via_tm = result.via_tm
            seg.state = "done"
            try:
                self.db.update_segment_translation(
                    seg.id, seg.dst, seg.ttfb_ms, seg.total_ms, seg.via_tm
                )
            except Exception:
                log.exception("更新片段译文失败")
            self._collect_candidate(seg, hits, result, meta or {})
            with self._lock:
                self._context.append((seg.src, seg.dst))
                self._cancel_events.pop(seg.id, None)
            if result.missing_terms:
                self.toast.emit(
                    "术语未完全命中：" + "、".join(result.missing_terms[:4]), "warn"
                )
            self._stats["ttfb_ms"] = seg.ttfb_ms
            self._stats["e2e_ms"] = seg.total_ms
            self.stats_changed.emit(dict(self._stats))
            self.segment_state.emit(seg.id, "done")
            self.translation_done.emit(
                seg.id,
                seg.dst,
                {
                    **seg.as_dict(),
                    "tm_score": result.tm_score,
                    "model": result.model,
                },
            )
        except TranslationCancelled:
            with self._lock:
                self._cancel_events.pop(seg.id, None)
                skipped = seg.id in self._skipped_translations
            if skipped:
                self.segment_state.emit(seg.id, "skipped")
            else:
                self.segment_state.emit(seg.id, "done" if seg.dst else "aborted")
        except TranslationError as exc:
            with self._lock:
                self._cancel_events.pop(seg.id, None)
            seg.error = str(exc)
            seg.state = "error"
            self.translation_failed.emit(seg.id, str(exc))
            self.segment_state.emit(seg.id, "error")
            if "API Key" not in str(exc):
                self.toast.emit(f"翻译失败：{exc}", "error")
        except Exception as exc:
            log.exception("翻译异常")
            with self._lock:
                self._cancel_events.pop(seg.id, None)
            seg.error = str(exc)
            seg.state = "error"
            self.translation_failed.emit(seg.id, f"翻译异常：{exc}")
            self.segment_state.emit(seg.id, "error")
        finally:
            with self._lock:
                self._cancel_events.pop(seg.id, None)
            self._translation_finished(seg.id)

    # ------------------------------------------------------------------ helpers
    def _source_label(self) -> str:
        s = self.config.settings.audio
        if s.source == "microphone":
            return "麦克风"
        if s.source == "tab":
            return "浏览器标签页"
        if s.system_device_name:
            return f"系统声音 · {s.system_device_name}"
        return "系统声音"

    def _set_status(self, state: str, message: str) -> None:
        self._stats["state"] = state
        self.status_changed.emit(state, message)

    def shutdown(self) -> None:
        self.stop()
        if self._stop_thread and self._stop_thread.is_alive():
            self._stop_thread.join(timeout=30.0)
        try:
            self._translator.close()
        except Exception:
            pass


def _clean_translation(text: str) -> str:
    value = text.strip()
    for prefix in ("译文：", "译文:", "翻译：", "翻译:"):
        if value.startswith(prefix):
            value = value[len(prefix) :].strip()
    return value
