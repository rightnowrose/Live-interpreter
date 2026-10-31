"""同传工作台主窗口。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QByteArray, QSize, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..config import ConfigStore
from ..db import Database
from .icons import make_icon
from .pages.corpus import CorpusPage
from .pages.dashboard import DashboardPage
from .pages.export import ExportPage
from .pages.history import HistoryPage
from .pages.settings import SettingsPage
from .pages.terms import TermsPage
from .theme import app_icon, apply_dark_title_bar
from .widgets import StatusDot, Toast, button, label

if TYPE_CHECKING:
    from ..pipeline import Pipeline

log = logging.getLogger(__name__)

PAGES = [
    ("dashboard", "live", "实时同传"),
    ("terms", "terms", "术语库"),
    ("corpus", "corpus", "语料库"),
    ("history", "history", "会话记录"),
    ("export", "export", "导出"),
    ("settings", "settings", "设置"),
]

NAV_GROUPS = [
    ("同传", ("dashboard", "terms", "corpus")),
    ("记录", ("history", "export")),
    ("系统", ("settings",)),
]


class WorkbenchWindow(QMainWindow):
    show_overlay_requested = Signal()
    kana_requested = Signal()
    hotkeys_changed = Signal()
    settings_applied = Signal()
    quit_requested = Signal()

    def __init__(
        self, pipeline: "Pipeline", db: Database, config: ConfigStore, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.pipeline = pipeline
        self.db = db
        self.config = config
        self._force_quit = False
        self._pages: dict[str, QWidget] = {}
        self._nav_buttons: dict[str, QPushButton] = {}
        self._nav_titles: dict[str, str] = {}
        self._section_labels: list[QLabel] = []
        self._sidebar_collapsed = bool(config.settings.ui.sidebar_collapsed)
        self._last_status = ("idle", "")
        self.setWindowTitle("RoseSI · 同传工作台")
        self.setWindowIcon(app_icon())
        self.resize(1180, 790)
        self.setMinimumSize(1000, 660)
        self._restore_geometry()
        self._build()
        self._connect_pipeline()
        self._restore_page()

    # ------------------------------------------------------------------ 构建
    def _build(self) -> None:
        central = QWidget()
        central.setObjectName("Root")
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(220)
        self._sidebar = sidebar
        side = QVBoxLayout(sidebar)
        self._side_layout = side
        side.setContentsMargins(14, 20, 14, 14)
        side.setSpacing(4)
        brand = QHBoxLayout()
        brand.setContentsMargins(6, 0, 0, 14)
        brand.setSpacing(10)
        logo = QLabel()
        logo.setObjectName("LogoImage")
        logo.setPixmap(app_icon(36).pixmap(36, 36))
        logo.setFixedSize(36, 36)
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet("background: transparent;")
        brand.addWidget(logo)
        text = QVBoxLayout()
        text.setSpacing(1)
        self._brand_name = QLabel("RoseSI")
        self._brand_name.setObjectName("BrandName")
        self._brand_sub = QLabel("本地同传工作台")
        self._brand_sub.setObjectName("BrandSub")
        text.addWidget(self._brand_name)
        text.addWidget(self._brand_sub)
        brand.addLayout(text)
        brand.addStretch(1)
        self._side_toggle = QPushButton("‹")
        self._side_toggle.setObjectName("SideToggle")
        self._side_toggle.setFixedSize(22, 26)
        self._side_toggle.setCursor(Qt.PointingHandCursor)
        self._side_toggle.setToolTip("收起侧栏")
        self._side_toggle.clicked.connect(self._toggle_sidebar)
        brand.addWidget(self._side_toggle)
        side.addLayout(brand)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        page_meta = {key: (icon_name, title) for key, icon_name, title in PAGES}
        for group_title, keys in NAV_GROUPS:
            section = QLabel(group_title)
            section.setObjectName("NavSection")
            side.addWidget(section)
            self._section_labels.append(section)
            for key in keys:
                icon_name, title = page_meta[key]
                nav_button = QPushButton(title)
                nav_button.setObjectName("Nav")
                nav_button.setCheckable(True)
                nav_button.setCursor(Qt.PointingHandCursor)
                nav_button.setFixedHeight(40)
                nav_button.setIcon(make_icon(icon_name, "#a795c2", 40))
                nav_button.setIconSize(QSize(16, 16))
                nav_button.setToolTip(title)
                nav_button.toggled.connect(
                    lambda checked, b=nav_button, name=icon_name: b.setIcon(
                        make_icon(name, "#ff9cc7" if checked else "#a795c2", 40)
                    )
                )
                nav_button.clicked.connect(lambda _=False, k=key: self.show_page(k))
                self._group.addButton(nav_button)
                side.addWidget(nav_button)
                self._nav_buttons[key] = nav_button
                self._nav_titles[key] = title
        side.addStretch(1)

        self.kana_button = button("あ  五十音图", "ghost")
        self.kana_button.setCursor(Qt.PointingHandCursor)
        self.kana_button.setToolTip("打开五十音图（Ctrl+Alt+K）")
        self.kana_button.clicked.connect(self.kana_requested.emit)
        side.addWidget(self.kana_button)

        self.side_start = button("开始同传", "primary")
        self.side_start.setObjectName("SideAction")
        self.side_start.setCursor(Qt.PointingHandCursor)
        self.side_start.clicked.connect(self._toggle_session)
        side.addWidget(self.side_start)

        self.dot = StatusDot("idle")
        footer = QHBoxLayout()
        footer.setContentsMargins(8, 8, 8, 0)
        footer.setSpacing(8)
        footer.addWidget(self.dot)
        self.footer_label = QLabel("引擎就绪")
        self.footer_label.setObjectName("Dim")
        footer.addWidget(self.footer_label)
        footer.addStretch(1)
        side.addLayout(footer)
        version = label(f"v{__version__} · 本地优先", "Tiny")
        version.setContentsMargins(8, 2, 0, 0)
        self._version_label = version
        side.addWidget(version)
        self._apply_sidebar_state(self._sidebar_collapsed, initial=True)
        layout.addWidget(sidebar)

        content = QWidget()
        content.setObjectName("Content")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        content_layout.addWidget(self.stack)
        layout.addWidget(content, 1)

        self.dashboard = DashboardPage(self.pipeline, self.db, self.config)
        self.terms = TermsPage(self.pipeline, self.db, self.config)
        self.corpus = CorpusPage(self.pipeline, self.db, self.config)
        self.history = HistoryPage(self.pipeline, self.db)
        self.export = ExportPage(self.pipeline, self.db)
        self.settings = SettingsPage(self.pipeline, self.config)
        for key, page in (
            ("dashboard", self.dashboard),
            ("terms", self.terms),
            ("corpus", self.corpus),
            ("history", self.history),
            ("export", self.export),
            ("settings", self.settings),
        ):
            self._pages[key] = page
            self.stack.addWidget(page)

        self.toast = Toast(central)
        self._connect_pages()
        self.show_page(self.config.settings.ui.last_page, remember=False)

    def _connect_pages(self) -> None:
        self.dashboard.start_requested.connect(self._toggle_session)
        self.dashboard.overlay_requested.connect(self.show_overlay_requested)
        self.dashboard.settings_requested.connect(lambda: self.show_page("settings"))
        self.terms.changed.connect(self._on_data_changed)
        self.corpus.changed.connect(self._on_data_changed)
        self.pipeline.candidates_changed.connect(self._on_candidates_changed)
        self._on_candidates_changed(self.pipeline.db.candidate_count(status="pending"))
        for page in (self.terms, self.corpus, self.history, self.export, self.settings):
            page.notify.connect(self.show_toast)
        self.settings.settings_saved.connect(self._on_settings_saved)
        self.settings.hotkeys_changed.connect(self.hotkeys_changed)
        self.settings.preview_overlay.connect(self.show_overlay_requested)
        self.settings.api_tested.connect(lambda ok, msg: self.show_toast(msg, "success" if ok else "error"))

    def _connect_pipeline(self) -> None:
        self.pipeline.status_changed.connect(self._on_status)
        self.pipeline.stats_changed.connect(self.dashboard.set_stats)
        self.pipeline.segment_started.connect(self.dashboard.add_item)
        self.pipeline.source_partial.connect(
            lambda seg_id, text: self.dashboard.update_item(
                {"id": seg_id, "src": text, "state": "transcribing"}
            )
        )
        self.pipeline.source_final.connect(
            lambda seg_id, text, meta: self.dashboard.update_item(
                {"id": seg_id, "src": text, "state": "translating"}
            )
        )
        self.pipeline.translation_delta.connect(
            lambda seg_id, text: self.dashboard.update_item(
                {"id": seg_id, "dst": text, "state": "output"}
            )
        )
        self.pipeline.translation_done.connect(
            lambda seg_id, text, meta: self.dashboard.update_item(
                {"id": seg_id, "dst": text, "state": "done", "terms": meta.get("terms", [])}
            )
        )
        self.pipeline.translation_failed.connect(
            lambda seg_id, msg: self.dashboard.update_item(
                {"id": seg_id, "error": msg, "state": "error"}
            )
        )
        self.pipeline.segment_dropped.connect(self.dashboard.remove_item)
        self.pipeline.session_started.connect(self._on_session_started)
        self.pipeline.session_finished.connect(self._on_session_finished)
        self.pipeline.toast.connect(self.show_toast)
        self.pipeline.error.connect(lambda msg: self.show_toast(msg, "error"))

    # ------------------------------------------------------------------ 页面/状态
    def show_page(self, key: str, remember: bool = True) -> None:
        if key not in self._pages:
            key = "dashboard"
        self.stack.setCurrentWidget(self._pages[key])
        for name, button in self._nav_buttons.items():
            button.setChecked(name == key)
        if remember:
            self.config.settings.ui.last_page = key
            self.config.save()
        if key == "dashboard":
            self.dashboard.refresh_engine_info()
        elif key == "corpus":
            self.corpus.reload()
        elif key == "terms":
            self.terms.reload_banks()
        elif key == "corpus":
            self.corpus.reload()
        elif key == "history":
            self.history.reload()
        elif key == "export":
            self.export.reload()
        elif key == "settings":
            self.settings.sync_overlay()

    def _restore_page(self) -> None:
        self.show_page(self.config.settings.ui.last_page, remember=False)

    def _toggle_session(self) -> None:
        if self.pipeline.running or self.pipeline.booting:
            self.pipeline.stop()
        else:
            self.pipeline.start()

    def _toggle_sidebar(self) -> None:
        self._apply_sidebar_state(not self._sidebar_collapsed)
        self.config.settings.ui.sidebar_collapsed = self._sidebar_collapsed
        self.config.save()

    def _apply_sidebar_state(self, collapsed: bool, initial: bool = False) -> None:
        self._sidebar_collapsed = bool(collapsed)
        self._sidebar.setFixedWidth(84 if collapsed else 220)
        self._side_layout.setContentsMargins(
            8 if collapsed else 14, 16 if collapsed else 20, 8 if collapsed else 14, 12
        )
        self._brand_name.setVisible(not collapsed)
        self._brand_sub.setVisible(not collapsed)
        self.footer_label.setVisible(not collapsed)
        self._version_label.setVisible(not collapsed)
        self._side_toggle.setText("›" if collapsed else "‹")
        self._side_toggle.setToolTip("展开侧栏" if collapsed else "收起侧栏")
        self.side_start.setFixedWidth(68 if collapsed else 192)
        self.kana_button.setFixedWidth(68 if collapsed else 192)
        self.kana_button.setText("あ" if collapsed else "あ  五十音图")
        self.kana_button.setToolTip("五十音图（Ctrl+Alt+K）")
        for section in self._section_labels:
            section.setVisible(not collapsed)
        for key, button in self._nav_buttons.items():
            title = self._nav_titles.get(key, "")
            button.setText("" if collapsed else title)
            button.setToolTip(title)
            button.setIconSize(QSize(18, 18) if collapsed else QSize(16, 16))
            button.setFixedHeight(44 if collapsed else 40)
            if button.property("collapsed") != collapsed:
                button.setProperty("collapsed", collapsed)
                button.style().unpolish(button)
                button.style().polish(button)
        self._apply_side_start_text()
        if not initial:
            self._on_candidates_changed(self.pipeline.db.candidate_count(status="pending"))

    def _apply_side_start_text(self) -> None:
        if not hasattr(self, "side_start"):
            return
        state, _ = self._last_status
        collapsed = self._sidebar_collapsed
        if state == "running":
            self.side_start.setText("停止" if collapsed else "停止同传")
            self.side_start.setEnabled(True)
            self.side_start.setProperty("variant", "danger")
        elif state in ("loading", "stopping"):
            self.side_start.setText(
                ("取消" if state == "loading" else "停止中") if collapsed
                else ("取消" if state == "loading" else "停止中…")
            )
            self.side_start.setEnabled(state != "stopping")
            self.side_start.setProperty("variant", "soft")
        else:
            self.side_start.setText("开始" if collapsed else "开始同传")
            self.side_start.setEnabled(True)
            self.side_start.setProperty("variant", "primary")
        self.side_start.style().unpolish(self.side_start)
        self.side_start.style().polish(self.side_start)

    def _on_status(self, state: str, message: str) -> None:
        self._last_status = (state, message)
        self.dot.set_state(state)
        if hasattr(self, "side_start"):
            self._apply_side_start_text()
        texts = {
            "idle": "引擎就绪",
            "loading": "准备中…",
            "running": "正在同传…",
            "stopping": "正在结束…",
            "error": "引擎错误",
        }
        if state == "running" and message:
            display = message if len(message) <= 16 else message[:16] + "…"
            self.footer_label.setText(display)
            self.footer_label.setToolTip(message)
        else:
            self.footer_label.setText(texts.get(state, message or state))
            self.footer_label.setToolTip(message if message else "")
        self.dashboard.set_status(state, message)

    def _on_session_started(self, info: dict) -> None:
        self.dashboard.clear_transcript()
        self.show_toast("同传已开始，字幕窗已就位", "success")
        self.history.reload()
        self.export.reload()

    def _on_session_finished(self, info: dict) -> None:
        seconds = int(info.get("duration_s", 0))
        self.show_toast(
            f"会话已保存 · {seconds // 60} 分 {seconds % 60} 秒 · {info.get('segments', 0)} 段",
            "success",
        )
        self.history.reload()
        self.export.reload()
        self.dashboard.refresh_engine_info()

    def _on_data_changed(self) -> None:
        self.dashboard.refresh_engine_info()
        self._on_candidates_changed(self.pipeline.db.candidate_count(status="pending"))

    def _on_candidates_changed(self, count: int) -> None:
        button = self._nav_buttons.get("corpus")
        if button is None:
            return
        title = self._nav_titles.get("corpus", "语料库")
        if self._sidebar_collapsed:
            button.setText("")
            button.setToolTip(f"{title} · {count} 条候选待审核" if count else title)
        else:
            button.setText(f"{title}  {count}" if count else title)
            button.setToolTip(f"{count} 条语料候选待审核" if count else "语料库与候选审核")

    def _on_settings_saved(self) -> None:
        self.dashboard.refresh_engine_info()
        self.corpus.reload()
        self.settings_applied.emit()

    def show_toast(self, message: str, level: str = "info") -> None:
        self.toast.show_message(message, level)

    # ------------------------------------------------------------------ 窗口
    def _restore_geometry(self) -> None:
        encoded = self.config.settings.ui.window_geometry
        if not encoded:
            return
        try:
            data = QByteArray.fromBase64(encoded.encode("ascii"))
            self.restoreGeometry(data)
        except Exception:
            pass

    def _save_geometry(self) -> None:
        try:
            data = bytes(self.saveGeometry().toBase64()).decode("ascii")
            self.config.settings.ui.window_geometry = data
            self.config.save()
        except Exception:
            pass

    def showEvent(self, event) -> None:
        super().showEvent(event)
        apply_dark_title_bar(self)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._force_quit:
            self._save_geometry()
            super().closeEvent(event)
            return
        event.ignore()
        self._save_geometry()
        self.hide()
        self.show_toast("工作台已隐藏，可从字幕窗或托盘重新打开", "info")

    def force_close(self) -> None:
        self._force_quit = True
        self._save_geometry()
        self.close()

    def open_settings(self) -> None:
        self.show_page("settings")
        self.showNormal()
        self.raise_()
        self.activateWindow()
