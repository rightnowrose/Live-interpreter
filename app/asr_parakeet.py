"""NVIDIA Parakeet TDT 0.6B JA（ONNX）识别与直播断句。

Parakeet 本身是长音频识别模型，不做直播级断句；这里用 VAD 片段 +
日语标点/语气词/连接词规则做二次断句，保证字幕不会被一段长句拖住。
"""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)


def _add_cuda_dll_dirs() -> None:
    """给 onnxruntime-gpu 找到 cuDNN/CUDA 运行时（Windows）。"""
    from . import paths

    candidates: list[Path] = [
        paths.bundle_root() / "cudnn",
        paths.data_dir() / "cudnn",
    ]
    cuda_path = os.environ.get("CUDA_PATH", "")
    if cuda_path:
        candidates.append(Path(cuda_path) / "bin")
    try:
        import ctranslate2

        candidates.append(Path(ctranslate2.__file__).resolve().parent)
    except Exception:
        pass
    try:
        import site

        for base in site.getsitepackages():
            candidates.append(Path(base) / "nvidia" / "cudnn" / "bin")
    except Exception:
        pass
    for candidate in candidates:
        if candidate.is_dir():
            try:
                os.add_dll_directory(str(candidate))
            except (OSError, AttributeError):
                pass
    existing = [str(p) for p in candidates if p.is_dir()]
    if existing:
        os.environ["PATH"] = ";".join(existing + [os.environ.get("PATH", "")])

SAMPLE_RATE = 16000
BLANK_ID = 3072
VOCAB_SIZE = 3073
DURATIONS = (0, 1, 2, 3, 4)
SUBSAMPLING = 8
FRAME_SECONDS = SUBSAMPLING * 0.01
MAX_TOKENS_PER_STEP = 10

# 不切断句子的连接成分：这些词前面通常是同一句的继续
_CONTINUATIONS = (
    "が",
    "けど",
    "けれど",
    "から",
    "ので",
    "のに",
    "し",
    "て",
    "で",
    "と",
    "に",
    "を",
    "は",
    "も",
    "へ",
)
# 适合做新句开头的词
_SENTENCE_STARTERS = (
    "でも",
    "しかし",
    "だから",
    "それで",
    "そして",
    "また",
    "ちなみに",
    "ところで",
    "では",
    "じゃあ",
    "ということで",
    "あと",
    "次に",
    "まず",
    "一方",
    "つまり",
    "要するに",
)
# 句尾常见形式（仅在整个片段末尾补句号，避免“思いますが”被切）
_SENTENCE_END = re.compile(
    r"(?:です|ます|でした|ました|ください|でしょう|ましょう|ですね|ますね|ですよ|ますよ|"
    r"と思います|んです|んだ|からね|よね|だね|だよ|かな|かも|みたい|そう|って)$"
)
_PUNCT = "。！？!?"


def _clean(text: str) -> str:
    text = text.replace("\u2581", " ")
    text = re.sub(r"\s+", " ", text).strip()
    # SentencePiece 对日语一般无空格；中英混排保留单词间空格
    return text


def _split_long(text: str, max_chars: int) -> list[str]:
    """在连接词/语气词附近切分过长文本，尽量不切在助词后。"""
    if len(text) <= max_chars:
        return [text]
    out: list[str] = []
    rest = text
    while len(rest) > max_chars:
        window = rest[:max_chars]
        cut = -1
        # 只在顿号/逗号后切；连接词断句由前面的句尾规则处理
        for mark in ("、", "，", ","):
            index = window.rfind(mark)
            if index >= 12:
                cut = max(cut, index + 1)
        # 找不到自然断点时保留剩余整段，也不在词中间硬切
        if cut < 12:
            out.append(rest)
            return out
        out.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    if rest:
        out.append(rest)
    return out


def segment_japanese(text: str, max_chars: int = 42, end_punct: bool = True) -> str:
    """把 Parakeet 的长串输出整理成直播可读的短句。

    Parakeet 会在停顿处输出句号，但位置并不可靠（例如「中心。に」「し。て」）。
    因此先去掉模型自带句末标点，只在句尾形式后接新句开头词时补句号；过长时
    再按连接词/顿号切开。只改文本层，不删词，不改音频/VAD 切点。
    """
    text = _clean(text)
    if not text:
        return ""
    # 去掉模型不可靠的句末标点，保留顿号；不改变词序
    text = re.sub(r"[。！？!?]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    # 句尾形式 + 新句开头词：这是最可靠的断句点
    for starter in _SENTENCE_STARTERS:
        text = re.sub(
            rf"(?<=[すたただねよ]){re.escape(starter)}",
            f"。{starter}",
            text,
        )
    sentences: list[str] = []
    for part in re.split(r"[。]+", text):
        for piece in _split_long(part.strip(), max_chars):
            if piece:
                sentences.append(piece)
    body = "".join(sentences)
    if not end_punct:
        return body
    return "".join(
        (piece.rstrip("、，,") or piece)
        if (piece.rstrip("、，,") or piece).endswith(tuple(_PUNCT))
        else (piece.rstrip("、，,") or piece) + "。"
        for piece in sentences
    )


class ParakeetRecognizer:
    """Parakeet TDT ONNX 贪心解码器（不依赖 onnx-asr 的 Python 3.11 包）。"""

    def __init__(self, model_dir: str | Path, device: str = "auto") -> None:
        self.model_dir = Path(model_dir)
        self.device = device
        self.sessions: dict[str, object] = {}
        self.providers: list[str] = []
        self.vocab: dict[int, str] = {}
        self.load_ms = 0.0

    @property
    def ready(self) -> bool:
        return bool(self.sessions)

    def _providers(self) -> list[str]:
        import onnxruntime as ort

        available = set(ort.get_available_providers())
        if self.device != "cpu" and "CUDAExecutionProvider" in available:
            return ["CUDAExecutionProvider", "CPUExecutionProvider"]
        return ["CPUExecutionProvider"]

    def _session(self, name: str, filename: str) -> object:
        import onnxruntime as ort

        path = self.model_dir / filename
        if not path.exists():
            raise RuntimeError(f"Parakeet 模型文件缺失：{path}")
        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        options.intra_op_num_threads = max(1, min(4, (os.cpu_count() or 4) - 1))
        options.log_severity_level = 2
        providers = self._providers()
        try:
            session = ort.InferenceSession(str(path), sess_options=options, providers=providers)
        except Exception as exc:
            if providers and providers[0] != "CPUExecutionProvider":
                log.warning("Parakeet %s CUDA 加载失败，回退 CPU：%s", filename, exc)
                providers = ["CPUExecutionProvider"]
                session = ort.InferenceSession(str(path), sess_options=options, providers=providers)
            else:
                raise
        self.sessions[name] = session
        self.providers = list(session.get_providers())
        return session

    def load(self) -> None:
        _add_cuda_dll_dirs()
        t0 = time.perf_counter()
        self._session("pre", "nemo80.onnx")
        self._session("encoder", "encoder-model.fp16.onnx")
        self._session("decoder", "decoder_joint-model.fp16.onnx")
        with (self.model_dir / "vocab.txt").open("rt", encoding="utf-8") as handle:
            for line in handle:
                line = line.rstrip("\n")
                if not line:
                    continue
                token, _, idx = line.rpartition(" ")
                if not token:
                    token, idx = idx, ""
                try:
                    self.vocab[int(idx)] = _clean(token)
                except ValueError:
                    continue
        if not self.vocab:
            raise RuntimeError("Parakeet vocab.txt 为空或格式不正确")
        self.load_ms = (time.perf_counter() - t0) * 1000
        log.info(
            "Parakeet 已加载 device=%s providers=%s vocab=%s path=%s",
            self.device,
            self.providers,
            len(self.vocab),
            self.model_dir,
        )

    def _features(self, audio: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        pre = self.sessions["pre"]
        wave = np.ascontiguousarray(audio, dtype=np.float32)[None, :]
        lens = np.asarray([audio.size], dtype=np.int64)
        features, feature_lens = pre.run(
            ["features", "features_lens"],
            {"waveforms": wave, "waveforms_lens": lens},
        )
        return features.astype(np.float32), feature_lens.astype(np.int64)

    def _decode(self, frames: np.ndarray) -> tuple[list[int], float | None, list[int]]:
        decoder = self.sessions["decoder"]
        # encoder output: [B,1024,T] -> [T,1024]
        frames = frames[0].transpose(1, 0)
        state1 = np.zeros((2, 1, 640), dtype=np.float32)
        state2 = np.zeros((2, 1, 640), dtype=np.float32)
        tokens: list[int] = []
        positions: list[int] = []
        logprobs: list[float] = []
        t = 0
        emitted = 0
        total = frames.shape[0]
        while t < total:
            frame = np.ascontiguousarray(frames[t][None, :, None], dtype=np.float32)
            prev = tokens[-1] if tokens else BLANK_ID
            outputs, out1, out2 = decoder.run(
                ["outputs", "output_states_1", "output_states_2"],
                {
                    "encoder_outputs": frame,
                    "targets": np.asarray([[prev]], dtype=np.int32),
                    "target_length": np.asarray([1], dtype=np.int32),
                    "input_states_1": state1,
                    "input_states_2": state2,
                },
            )
            logits = np.asarray(outputs).reshape(-1)
            token = int(np.argmax(logits[:VOCAB_SIZE]))
            duration = DURATIONS[int(np.argmax(logits[VOCAB_SIZE : VOCAB_SIZE + len(DURATIONS)]))]
            if token != BLANK_ID:
                state1, state2 = out1, out2
                tokens.append(token)
                positions.append(t)
                emitted += 1
                # 只对实际输出的 token 计算置信度，避免把 blank 计入
                probs = logits[:VOCAB_SIZE]
                probs = probs - probs.max()
                logprobs.append(float(probs[token] - np.log(np.exp(probs).sum())))
            if duration > 0:
                t += duration
                emitted = 0
            elif token == BLANK_ID or emitted >= MAX_TOKENS_PER_STEP:
                t += 1
                emitted = 0
        avg = float(np.mean(logprobs)) if logprobs else None
        return tokens, avg, positions

    def warmup(self) -> None:
        """预跑一次 8s 形状，建立 CUDA 卷积/图缓存，避免第一句慢 1–2 秒。"""
        if not self.sessions:
            self.load()
        sec = 8.0
        t = np.arange(int(SAMPLE_RATE * sec), dtype=np.float32) / SAMPLE_RATE
        tone = (np.sin(2 * np.pi * 220 * t) * 0.001).astype(np.float32)
        try:
            self.transcribe(tone, "ja", False)
        except Exception:
            log.debug("Parakeet warmup 失败", exc_info=True)

    def transcribe(self, audio: np.ndarray, language: str = "ja", is_partial: bool = False) -> tuple[str, float, float | None]:
        if not self.sessions:
            self.load()
        t0 = time.perf_counter()
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        if audio.size < int(SAMPLE_RATE * 0.15):
            return "", 0.0, None
        peak = float(np.max(np.abs(audio)))
        if peak < 1e-4:
            return "", 0.0, None
        # 不要用静音把短片段补到 8 秒：TDT 会在长静音上退化成全 blank，
        # 实测 0.6–3.8 秒的有效短句补零后会整句丢失。按真实长度送入编码器，
        # 8 秒预热仍然保留，用于建立长片段的 CUDA 卷积缓存。
        features, feature_lens = self._features(audio)
        actual_features = min(int(feature_lens[0]), features.shape[-1])
        encoder = self.sessions["encoder"]
        encoded, encoded_lens = encoder.run(
            ["outputs", "encoded_lengths"],
            {"audio_signal": features, "length": np.asarray([actual_features], dtype=np.int64)},
        )
        encoded = np.asarray(encoded, dtype=np.float32)
        if encoded.shape[1] != 1024 and encoded.shape[2] == 1024:
            encoded = encoded.transpose(0, 2, 1)
        valid_frames = min(int(encoded_lens[0]), encoded.shape[2])
        encoded = encoded[:, :, :valid_frames]
        tokens, avg, positions = self._decode(encoded)
        # 用 TDT 的 token 位置识别停顿：同一段 VAD 里的停顿也应落成句号，
        # 而不是把整段 8 秒压成一条没有标点的长句。
        groups: list[list[int]] = []
        gaps: list[int] = []
        current: list[int] = []
        last_pos = positions[0] if positions else 0
        for token, pos in zip(tokens, positions):
            gap = pos - last_pos
            if current and gap >= 12:  # 约 12×80ms ≈ 0.96s
                groups.append(current)
                gaps.append(gap)
                current = []
            current.append(token)
            last_pos = pos
        if current:
            groups.append(current)
        if len(groups) <= 1:
            text = "".join(self.vocab.get(token, "") for token in tokens)
            text = segment_japanese(text)
        else:
            text = ""
            for index, group in enumerate(groups):
                raw = "".join(self.vocab.get(token, "") for token in group)
                piece = segment_japanese(raw, end_punct=False)
                if not piece:
                    continue
                if text:
                    text += "。" if gaps[index - 1] >= 24 else "、"
                text += piece
            text = text.strip()
            if text and not text.endswith(tuple(_PUNCT)):
                text += "。"
        return text, (time.perf_counter() - t0) * 1000, avg
