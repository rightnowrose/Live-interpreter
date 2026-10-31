"""Lite 版首次运行时下载 Parakeet ONNX 模型（带进度、取消）。"""

from __future__ import annotations

import os
import threading
import time
import urllib.request
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .. import paths


class ParakeetDownloader(QObject):
    progress = Signal(int, int)  # 已下载字节, 总字节
    finished = Signal(str)  # 模型目录
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name="parakeet-download", daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._cancel.set()

    def _run(self) -> None:
        folder = paths.parakeet_dir()
        folder.mkdir(parents=True, exist_ok=True)
        total_expected = sum(paths.PARAKEET_FILES.values())
        done_before = 0
        current_part: Path | None = None
        try:
            for name, expected in paths.PARAKEET_FILES.items():
                target = folder / name
                if target.is_file() and target.stat().st_size >= int(expected * paths.PARAKEET_MIN_BYTES):
                    done_before += target.stat().st_size
                    self.progress.emit(done_before, total_expected)
                    continue
                current_part = target.with_suffix(target.suffix + ".part")
                if target.exists():
                    target.unlink(missing_ok=True)
                if current_part.exists():
                    current_part.unlink(missing_ok=True)

                request = urllib.request.Request(
                    paths.parakeet_download_url(name),
                    headers={
                        "User-Agent": "RoseSI/1.2 Lite",
                        "Accept": "application/octet-stream",
                    },
                )
                with urllib.request.urlopen(request, timeout=60) as response:
                    header = response.headers.get("Content-Length")
                    total = int(header) if header and header.isdigit() else expected
                    done = 0
                    last_emit = 0.0
                    with current_part.open("wb") as handle:
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
                                self.progress.emit(done_before + done, total_expected)
                if self._cancel.is_set():
                    raise RuntimeError("下载已取消")
                if current_part.stat().st_size < int(expected * paths.PARAKEET_MIN_BYTES):
                    raise RuntimeError(f"{name} 下载不完整，请重试")
                os.replace(current_part, target)
                done_before += target.stat().st_size
                self.progress.emit(done_before, total_expected)
                current_part = None

            missing = paths.parakeet_missing()
            if missing:
                raise RuntimeError("模型文件不完整：" + ", ".join(missing))
            self.finished.emit(str(folder))
        except Exception as exc:
            if current_part is not None:
                try:
                    current_part.unlink(missing_ok=True)
                except OSError:
                    pass
            self.failed.emit(str(exc))
