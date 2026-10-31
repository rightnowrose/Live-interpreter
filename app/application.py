"""应用装配与生命周期。"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import QLockFile
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from . import APP_NAME, __version__, paths
from .config import ConfigStore
from .db import Database
from .pipeline import Pipeline
from .ui.hotkeys import HotkeyManager
from .ui.kana import KanaWindow
from .ui.overlay import OverlayWindow
from .ui.theme import app_icon, apply_theme
from .ui.tray import TrayIcon
from .ui.workbench import WorkbenchWindow

log = logging.getLogger(__name__)


class InterpreterApp:
    def __init__(self, app: QApplication) -> None:
        self.app = app
        self._quitting = False
        self.lock = QLockFile(str(paths.data_dir() / "instance.lock"))
        self.lock.setStaleLockTime(30000)
        if not self.lock.tryLock(120):
            QMessageBox.information(
                None,
                "RoseSI",
                "程序已经在运行。\n请查看桌面字幕窗或系统托盘。",
            )
            raise SystemExit(0)

        self.config = ConfigStore()
        # 鼠标穿透不跨启动恢复，避免用户找不到窗口
        if self.config.settings.overlay.click_through:
            self.config.settings.overlay.click_through = False
            self.config.save()
        self.db = Database()
        self.pipeline = Pipeline(self.config, self.db)
        self.overlay = OverlayWindow(self.config)
        self.workbench = WorkbenchWindow(self.pipeline, self.db, self.config)
        self.tray = TrayIcon(self.app)
        self.hotkeys = HotkeyManager(self.app)
        self._kana: KanaWindow | None = None

        self._wire_pipeline()
        self._wire_overlay()
        self._wire_workbench()
        self._wire_tray()
        self._wire_hotkeys()
        self._register_hotkeys()

        self.tray.show()
        self.overlay.show()
        self.overlay.raise_()
        if self.config.settings.ui.first_run:
            self.workbench.show_page("settings")
            self.workbench.show()
            self.workbench.raise_()
            self.workbench.activateWindow()
        log.info("RoseSI %s 已启动", __version__)

    # ------------------------------------------------------------------ 装配
    def _wire_pipeline(self) -> None:
        p = self.pipeline
        p.status_changed.connect(self.overlay.set_status)
        p.status_changed.connect(lambda state, msg: self.tray.set_state(state))
        p.segment_started.connect(self.overlay.add_segment)
        p.source_partial.connect(
            lambda seg_id, text: self.overlay.set_source(seg_id, text, partial=True)
        )
        p.source_final.connect(
            lambda seg_id, text, meta: self.overlay.set_source(seg_id, text, partial=False)
        )
        p.translation_delta.connect(
            lambda seg_id, text: self.overlay.set_translation(seg_id, text, state="output")
        )
        p.translation_done.connect(
            lambda seg_id, text, meta: self.overlay.set_translation(
                seg_id,
                text,
                state="done",
                via_tm=bool(meta.get("via_tm")),
                terms=list(meta.get("terms") or []),
            )
        )
        p.translation_failed.connect(
            lambda seg_id, msg: self.overlay.set_translation(seg_id, "", error=msg)
        )
        p.segment_state.connect(self._on_segment_state)
        p.segment_dropped.connect(self.overlay.remove_segment)
        p.level_changed.connect(self.overlay.set_level)
        p.stats_changed.connect(self.overlay.set_stats)
        p.session_started.connect(self._on_session_started)
        p.session_finished.connect(self._on_session_finished)
        p.toast.connect(self._on_toast)
        p.error.connect(lambda msg: self.overlay.flash(msg, "error"))

    def _wire_overlay(self) -> None:
        self.overlay.toggle_requested.connect(self.toggle_session)
        self.overlay.workbench_requested.connect(self.show_workbench)
        self.overlay.kana_requested.connect(self.show_kana)
        self.overlay.settings_requested.connect(self.workbench.open_settings)
        self.overlay.mode_changed.connect(lambda _: self._sync_settings())
        self.overlay.click_through_changed.connect(self._on_click_through)
        self.overlay.always_on_top_changed.connect(lambda _: self._sync_settings())
        self.overlay.geometry_changed.connect(lambda *_: self._sync_settings())
        self.overlay.hidden.connect(self._on_overlay_hidden)
        self.overlay.quit_requested.connect(self.quit)
        self.overlay.font_size_changed.connect(lambda _: self._sync_settings())
        self.overlay.opacity_changed.connect(lambda _: self._sync_settings())

    def _wire_workbench(self) -> None:
        self.workbench.show_overlay_requested.connect(self.show_overlay)
        self.workbench.kana_requested.connect(self.show_kana)
        self.workbench.settings_applied.connect(self._apply_settings)
        self.workbench.hotkeys_changed.connect(self._register_hotkeys)
        self.workbench.quit_requested.connect(self.quit)

    def _wire_tray(self) -> None:
        self.tray.toggle_overlay_requested.connect(self.toggle_overlay)
        self.tray.workbench_requested.connect(self.show_workbench)
        self.tray.kana_requested.connect(self.show_kana)
        self.tray.toggle_session_requested.connect(self.toggle_session)
        self.tray.click_through_toggled.connect(self._set_click_through)
        self.tray.quit_requested.connect(self.quit)
        self.tray.set_state("idle")
        self.tray.set_click_through(False)

    def _wire_hotkeys(self) -> None:
        self.hotkeys.triggered.connect(self._on_hotkey)
        self.hotkeys.failed.connect(
            lambda action, sequence: self._notify(
                f"热键 {sequence} 注册失败，可能被其他程序占用", "warn"
            )
        )

    def _register_hotkeys(self) -> None:
        s = self.config.settings.hotkeys
        self.hotkeys.register(
            {
                "toggle_start": s.toggle_start,
                "open_workbench": s.open_workbench,
                "toggle_click_through": s.toggle_click_through,
                "toggle_overlay": s.toggle_overlay,
                "open_kana": s.open_kana,
            }
        )

    # ------------------------------------------------------------------ 动作
    def toggle_session(self) -> None:
        if self.pipeline.running or self.pipeline.booting:
            self.pipeline.stop()
        else:
            self.pipeline.start()

    def show_workbench(self) -> None:
        if self.workbench.isMinimized():
            self.workbench.showNormal()
        else:
            self.workbench.show()
        self.workbench.raise_()
        self.workbench.activateWindow()

    def show_overlay(self) -> None:
        self.overlay.show()
        if not self.config.settings.overlay.click_through:
            self.overlay.raise_()
            self.overlay.activateWindow()

    def toggle_overlay(self) -> None:
        if self.overlay.isVisible():
            self.overlay.hide()
        else:
            self.show_overlay()

    def _on_hotkey(self, action: str) -> None:
        if action == "toggle_start":
            self.toggle_session()
        elif action == "open_workbench":
            self.show_workbench()
        elif action == "toggle_click_through":
            self.overlay.toggle_click_through()
        elif action == "toggle_overlay":
            self.toggle_overlay()
        elif action == "open_kana":
            self.show_kana()

    def show_kana(self) -> None:
        if self._kana is None:
            self._kana = KanaWindow()
        self._kana.show()
        if self._kana.isMinimized():
            self._kana.showNormal()
        self._kana.raise_()
        self._kana.activateWindow()

    def _set_click_through(self, enabled: bool) -> None:
        self.overlay.set_click_through(enabled)

    def _on_click_through(self, enabled: bool) -> None:
        self.tray.set_click_through(enabled)
        self.config.settings.overlay.click_through = enabled
        self.config.save()
        if enabled:
            self.tray.showMessage(
                "鼠标穿透已开启",
                "字幕窗不再接收鼠标。按 Ctrl+Alt+T 或从托盘关闭。",
                QSystemTrayIcon.Information,
                3500,
            )
        self._sync_settings()

    def _on_overlay_hidden(self) -> None:
        if not self._quitting:
            self.tray.showMessage(
                "字幕窗已隐藏",
                "从系统托盘双击图标，或按 Ctrl+Alt+H 重新显示。",
                QSystemTrayIcon.Information,
                2500,
            )

    def _on_segment_state(self, seg_id: str, state: str) -> None:
        if state in ("translating",):
            self.overlay.set_translation(seg_id, "", state="translating")
        elif state == "skipped":
            self.overlay.set_translation(seg_id, "", error="翻译积压，已跳过")
        elif state == "aborted":
            self.overlay.set_translation(seg_id, "", state="done")

    def _on_session_started(self, info: dict) -> None:
        self.overlay.clear()
        self.overlay.set_empty_text("同传中…", "识别到语音后，原文与译文会逐句出现")
        self.overlay.set_empty_visible(True)

    def _on_session_finished(self, info: dict) -> None:
        self.overlay.set_empty_text("等待声音…", "点击「开始」或按 Ctrl+Shift+S 启动同传")
        if self.overlay._cards:
            self.overlay.set_empty_visible(False)

    def _on_toast(self, message: str, level: str) -> None:
        self.overlay.flash(message, level)
        if level in ("error", "warn") and not self.workbench.isVisible():
            self.tray.showMessage("RoseSI", message, QSystemTrayIcon.Warning, 3500)

    def _sync_settings(self) -> None:
        if self.workbench.isVisible():
            self.workbench.settings.sync_overlay()

    def _save_all(self) -> None:
        self.workbench._save_geometry()
        self.config.save()

    def _apply_settings(self) -> None:
        self.overlay.apply_settings()
        self.tray.set_click_through(self.config.settings.overlay.click_through)
        self._register_hotkeys()
        self.workbench.dashboard.refresh_engine_info()

    def _notify(self, message: str, level: str = "info") -> None:
        self.overlay.flash(message, level)
        self.tray.showMessage("RoseSI", message, QSystemTrayIcon.Information, 3000)

    # ------------------------------------------------------------------ 退出
    def quit(self) -> None:
        if self._quitting:
            return
        if self.pipeline.running or self.pipeline.booting:
            box = QMessageBox()
            box.setWindowTitle("退出 RoseSI")
            box.setText("同传仍在进行，确定退出吗？\n当前会话会保存已完成的片段。")
            yes = box.addButton("退出", QMessageBox.AcceptRole)
            box.addButton("取消", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is not yes:
                return
        self._quitting = True
        try:
            self.hotkeys.unregister_all()
            self.pipeline.shutdown()
            self.workbench.force_close()
            self.overlay.hide()
            self.tray.hide()
            self.db.close()
        finally:
            self.app.quit()


def _prepare_frozen_dlls() -> None:
    """PyInstaller 运行时把 CUDA / llama.cpp 的 DLL 目录加入搜索路径。"""
    if not getattr(sys, "frozen", False):
        return
    roots = [Path(sys.executable).resolve().parent]
    roots.append(roots[0] / "cudnn")
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        root = Path(meipass)
        roots += [root, root / "llama_cpp" / "lib", root / "ctranslate2"]
    for folder in roots:
        try:
            if folder.is_dir():
                os.add_dll_directory(str(folder))
        except (AttributeError, OSError):
            pass


def package_check() -> int:
    """打包后自检：确认内置模型和原生依赖能被找到，不读取 API Key。"""
    result: dict[str, object] = {
        "frozen": bool(getattr(sys, "frozen", False)),
        "executable": sys.executable,
        "bundle_root": str(paths.bundle_root()),
        "bundled_models": str(paths.bundled_models_dir()),
        "data_dir": str(paths.data_dir()),
    }
    try:
        from .config import TranslateSettings

        result["api_key_empty_by_default"] = TranslateSettings().api_key_enc == ""
    except Exception as exc:
        result["api_key_empty_by_default"] = f"error: {exc}"
    try:
        parakeet = paths.resolve_parakeet_dir()
        result["asr_parakeet"] = str(parakeet)
        result["asr_parakeet_ok"] = paths.parakeet_ready()
    except Exception as exc:
        result["asr_parakeet_ok"] = False
        result["asr_parakeet_error"] = str(exc)
    try:
        local = paths.resolve_local_mt_model("hy-mt-1.8b-q4")
        result["local_mt"] = local
        result["local_mt_ok"] = bool(local) and Path(local).is_file()
    except Exception as exc:
        result["local_mt_ok"] = False
        result["local_mt_error"] = str(exc)
    for module in ("faster_whisper", "ctranslate2", "llama_cpp", "onnxruntime"):
        try:
            __import__(module)
            result[module] = "ok"
        except Exception as exc:
            result[module] = f"error: {exc}"
    try:
        import llama_cpp

        result["llama_gpu_offload"] = bool(llama_cpp.llama_supports_gpu_offload())
    except Exception as exc:
        result["llama_gpu_offload"] = f"error: {exc}"
    out = paths.data_dir() / "package_check.json"
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    try:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception:
        pass
    ok = bool(result.get("asr_parakeet_ok")) and bool(result.get("local_mt_ok"))
    return 0 if ok else 1


def main() -> int:
    paths.setup_logging()
    _prepare_frozen_dlls()
    if "--package-check" in sys.argv:
        return package_check()
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "RoseSI.Desktop.1"
            )
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("RoseSI")
    app.setQuitOnLastWindowClosed(False)
    if sys.platform == "win32":
        try:
            import ctypes

            # Qt 使用 STA；先初始化可避免 soundcard 在枚举线程之外把主线程改成 MTA。
            ctypes.windll.ole32.OleInitialize(None)
        except Exception:
            pass
    apply_theme(app)
    icon = app_icon()
    app.setWindowIcon(icon)
    try:
        controller = InterpreterApp(app)
    except SystemExit as exc:
        return int(exc.code or 0)
    except Exception:
        log.exception("应用启动失败")
        QMessageBox.critical(None, "启动失败", "应用启动失败，请查看日志：\n" + str(paths.logs_dir()))
        return 1
    app.aboutToQuit.connect(controller._save_all)
    return app.exec()
