"""后台下载 GGUF 本地翻译模型（带进度、取消）。"""

from __future__ import annotations

import os
import threading
import time
import urllib.request

from PySide6.QtCore import QObject, Signal

from .. import paths


class ModelDownloader(QObject):
    progress = Signal(int, int)  # 已下载字节, 总字节（未知时为 0）
    finished = Signal(str)  # 最终文件路径
    failed = Signal(str)

    def __init__(self, key: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.key = key
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="model-download", daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._cancel.set()

    def _run(self) -> None:
        info = paths.local_mt_info(self.key)
        target = paths.local_mt_expected_path(self.key)
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_suffix(target.suffix + ".part")
        expected = int(info.get("size") or 0)
        url = paths.local_mt_download_url(self.key)
        done = 0
        response = None
        try:
            if target.is_file() and paths.local_mt_file_ready(self.key, str(target)):
                self.finished.emit(str(target))
                return
            if target.exists():
                # 上次下载中断或文件损坏：删除后重下，避免把半文件当成品。
                target.unlink(missing_ok=True)
            if part.exists():
                part.unlink(missing_ok=True)
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "RoseSI/1.2",
                    "Accept": "application/octet-stream",
                },
            )
            response = urllib.request.urlopen(request, timeout=30)
            header = response.headers.get("Content-Length")
            total = int(header) if header and header.isdigit() else expected
            last_emit = 0.0
            with part.open("wb") as handle:
                while True:
                    if self._cancel.is_set():
                        raise RuntimeError("下载已取消")
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    done += len(chunk)
                    now = time.monotonic()
                    if now - last_emit > 0.2:
                        last_emit = now
                        self.progress.emit(done, total)
            if self._cancel.is_set():
                raise RuntimeError("下载已取消")
            if expected and part.stat().st_size < expected * 0.98:
                raise RuntimeError(
                    f"下载不完整（{part.stat().st_size / 1024 / 1024:.0f} MB），请重试"
                )
            os.replace(part, target)
            self.progress.emit(done, total or done)
            self.finished.emit(str(target))
        except Exception as exc:
            try:
                if part.exists():
                    part.unlink(missing_ok=True)
            except OSError:
                pass
            self.failed.emit(str(exc))
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
