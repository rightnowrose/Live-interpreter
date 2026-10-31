"""浏览器标签页音频接收（WebSocket，配合 extension/ 下的 Edge/Chrome 扩展）。"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Callable

import numpy as np

from .config import AudioSettings

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000


class TabCapture:
    """替代 CaptureBase 的标签页采集：扩展推送 16 kHz 单声道 float32。"""

    def __init__(
        self,
        settings: AudioSettings,
        on_audio: Callable[[np.ndarray], None],
        on_level: Callable[[float], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        on_status: Callable[[str], None] | None = None,
    ) -> None:
        self.settings = settings
        self.on_audio = on_audio
        self.on_level = on_level
        self.on_error = on_error
        self.on_status = on_status
        self.port = int(settings.ws_port or 17866)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._server = None
        self._client = None
        self._last_level = 0.0
        self._last_level_at = 0.0
        self._title = ""

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="tab-capture", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        server = self._server
        if server is not None:
            try:
                server.shutdown()
            except Exception:
                pass
        client = self._client
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._thread = None
        self._server = None

    def _run(self) -> None:
        try:
            from websockets.sync.server import serve

            with serve(
                self._handler,
                "127.0.0.1",
                self.port,
                max_size=2 * 1024 * 1024,
                compression=None,
                open_timeout=10,
            ) as server:
                self._server = server
                log.info("标签页音频服务已监听 127.0.0.1:%s", self.port)
                if self.on_status:
                    self.on_status(f"等待浏览器扩展连接（端口 {self.port}）…")
                server.serve_forever()
        except OSError as exc:
            self._error(f"无法监听端口 {self.port}：{exc}")
        except Exception as exc:
            if not self._stop.is_set():
                self._error(f"标签页音频服务异常：{exc}")
        finally:
            self._server = None
            self._client = None

    def _handler(self, connection) -> None:
        self._client = connection
        self._title = ""
        log.info("浏览器扩展已连接：%s", getattr(connection, "remote_address", "?"))
        if self.on_status:
            self.on_status("浏览器标签页已连接")
        try:
            for message in connection:
                if isinstance(message, bytes):
                    self._on_pcm(message)
                else:
                    try:
                        payload = json.loads(message)
                    except json.JSONDecodeError:
                        continue
                    if payload.get("type") == "hello":
                        self._title = str(payload.get("title") or "")
                        if self.on_status:
                            self.on_status(
                                f"标签页：{self._title}" if self._title else "浏览器标签页已连接"
                            )
        except Exception:
            if not self._stop.is_set():
                log.debug("标签页连接断开", exc_info=True)
        finally:
            self._client = None
            log.info("浏览器扩展已断开")
            if not self._stop.is_set() and self.on_status:
                self.on_status("等待浏览器扩展连接…")

    def _on_pcm(self, payload: bytes) -> None:
        if len(payload) < 4 or len(payload) % 4:
            return
        audio = np.frombuffer(payload, dtype="<f4").astype(np.float32, copy=True)
        if audio.size == 0:
            return
        audio = np.clip(audio, -1.0, 1.0)
        try:
            self.on_audio(audio)
        except Exception:
            log.exception("标签页音频回调异常")
        if self.on_level is not None:
            now = time.monotonic()
            if now - self._last_level_at >= 0.05:
                self._last_level_at = now
                rms = float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))
                level = max(0.0, min(1.0, (20 * np.log10(max(rms, 1e-7)) + 60) / 60))
                try:
                    self.on_level(level)
                except Exception:
                    pass

    def _error(self, message: str) -> None:
        log.error("%s", message)
        if self.on_error:
            try:
                self.on_error(message)
            except Exception:
                pass
