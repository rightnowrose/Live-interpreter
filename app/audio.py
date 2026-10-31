"""音频采集：系统环回（WASAPI loopback）与麦克风。

所有采集统一输出 16 kHz、单声道、float32 的音频块。
"""

from __future__ import annotations

import ctypes
import importlib.util
import logging
import sys
import threading
import time
import warnings
from dataclasses import dataclass
from typing import Callable

import numpy as np
import soxr

from .config import AudioSettings

log = logging.getLogger(__name__)

TARGET_RATE = 16000
CAPTURE_RATE = 48000

AudioCallback = Callable[[np.ndarray], None]
LevelCallback = Callable[[float], None]
ErrorCallback = Callable[[str], None]
StatusCallback = Callable[[str], None]

# 延迟导入：soundcard 在 import 时会 CoInitializeEx(MULTITHREADED)，
# 若早于 QApplication 执行会让 Qt 的 OleInitialize(STA) 失败。
sc = None
SoundcardRuntimeWarning = Warning  # type: ignore


def _load_sc():
    global sc, SoundcardRuntimeWarning
    if sc is not None:
        return sc
    import soundcard as _sc
    from soundcard import SoundcardRuntimeWarning as _warning

    warnings.filterwarnings("ignore", category=_warning)
    sc = _sc
    SoundcardRuntimeWarning = _warning
    return sc


def ensure_com() -> None:
    """在采集/枚举线程中初始化 COM(MTA)；失败（已是 STA）可忽略。"""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.ole32.CoInitializeEx(None, 0x0)
    except Exception:
        pass


@dataclass(frozen=True)
class AudioDevice:
    id: str
    name: str
    is_default: bool
    kind: str


def available() -> bool:
    return importlib.util.find_spec("soundcard") is not None


def list_speakers() -> list[AudioDevice]:
    lib = _load_sc()
    try:
        default = lib.default_speaker()
        default_id = default.id if default else ""
        items = [
            AudioDevice(spk.id, spk.name, spk.id == default_id, "speaker")
            for spk in lib.all_speakers()
        ]
        items.sort(key=lambda d: (not d.is_default, d.name.lower()))
        return items
    except Exception:
        log.exception("枚举输出设备失败")
        return []


def list_microphones() -> list[AudioDevice]:
    lib = _load_sc()
    try:
        default = lib.default_microphone()
        default_id = default.id if default else ""
        items = [
            AudioDevice(mic.id, mic.name, mic.id == default_id, "microphone")
            for mic in lib.all_microphones(include_loopback=False)
        ]
        items.sort(key=lambda d: (not d.is_default, d.name.lower()))
        return items
    except Exception:
        log.exception("枚举麦克风失败")
        return []


class _Resampler:
    def __init__(self, gain: float = 1.0) -> None:
        self._stream = soxr.ResampleStream(
            CAPTURE_RATE, TARGET_RATE, 1, dtype="float32", quality="HQ"
        )
        self._gain = max(0.1, min(4.0, float(gain)))

    def feed(self, mono: np.ndarray, last: bool = False) -> np.ndarray:
        if mono.size == 0:
            if not last:
                return np.zeros(0, dtype=np.float32)
            out = self._stream.resample_chunk(np.zeros(0, dtype=np.float32), last=True)
        else:
            out = self._stream.resample_chunk(mono.astype(np.float32), last=last)
        if self._gain != 1.0:
            out = out * self._gain
        return np.clip(out, -1.0, 1.0).astype(np.float32, copy=False)


class CaptureBase:
    def __init__(
        self,
        on_audio: AudioCallback,
        on_level: LevelCallback | None = None,
        on_error: ErrorCallback | None = None,
        on_status: StatusCallback | None = None,
        gain: float = 1.0,
    ) -> None:
        self.on_audio = on_audio
        self.on_level = on_level
        self.on_error = on_error
        self.on_status = on_status
        self.gain = gain
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._resampler = _Resampler(gain)
        self._last_level = 0.0
        self._last_level_at = 0.0

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._resampler = _Resampler(self.gain)
        self._thread = threading.Thread(
            target=self._run, name=f"audio-{type(self).__name__}", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.5)
        self._thread = None

    def _run(self) -> None:  # pragma: no cover - 子类实现
        raise NotImplementedError

    def _emit(self, mono: np.ndarray) -> None:
        if mono.size == 0:
            return
        resampled = self._resampler.feed(mono)
        if resampled.size:
            try:
                self.on_audio(resampled)
            except Exception:
                log.exception("音频回调异常")
            self._emit_level(mono)

    def _emit_level(self, mono: np.ndarray) -> None:
        if self.on_level is None:
            return
        now = time.monotonic()
        if now - self._last_level_at < 0.05:
            return
        self._last_level_at = now
        rms = float(np.sqrt(np.mean(np.square(mono, dtype=np.float64)))) if mono.size else 0.0
        # 近似 dBFS -> 0..1 的显示值
        level = max(0.0, min(1.0, (20 * np.log10(max(rms, 1e-7)) + 60) / 60))
        self._last_level = level
        try:
            self.on_level(level)
        except Exception:
            pass

    def _error(self, message: str) -> None:
        log.error("%s: %s", type(self).__name__, message)
        if self.on_error:
            try:
                self.on_error(message)
            except Exception:
                pass


class SystemLoopbackCapture(CaptureBase):
    """抓取某个输出设备的环回音频——浏览器、播放器、会议软件都在这里。"""

    def __init__(
        self,
        settings: AudioSettings,
        on_audio: AudioCallback,
        on_level: LevelCallback | None = None,
        on_error: ErrorCallback | None = None,
        on_status: StatusCallback | None = None,
    ) -> None:
        super().__init__(on_audio, on_level, on_error, on_status, gain=settings.gain)
        self.device_id = settings.system_device or ""

    def _resolve(self):
        lib = _load_sc()
        speaker = lib.get_speaker(self.device_id) if self.device_id else lib.default_speaker()
        if speaker is None:
            raise RuntimeError("没有可用的输出设备")
        loopback = lib.get_microphone(speaker.id, include_loopback=True)
        if loopback is None:
            raise RuntimeError(f"输出设备“{speaker.name}”不支持环回采集")
        return speaker, loopback

    def _run(self) -> None:
        try:
            _load_sc()
            ensure_com()
            speaker, loopback = self._resolve()
            if self.on_status:
                self.on_status(f"环回：{speaker.name}")
            with loopback.recorder(samplerate=CAPTURE_RATE, channels=2, blocksize=960) as rec:
                while not self._stop.is_set():
                    data = rec.record(numframes=960)
                    if data is None or len(data) == 0:
                        continue
                    if data.ndim > 1:
                        mono = data.mean(axis=1)
                    else:
                        mono = data
                    self._emit(np.asarray(mono, dtype=np.float32))
        except Exception as exc:
            self._error(f"系统声音采集失败：{exc}")
        finally:
            tail = self._resampler.feed(np.zeros(0, dtype=np.float32), last=True)
            if tail.size:
                try:
                    self.on_audio(tail)
                except Exception:
                    pass


class MicrophoneCapture(CaptureBase):
    def __init__(
        self,
        settings: AudioSettings,
        on_audio: AudioCallback,
        on_level: LevelCallback | None = None,
        on_error: ErrorCallback | None = None,
        on_status: StatusCallback | None = None,
    ) -> None:
        super().__init__(on_audio, on_level, on_error, on_status, gain=settings.gain)
        self.device_id = settings.mic_id or ""

    def _resolve(self):
        lib = _load_sc()
        mic = lib.get_microphone(self.device_id) if self.device_id else lib.default_microphone()
        if mic is None:
            raise RuntimeError("没有可用的麦克风")
        return mic

    def _run(self) -> None:
        try:
            _load_sc()
            ensure_com()
            mic = self._resolve()
            if self.on_status:
                self.on_status(f"麦克风：{mic.name}")
            with mic.recorder(samplerate=CAPTURE_RATE, channels=1, blocksize=960) as rec:
                while not self._stop.is_set():
                    data = rec.record(numframes=960)
                    if data is None or len(data) == 0:
                        continue
                    mono = data.mean(axis=1) if data.ndim > 1 else data
                    self._emit(np.asarray(mono, dtype=np.float32))
        except Exception as exc:
            self._error(f"麦克风采集失败：{exc}")


def create_capture(
    settings: AudioSettings,
    on_audio: AudioCallback,
    on_level: LevelCallback | None = None,
    on_error: ErrorCallback | None = None,
    on_status: StatusCallback | None = None,
) -> CaptureBase:
    if settings.source == "microphone":
        return MicrophoneCapture(settings, on_audio, on_level, on_error, on_status)
    if settings.source == "tab":
        from .tab_capture import TabCapture

        return TabCapture(settings, on_audio, on_level, on_error, on_status)
    return SystemLoopbackCapture(settings, on_audio, on_level, on_error, on_status)
