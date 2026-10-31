"""工作台 · 实时总览。"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..widgets import Card, PageHeader, StatRow, button
from ... import paths

if TYPE_CHECKING:
    from ...config import ConfigStore
    from ...db import Database
    from ...pipeline import Pipeline


class TranscriptItem(QFrame):
    def __init__(self, seg: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TranscriptItem")
        self.setStyleSheet(
            "QFrame#TranscriptItem { background: #1a1e26; border: 1px solid #232833;"
            " border-radius: 8px; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 12, 0)
        layout.setSpacing(0)
        accent = QFrame()
        accent.setFixedWidth(3)
        accent.setStyleSheet("background: #4f8cff; border-radius: 1px;")
        layout.addWidget(accent)
        body = QVBoxLayout()
        body.setContentsMargins(12, 8, 0, 8)
        body.setSpacing(3)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        self.src = QLabel(str(seg.get("src", "")))
        self.src.setWordWrap(True)
        self.src.setStyleSheet("color: #8b93a7; font-size: 12px;")
        self.state = QLabel("聆听中")
        self.state.setStyleSheet("color: #6f7789; font-size: 10px;")
        top.addWidget(self.src, 1)
        top.addWidget(self.state, 0, Qt.AlignTop)
        body.addLayout(top)
        self.dst = QLabel(str(seg.get("dst", "")))
        self.dst.setWordWrap(True)
        self.dst.setStyleSheet("color: #e6e8ee; font-size: 14px;")
        body.addWidget(self.dst)
        layout.addLayout(body, 1)
        self._seg = seg
        self.set_state(str(seg.get("state", "listening")))

    def set_state(self, state: str, error: str = "") -> None:
        texts = {
            "listening": "聆听中",
            "transcribing": "识别中",
            "translating": "翻译中",
            "output": "输出中",
            "done": "完成",
            "error": "出错",
            "aborted": "已取消",
        }
        colors = {
            "listening": "#6f7789",
            "transcribing": "#f0a020",
            "translating": "#4f8cff",
            "output": "#4f8cff",
            "done": "#35c26b",
            "error": "#e5484d",
            "aborted": "#6f7789",
        }
        self.state.setText(texts.get(state, state))
        self.state.setStyleSheet(
            f"color: {colors.get(state, '#6f7789')}; font-size: 10px;"
        )
        if error:
            self.dst.setText("⚠ " + error)
            self.dst.setStyleSheet("color: #ff9a9e; font-size: 12px;")

    def set_source(self, text: str) -> None:
        self.src.setText(text)

    def set_translation(self, text: str, streaming: bool = False) -> None:
        value = text + ("▍" if streaming and text else "")
        self.dst.setText(value or ("…" if streaming else ""))
        self.dst.setStyleSheet("color: #e6e8ee; font-size: 14px;")


class DashboardPage(QWidget):
    start_requested = Signal()
    overlay_requested = Signal()
    settings_requested = Signal()
    api_tested = Signal(bool, str)

    def __init__(
        self,
        pipeline: "Pipeline",
        db: "Database",
        config: "ConfigStore",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.pipeline = pipeline
        self.db = db
        self.config = config
        self._items: dict[str, TranscriptItem] = {}
        self._build()
        self.refresh_engine_info()
        self.api_tested.connect(self._on_api_tested)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)
        header = PageHeader(
            "实时同传", "本地 Whisper 识别 + 本地/DeepSeek 流式翻译 + 本地术语库/语料库"
        )
        self.start_button = button("开始同传", "primary")
        self.start_button.setMinimumWidth(104)
        self.start_button.clicked.connect(self.start_requested)
        header.add_action(self.start_button)
        overlay_btn = button("打开字幕窗", "ghost")
        overlay_btn.clicked.connect(self.overlay_requested)
        header.add_action(overlay_btn)
        root.addWidget(header)

        grid = QHBoxLayout()
        grid.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(16)
        self.transcript_card = Card("实时字幕预览")
        self.transcript_scroll = QScrollArea()
        self.transcript_scroll.setWidgetResizable(True)
        self.transcript_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.transcript_scroll.setMinimumHeight(420)
        container = QWidget()
        self.transcript_layout = QVBoxLayout(container)
        self.transcript_layout.setContentsMargins(0, 0, 4, 0)
        self.transcript_layout.setSpacing(8)
        self.empty_label = QLabel("点击「开始同传」后，识别与翻译结果将在此显示。")
        self.empty_label.setObjectName("Dim")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setMinimumHeight(380)
        self.transcript_layout.addWidget(self.empty_label)
        self.transcript_layout.addStretch(1)
        self.transcript_scroll.setWidget(container)
        self.transcript_card.add_widget(self.transcript_scroll)
        left.addWidget(self.transcript_card, 1)
        grid.addLayout(left, 1)

        right = QVBoxLayout()
        right.setSpacing(16)
        stats = Card("运行状态")
        self.row_asr = StatRow("ASR 延迟")
        self.row_ttfb = StatRow("翻译 TTFB")
        self.row_e2e = StatRow("端到端延迟")
        self.row_count = StatRow("本次片段", "0")
        self.row_source = StatRow("音频源", "—")
        self.row_language = StatRow("识别语言", "自动")
        for row in (
            self.row_asr,
            self.row_ttfb,
            self.row_e2e,
            self.row_count,
            self.row_source,
            self.row_language,
        ):
            stats.add_widget(row)
        right.addWidget(stats)

        engine = Card("引擎")
        self.model_label = QLabel("—")
        self.model_label.setObjectName("Dim")
        self.model_label.setWordWrap(True)
        engine.add_widget(self._kv("本地模型", self.model_label))
        self.glossary_label = QLabel("0 条")
        engine.add_widget(self._kv("启用术语", self.glossary_label))
        self.tm_label = QLabel("0 条")
        engine.add_widget(self._kv("语料库", self.tm_label))
        self.api_label = QLabel("—")
        engine.add_widget(self._kv("翻译服务", self.api_label))
        actions = QHBoxLayout()
        test_btn = button("测试翻译", "soft")
        test_btn.clicked.connect(self._test_api)
        settings_btn = button("打开设置", "ghost")
        settings_btn.clicked.connect(self.settings_requested)
        actions.addWidget(test_btn)
        actions.addWidget(settings_btn)
        engine.add_layout(actions)
        right.addWidget(engine)
        right.addStretch(1)
        wrap = QWidget()
        wrap.setLayout(right)
        wrap.setFixedWidth(310)
        grid.addWidget(wrap)
        root.addLayout(grid, 1)

    def _kv(self, key: str, value: QLabel) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 3, 0, 3)
        key_label = QLabel(key)
        key_label.setObjectName("Dim")
        layout.addWidget(key_label)
        layout.addStretch(1)
        layout.addWidget(value)
        value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        return widget

    # ------------------------------------------------------------------
    def refresh_engine_info(self) -> None:
        overview = self.db.overview()
        s = self.config.settings.asr
        self.model_label.setText(f"{s.model} · {s.device}/{s.compute_type}")
        self.glossary_label.setText(f"{overview['enabled_terms']} 条")
        self.tm_label.setText(f"{overview['tm']} 条")
        if self.config.settings.demo_mode:
            self.api_label.setText("演示模式")
            self.api_label.setStyleSheet("color: #f0a020;")
        elif self.config.settings.translate.provider in ("local", "hy-mt", "offline"):
            t = self.config.settings.translate
            path = paths.resolve_local_mt_model(t.local_model, t.local_model_path)
            if path:
                self.api_label.setText(f"本地 · {paths.local_mt_label(t.local_model)}")
                self.api_label.setStyleSheet("color: #35c26b;")
            else:
                self.api_label.setText("本地模型未下载")
                self.api_label.setStyleSheet("color: #e5484d;")
        elif self.config.has_api_key:
            self.api_label.setText(self.config.settings.translate.model)
            self.api_label.setStyleSheet("color: #35c26b;")
        else:
            self.api_label.setText("未配置 API Key")
            self.api_label.setStyleSheet("color: #e5484d;")

    def set_status(self, state: str, message: str = "") -> None:
        if state in ("loading", "stopping"):
            self.start_button.setText("取消" if state == "loading" else "停止中…")
            self.start_button.setEnabled(state != "stopping")
            self.start_button.setProperty("variant", "soft")
        elif state == "running":
            self.start_button.setText("停止同传")
            self.start_button.setEnabled(True)
            self.start_button.setProperty("variant", "danger")
        else:
            self.start_button.setText("开始同传")
            self.start_button.setEnabled(True)
            self.start_button.setProperty("variant", "primary")
        self.start_button.style().unpolish(self.start_button)
        self.start_button.style().polish(self.start_button)

    def set_stats(self, stats: dict[str, Any]) -> None:
        def ms(key: str) -> tuple[str, str]:
            value = float(stats.get(key) or 0)
            if value <= 0:
                return "—", ""
            tone = "good" if value < 1200 else "warn"
            return f"{value / 1000:.2f}s", tone

        text, tone = ms("asr_ms")
        self.row_asr.set_value(text, tone)
        text, tone = ms("ttfb_ms")
        self.row_ttfb.set_value(text, tone)
        text, tone = ms("e2e_ms")
        self.row_e2e.set_value(text, tone)
        self.row_count.set_value(str(stats.get("segments", 0)))
        if stats.get("audio_source"):
            self.row_source.set_value(str(stats["audio_source"]))
        if stats.get("language"):
            self.row_language.set_value(str(stats["language"]))

    # ------------------------------------------------------------------
    def clear_transcript(self) -> None:
        for seg_id in list(self._items):
            self.remove_item(seg_id)
        self.empty_label.setVisible(True)

    def add_item(self, seg: dict[str, Any]) -> None:
        seg_id = str(seg.get("id"))
        if not seg_id or seg_id in self._items:
            return
        item = TranscriptItem(seg)
        self._items[seg_id] = item
        index = self.transcript_layout.count() - 1
        self.transcript_layout.insertWidget(max(0, index), item)
        self.empty_label.setVisible(False)
        while len(self._items) > 200:
            old_id = next(iter(self._items))
            self.remove_item(old_id)
        self._scroll_to_bottom()

    def update_item(self, seg: dict[str, Any]) -> None:
        seg_id = str(seg.get("id"))
        item = self._items.get(seg_id)
        if item is None:
            self.add_item(seg)
            return
        state = str(seg.get("state", ""))
        if seg.get("src"):
            item.set_source(str(seg["src"]))
        if seg.get("error"):
            item.set_state("error", str(seg["error"]))
        elif seg.get("dst"):
            item.set_translation(
                str(seg["dst"]), streaming=state in ("output", "translating")
            )
            item.set_state(state)
        else:
            item.set_state(state)

    def remove_item(self, seg_id: str) -> None:
        item = self._items.pop(seg_id, None)
        if item is not None:
            self.transcript_layout.removeWidget(item)
            item.deleteLater()
        if not self._items:
            self.empty_label.setVisible(True)

    def _scroll_to_bottom(self) -> None:
        bar = self.transcript_scroll.verticalScrollBar()
        if bar.value() >= bar.maximum() - 60:
            bar.setValue(bar.maximum())

    def _test_api(self) -> None:
        self.api_label.setText("测试中…")
        self.api_label.setStyleSheet("color: #f0a020;")

        def work() -> None:
            try:
                ok, message = self.pipeline._translator.test_connection()
            except Exception as exc:
                ok, message = False, str(exc)
            self.api_tested.emit(ok, message)

        threading.Thread(target=work, daemon=True).start()

    def _on_api_tested(self, ok: bool, message: str) -> None:
        if ok:
            self.refresh_engine_info()
            self.api_label.setToolTip(message)
        else:
            self.api_label.setText("本地不可用" if self.config.settings.translate.provider == "local" else "连接失败")
            self.api_label.setStyleSheet("color: #e5484d;")
            self.api_label.setToolTip(message)
