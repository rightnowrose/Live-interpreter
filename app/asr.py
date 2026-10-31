"""本地 ASR：Silero VAD 流式切句 + faster-whisper 增量识别。"""

from __future__ import annotations

import gc
import logging
import os
import queue
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from .config import ASRSettings, whisper_language
from .models import new_id
from .paths import PARAKEET_MODEL, parakeet_ready, resolve_parakeet_dir, resolve_asr_model

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
FRAME_SAMPLES = 512  # 32 ms @ 16k

# Whisper 在静音/音乐上常见的幻觉输出
_ARTIFACTS = (
    "谢谢观看",
    "谢谢大家",
    "请不吝点赞",
    "订阅",
    "字幕由",
    "字幕提供",
    "thanks for watching",
    "thank you for watching",
    "subtitles by",
    "amara.org",
    "请开启字幕",
    "中文字幕",
)


def _clean_text(text: str) -> str:
    value = text.strip()
    if not value:
        return ""
    value = re.sub(r"\[(?:music|applause|laughter|silence|音乐|掌声|笑声|静音)\]", " ", value, flags=re.I)
    value = re.sub(r"[（(](?:music|applause|laughter|音乐|掌声|笑声)[）)]", " ", value, flags=re.I)
    value = value.replace("♪", " ").strip()
    low = value.lower()
    if len(value) <= 24 and any(marker in low for marker in _ARTIFACTS):
        return ""
    # 去掉同一句被反复生成的情况
    parts = re.split(r"(?<=[.!?。！？])\s*", value)
    if len(parts) >= 3 and len(set(parts)) <= max(1, len(parts) // 3):
        value = parts[0]
    return re.sub(r"\s+", " ", value).strip()


@dataclass
class ASRText:
    text: str
    language: str
    language_prob: float
    asr_ms: float
    avg_logprob: float | None = None
    no_speech_prob: float | None = None


class StreamingVAD:
    """Silero VAD v6 的流式封装（持久 h/c 状态）。"""

    def __init__(self, threshold: float) -> None:
        import onnxruntime as ort
        from faster_whisper.vad import get_assets_path

        options = ort.SessionOptions()
        options.inter_op_num_threads = 1
        options.intra_op_num_threads = 1
        options.log_severity_level = 4
        path = os.path.join(get_assets_path(), "silero_vad_v6.onnx")
        self._session = ort.InferenceSession(
            path, providers=["CPUExecutionProvider"], sess_options=options
        )
        self._h = np.zeros((1, 1, 128), dtype=np.float32)
        self._c = np.zeros((1, 1, 128), dtype=np.float32)
        self._ctx = np.zeros(64, dtype=np.float32)
        self.threshold = threshold

    def reset(self) -> None:
        self._h[:] = 0
        self._c[:] = 0
        self._ctx[:] = 0

    def prob(self, frame: np.ndarray) -> float:
        inp = np.concatenate([self._ctx, frame]).astype(np.float32)[None, :]
        out, self._h, self._c = self._session.run(
            None, {"input": inp, "h": self._h, "c": self._c}
        )
        self._ctx = frame[-64:].copy()
        return float(np.asarray(out).reshape(-1)[0])


class UtteranceSegmenter:
    """把连续音频切成句，并在说话过程中定期产出增量音频。"""

    def __init__(
        self,
        settings: ASRSettings,
        on_start: Callable[[str, float], None],
        on_partial: Callable[[str, np.ndarray, float, float], None],
        on_final: Callable[[str, np.ndarray, float, float, float], None],
        on_drop: Callable[[str], None],
        should_hold: Callable[[str], bool] | None = None,
    ) -> None:
        self.settings = settings
        self.on_start = on_start
        self.on_partial = on_partial
        self.on_final = on_final
        self.on_drop = on_drop
        self.should_hold = should_hold
        self.vad = StreamingVAD(settings.vad_threshold)
        self._pending = np.zeros(0, dtype=np.float32)
        self._pre_roll: list[np.ndarray] = []
        self._pre_roll_frames = max(1, int(settings.pre_roll_ms / 32))
        self._frames: list[np.ndarray] = []
        self._state = "idle"
        self._trigger = 0
        self._silence_run = 0
        self._last_partial_frames = 0
        self._seg_id = ""
        self._total_frames = 0
        self._start_frame = 0
        self._off_threshold = max(0.15, settings.vad_threshold - 0.2)

    def feed(self, audio: np.ndarray) -> None:
        if audio.size == 0:
            return
        self._pending = np.concatenate([self._pending, audio.astype(np.float32, copy=False)])
        while self._pending.size >= FRAME_SAMPLES:
            frame = self._pending[:FRAME_SAMPLES].copy()
            self._pending = self._pending[FRAME_SAMPLES:]
            self._process(frame)

    def flush(self) -> None:
        if self._state == "speech" and self._frames:
            self._finalize(force=True)

    def _process(self, frame: np.ndarray) -> None:
        prob = self.vad.prob(frame)
        self._total_frames += 1

        if self._state == "idle":
            self._pre_roll.append(frame)
            if len(self._pre_roll) > self._pre_roll_frames:
                self._pre_roll.pop(0)
            if prob >= self.settings.vad_threshold:
                self._trigger += 1
            else:
                self._trigger = 0
            if self._trigger >= 2:
                self._state = "speech"
                self._seg_id = new_id()
                self._frames = list(self._pre_roll)
                self._start_frame = self._total_frames - len(self._frames)
                self._silence_run = 0
                self._last_partial_frames = 0
                self._pre_roll.clear()
                self._trigger = 0
                self.on_start(self._seg_id, self._start_frame * FRAME_SAMPLES / SAMPLE_RATE)
            return

        self._frames.append(frame)
        if prob < self._off_threshold:
            self._silence_run += 1
        else:
            self._silence_run = 0

        duration_frames = len(self._frames)
        speech_frames = duration_frames - self._silence_run
        partial_every = max(1, int(self.settings.partial_interval_ms / 32))

        if (
            speech_frames >= int(self.settings.min_segment_ms / 32)
            and duration_frames - self._last_partial_frames >= partial_every
        ):
            self._last_partial_frames = duration_frames
            end_frame = min(duration_frames, speech_frames + 2)
            audio = np.concatenate(self._frames[:end_frame])
            self.on_partial(
                self._seg_id,
                audio,
                self._start_frame * FRAME_SAMPLES / SAMPLE_RATE,
                (self._start_frame + end_frame) * FRAME_SAMPLES / SAMPLE_RATE,
            )

        if self._silence_run * 32 >= self.settings.silence_ms:
            silence_ms = self._silence_run * 32
            hold = (
                silence_ms < max(self.settings.silence_ms, int(self.settings.silence_max_ms or 0))
                and self.should_hold is not None
                and self.should_hold(self._seg_id)
            )
            if not hold:
                self._finalize()
        elif duration_frames * 32 >= self.settings.max_segment_ms:
            self._finalize(force=True)

    def _finalize(self, force: bool = False) -> None:
        if not self._frames:
            self._reset()
            return
        keep = len(self._frames) - self._silence_run + 4
        keep = max(1, min(len(self._frames), keep))
        audio = np.concatenate(self._frames[:keep])
        start_s = self._start_frame * FRAME_SAMPLES / SAMPLE_RATE
        end_s = (self._start_frame + keep) * FRAME_SAMPLES / SAMPLE_RATE
        duration_ms = len(audio) / SAMPLE_RATE * 1000
        if duration_ms >= self.settings.min_segment_ms:
            self.on_final(self._seg_id, audio, start_s, end_s, duration_ms)
        else:
            self.on_drop(self._seg_id)
        self._reset()

    def _reset(self) -> None:
        self._state = "idle"
        self._frames = []
        self._silence_run = 0
        self._trigger = 0
        self._last_partial_frames = 0
        self._seg_id = ""
        self.vad.reset()


class ASREngine:
    def __init__(self, settings: ASRSettings) -> None:
        self.settings = settings
        self.model = None
        self.parakeet = None
        self.backend = "whisper"
        self.device = ""
        self.compute_type = ""
        self.resolved_path = ""
        self.load_ms = 0.0
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self.model is not None or self.parakeet is not None

    @property
    def supports_partials(self) -> bool:
        # Parakeet 每次都要跑完整 encoder，直播中只做最终片段更稳更省
        return self.backend != "parakeet"

    def load(self, progress: Callable[[str], None] | None = None) -> None:
        if self.loaded:
            return
        if self.settings.model == PARAKEET_MODEL:
            self._load_parakeet(progress)
            return
        from faster_whisper import WhisperModel

        path = self.settings.model_path or resolve_asr_model(self.settings.model)
        self.resolved_path = path
        if self.settings.model.startswith("kotoba-whisper") and not Path(path).is_dir():
            raise RuntimeError(
                "Kotoba 模型尚未下载到本地。请先把 model.bin/config.json 等文件放入 "
                f"{path}，或在设置中填写正确的模型目录。"
            )
        candidates: list[tuple[str, str]] = []
        requested_device = self.settings.device
        requested_compute = self.settings.compute_type

        if requested_device == "cpu":
            candidates = [("cpu", "int8" if requested_compute == "auto" else requested_compute)]
        elif requested_device == "cuda":
            candidates = [("cuda", "int8_float16" if requested_compute == "auto" else requested_compute)]
        else:
            candidates = [
                ("cuda", "int8_float16" if requested_compute == "auto" else requested_compute),
                ("cpu", "int8"),
            ]

        errors: list[str] = []
        for index, (device, compute) in enumerate(candidates):
            if progress:
                progress(f"加载 {os.path.basename(path)} · {device}/{compute}")
            try:
                t0 = time.perf_counter()
                model = WhisperModel(
                    path,
                    device=device,
                    compute_type=compute,
                    cpu_threads=max(1, min(8, (os.cpu_count() or 4) - 1)),
                    num_workers=1,
                )
                self.model = model
                self.backend = "whisper"
                self.device = device
                self.compute_type = compute
                self.load_ms = (time.perf_counter() - t0) * 1000
                log.info("ASR 已加载 device=%s compute=%s path=%s", device, compute, path)
                return
            except Exception as exc:
                errors.append(f"{device}/{compute}: {exc}")
                log.warning("ASR 加载失败 %s/%s: %s", device, compute, exc)
                if index == 0 and requested_device == "auto":
                    if progress:
                        progress("GPU 不可用，回退 CPU（可能无法实时）")
        raise RuntimeError("ASR 模型加载失败：\n" + "\n".join(errors))

    def _load_parakeet(self, progress: Callable[[str], None] | None = None) -> None:
        from .asr_parakeet import ParakeetRecognizer

        custom = Path(self.settings.model_path) if self.settings.model_path else None
        folder = custom if custom and custom.is_dir() else resolve_parakeet_dir()
        self.resolved_path = str(folder)
        if custom is None and not parakeet_ready():
            missing = "、".join(self._parakeet_missing())
            raise RuntimeError(
                "Parakeet 模型尚未下载完整。缺少："
                f"{missing}。请重新下载到 {folder}，或在设置中指定模型目录。"
            )
        if progress:
            progress("加载 Parakeet TDT 0.6B JA · ONNX")
        t0 = time.perf_counter()
        recognizer = ParakeetRecognizer(folder, device=self.settings.device)
        recognizer.load()
        if self.settings.warmup:
            if progress:
                progress("预热 Parakeet 推理")
            recognizer.warmup()
        self.parakeet = recognizer
        self.backend = "parakeet"
        self.device = "cuda" if "CUDAExecutionProvider" in recognizer.providers else "cpu"
        self.compute_type = "fp16"
        self.load_ms = (time.perf_counter() - t0) * 1000
        log.info(
            "Parakeet 已加载 device=%s providers=%s path=%s load=%.0fms",
            self.device,
            recognizer.providers,
            folder,
            self.load_ms,
        )

    def _parakeet_missing(self) -> list[str]:
        from .paths import parakeet_missing

        return parakeet_missing()

    def unload(self) -> None:
        with self._lock:
            self.model = None
            self.parakeet = None
            self.backend = "whisper"
            self.device = self.compute_type = ""
            gc.collect()

    def transcribe(
        self,
        audio: np.ndarray,
        beam_size: int,
        language: str | None,
        initial_prompt: str = "",
        is_partial: bool = False,
    ) -> ASRText:
        if self.parakeet is not None:
            with self._lock:
                text, elapsed, avg = self.parakeet.transcribe(
                    audio, language or "ja", is_partial
                )
            return ASRText(
                text=text,
                language="ja",
                language_prob=1.0,
                asr_ms=elapsed,
                avg_logprob=avg,
                no_speech_prob=None,
            )
        if self.model is None:
            raise RuntimeError("ASR 模型尚未加载")
        if audio.size < int(SAMPLE_RATE * 0.15):
            return ASRText("", language or "", 0.0, 0.0)
        audio = np.ascontiguousarray(audio, dtype=np.float32)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        if peak > 1.5:  # 兼容误传的 int16
            audio = audio / 32768.0
        t0 = time.perf_counter()
        with self._lock:
            segments, info = self.model.transcribe(
                audio,
                language=language,
                beam_size=beam_size,
                vad_filter=False,
                condition_on_previous_text=False,
                without_timestamps=True,
                word_timestamps=False,
                temperature=0.0,
                no_speech_threshold=0.75 if is_partial else 0.6,
                log_prob_threshold=-1.0,
                compression_ratio_threshold=2.4,
                initial_prompt=initial_prompt or None,
            )
            items = list(segments)
            text = " ".join(seg.text.strip() for seg in items).strip()
        elapsed = (time.perf_counter() - t0) * 1000
        text = _clean_text(text)
        weights = [max(1, len(seg.text.strip())) for seg in items]
        total_weight = max(1, sum(weights))
        avg_logprob = (
            sum(float(getattr(seg, "avg_logprob", 0.0) or 0.0) * weight for seg, weight in zip(items, weights))
            / total_weight
            if items
            else None
        )
        no_speech_values = [
            float(getattr(seg, "no_speech_prob", 0.0) or 0.0) for seg in items
        ]
        return ASRText(
            text=text,
            language=info.language or (language or ""),
            language_prob=float(info.language_probability or 0.0),
            asr_ms=elapsed,
            avg_logprob=avg_logprob,
            no_speech_prob=max(no_speech_values) if no_speech_values else None,
        )


class ASRWorker:
    """独立线程：消费 16 kHz 音频，产出增量/最终识别文本。"""

    def __init__(
        self,
        engine: ASREngine,
        settings: ASRSettings,
        on_start: Callable[[str, float], None],
        on_partial: Callable[[str, str, dict], None],
        on_final: Callable[[str, str, dict], None],
        on_drop: Callable[[str], None],
        on_error: Callable[[str], None],
        on_status: Callable[[str], None] | None = None,
    ) -> None:
        self.engine = engine
        self.settings = settings
        self.on_start = on_start
        self.on_partial = on_partial
        self.on_final = on_final
        self.on_drop = on_drop
        self.on_error = on_error
        self.on_status = on_status
        self._queue: queue.Queue[np.ndarray | None] = queue.Queue(maxsize=400)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._segmenter = UtteranceSegmenter(
            settings,
            on_start=self._handle_start,
            on_partial=self._handle_partial_audio,
            on_final=self._handle_final_audio,
            on_drop=on_drop,
            should_hold=self._should_hold_endpoint,
        )
        self._last_language = ""
        self._last_language_prob = 0.0
        self._dropped_blocks = 0
        self._final_lock = threading.Lock()
        self._pending_finals = 0
        # Parakeet 没有原生 partial；用滑动窗口做“草稿预览”。
        self._preview_executor: ThreadPoolExecutor | None = None
        self._preview_busy = threading.Event()
        self._preview_lock = threading.Lock()
        self._preview_generation = 0
        self._preview_seg = ""
        self._preview_prev = ""
        self._preview_text = ""

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._preview_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="asr-preview"
        )
        self._thread = threading.Thread(target=self._run, name="asr-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        executor = self._preview_executor
        self._preview_executor = None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        self._thread = None

    def feed(self, audio: np.ndarray) -> None:
        try:
            self._queue.put_nowait(audio)
        except queue.Full:
            self._dropped_blocks += 1
            if self._dropped_blocks % 50 == 1:
                log.warning("ASR 队列已满，丢弃音频块（%s）", self._dropped_blocks)

    # ------------------------------------------------------------------
    def _run(self) -> None:
        try:
            while True:
                try:
                    block = self._queue.get(timeout=0.2)
                except queue.Empty:
                    if self._stop.is_set():
                        break
                    continue
                if block is None:
                    break
                self._segmenter.feed(block)
            self._segmenter.flush()
        except Exception as exc:
            log.exception("ASR 线程异常")
            self.on_error(f"识别线程异常：{exc}")

    def _lang_for_partial(self) -> str | None:
        configured = whisper_language(self.settings.language)
        if configured:
            return configured
        if self._last_language and self._last_language_prob >= 0.65:
            return self._last_language
        return None

    def _handle_start(self, seg_id: str, start_s: float) -> None:
        with self._preview_lock:
            self._preview_generation += 1
            self._preview_seg = seg_id
            self._preview_prev = ""
            self._preview_text = ""
        self.on_start(seg_id, start_s)

    @staticmethod
    def _common_prefix(left: str, right: str) -> str:
        limit = min(len(left), len(right))
        index = 0
        while index < limit and left[index] == right[index]:
            index += 1
        return left[:index]

    def _stable_preview(self, text: str) -> str:
        """连续两次预览的公共前缀才算稳定，避免草稿反复跳动。"""
        with self._preview_lock:
            previous = self._preview_prev
            self._preview_prev = text
            if not previous:
                stable = text
            elif text.startswith(self._preview_text):
                stable = text
            else:
                common = self._common_prefix(previous, text)
                stable = common if len(common) >= 4 else self._preview_text
            if len(stable) > len(self._preview_text):
                self._preview_text = stable
            return self._preview_text

    def _should_hold_endpoint(self, seg_id: str) -> bool:
        """静音到时后，若预览文本还停在非句末形式，再等一小段。"""
        with self._preview_lock:
            if seg_id != self._preview_seg:
                return False
            text = self._preview_text.strip().rstrip("。！？!?、,， ")
        if len(text) < 4:
            return False
        final_forms = (
            "です",
            "ます",
            "ました",
            "ません",
            "でしょう",
            "ください",
            "ですね",
            "ますね",
            "ですよ",
            "ますよ",
            "かな",
            "かしら",
            "と思います",
            "とおもいます",
        )
        if text.endswith(final_forms):
            return False
        non_final = (
            "て",
            "で",
            "が",
            "を",
            "に",
            "は",
            "も",
            "と",
            "や",
            "から",
            "けど",
            "けれど",
            "ので",
            "し",
            "り",
            "って",
            "たら",
            "なら",
            "ながら",
            "つつ",
            "おり",
            "ため",
        )
        return text.endswith(non_final)

    def _preview_audio(
        self, generation: int, seg_id: str, audio: np.ndarray, start_s: float, end_s: float
    ) -> None:
        try:
            result = self.engine.transcribe(
                audio,
                beam_size=1,
                language=self._lang_for_partial(),
                is_partial=True,
            )
            if self._stop.is_set() or generation != self._preview_generation:
                return
            text = (result.text or "").strip()
            if not text or seg_id != self._preview_seg:
                return
            stable = self._stable_preview(text)
            if len(stable) < 4:
                return
            self.on_partial(
                seg_id,
                stable,
                {
                    "start": start_s,
                    "end": end_s,
                    "asr_ms": result.asr_ms,
                    "language": "ja",
                    "avg_logprob": result.avg_logprob,
                    "no_speech_prob": result.no_speech_prob,
                    "partial": True,
                    "preview": True,
                },
            )
        except Exception:
            log.debug("Parakeet 预览识别失败", exc_info=True)
        finally:
            self._preview_busy.clear()

    def _handle_partial_audio(
        self, seg_id: str, audio: np.ndarray, start_s: float, end_s: float
    ) -> None:
        if not self.engine.supports_partials:
            # Parakeet 的滑动窗口草稿：只上屏原文，不触发翻译。
            if self.engine.backend != "parakeet" or self._preview_busy.is_set():
                return
            executor = self._preview_executor
            if executor is None:
                return
            self._preview_busy.set()
            generation = self._preview_generation
            try:
                executor.submit(
                    self._preview_audio,
                    generation,
                    seg_id,
                    np.ascontiguousarray(audio, dtype=np.float32).copy(),
                    start_s,
                    end_s,
                )
            except RuntimeError:
                self._preview_busy.clear()
            return
        try:
            result = self.engine.transcribe(
                audio,
                beam_size=self.settings.partial_beam_size,
                language=self._lang_for_partial(),
                is_partial=True,
            )
            if result.language and result.language_prob >= 0.6:
                self._last_language = result.language
                self._last_language_prob = result.language_prob
            if result.text:
                with self._preview_lock:
                    if seg_id == self._preview_seg:
                        self._preview_text = result.text.strip()
                self.on_partial(
                    seg_id,
                    result.text,
                    {
                        "start": start_s,
                        "end": end_s,
                        "asr_ms": result.asr_ms,
                        "language": result.language,
                        "avg_logprob": result.avg_logprob,
                        "no_speech_prob": result.no_speech_prob,
                        "partial": True,
                    },
                )
        except Exception as exc:
            log.exception("增量识别失败")
            self.on_error(f"增量识别失败：{exc}")

    def _handle_final_audio(
        self, seg_id: str, audio: np.ndarray, start_s: float, end_s: float, duration_ms: float
    ) -> None:
        self._pending_finals += 1
        with self._preview_lock:
            self._preview_generation += 1
            preview_text = self._preview_text
        try:
            result = self.engine.transcribe(
                audio,
                beam_size=self.settings.beam_size,
                language=whisper_language(self.settings.language) or self._lang_for_partial(),
                initial_prompt=self.settings.initial_prompt,
                is_partial=False,
            )
            text = result.text or ""
            if not text and preview_text:
                # 最终解码偶发空白时，至少保留已稳定的草稿，避免整句消失。
                text = preview_text
            if not text:
                self.on_drop(seg_id)
                return
            if result.language and result.language_prob >= 0.6:
                self._last_language = result.language
                self._last_language_prob = result.language_prob
            self.on_final(
                seg_id,
                text,
                {
                    "start": start_s,
                    "end": end_s,
                    "duration_ms": duration_ms,
                    "asr_ms": result.asr_ms,
                    "language": result.language,
                    "language_prob": result.language_prob,
                    "avg_logprob": result.avg_logprob,
                    "no_speech_prob": result.no_speech_prob,
                },
            )
        except Exception as exc:
            log.exception("最终识别失败")
            self.on_error(f"最终识别失败：{exc}")
            self.on_drop(seg_id)
        finally:
            self._pending_finals -= 1
            with self._preview_lock:
                self._preview_seg = ""
                self._preview_prev = ""
                self._preview_text = ""
