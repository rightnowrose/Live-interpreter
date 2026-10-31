"""常驻字幕悬浮窗。"""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Any

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QFont,
    QGuiApplication,
    QLinearGradient,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..config import ConfigStore
from .icons import make_icon
from .theme import app_icon
from .widgets import IconButton, LevelMeter, StatusDot

log = logging.getLogger(__name__)

OVERLAY_QSS = """
QWidget#OverlayRoot { background: transparent; }
QWidget#OverlayBar { background: transparent; }
QLabel#OvLogo {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ff6fa9, stop:1 #8b7bff);
    border-radius: 6px; color: white; font-size: 11px; font-weight: 700;
}
QLabel#OvTitle { color: rgba(246,237,255,0.42); font-size: 9px; letter-spacing: 2px; }
QLabel#OvStatus { color: rgba(246,237,255,0.66); font-size: 11px; }
QLabel#OvLatency { color: rgba(246,237,255,0.42); font-size: 10px; }
QLabel#OvHint { color: rgba(246,237,255,0.3); font-size: 10px; }
QLabel#OvMeta { color: rgba(255,179,209,0.76); font-size: 10px; }
QPushButton#OvJump {
    background: rgba(30,20,44,0.94); border: 1px solid rgba(255,111,169,0.48);
    color: #ffd9ea; border-radius: 12px; padding: 4px 11px;
    font-size: 11px; font-weight: 500;
}
QPushButton#OvJump:hover { background: rgba(55,32,66,0.98); border-color: #ff9cc7; }
QLabel#OvEmptyTitle { color: rgba(246,237,255,0.76); font-size: 14px; }
QLabel#OvEmptySub { color: rgba(246,237,255,0.36); font-size: 11px; }
QPushButton#OvMode {
    background: transparent; border: none; color: #9aa3b5;
    padding: 3px 7px; border-radius: 5px; font-size: 11px;
}
QPushButton#OvMode:hover { background: rgba(255,255,255,0.08); color: #ffffff; }
QPushButton#OvWorkbench {
    background: transparent; border: 1px solid rgba(255,255,255,0.14);
    color: #c3cad8; padding: 3px 10px; border-radius: 6px; font-size: 11px;
}
QPushButton#OvWorkbench:hover { background: rgba(255,255,255,0.08); border-color: rgba(255,255,255,0.25); }
QPushButton#OvStart {
    border: none; border-radius: 6px; padding: 3px 12px;
    font-size: 11px; font-weight: 600; color: white;
}
"""


class SubtitleCard(QFrame):
    def __init__(self, font_size: int = 22, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SubtitleCard")
        self._font_size = font_size
        self._mode = "bilingual"
        self._past = False
        self._terms: list[dict[str, str]] = []
        self._via_tm = False
        self._meta_text = ""
        self._dst_full = ""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(11)
        self.accent = QFrame()
        self.accent.setFixedWidth(3)
        self.accent.setStyleSheet(
            "background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            " stop:0 #4f8cff, stop:1 #7b5cff); border-radius: 1px;"
        )
        layout.addWidget(self.accent)
        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(2)
        self.src = QLabel("")
        self.src.setWordWrap(True)
        self.src.setTextFormat(Qt.PlainText)
        self.src.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.dst = QLabel("")
        self.dst.setWordWrap(True)
        self.dst.setTextFormat(Qt.PlainText)
        self.dst.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.meta = QLabel("")
        self.meta.setObjectName("OvMeta")
        self.meta.setVisible(False)
        content.addWidget(self.src)
        content.addWidget(self.dst)
        content.addWidget(self.meta)
        layout.addLayout(content, 1)
        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.apply_font(font_size)

    @staticmethod
    def _families(text: str) -> list[str]:
        # 日文假名优先用日文字体，避免简体中文字形的细微差异。
        if any("\u3040" <= ch <= "\u30ff" for ch in text):
            return ["Yu Gothic UI", "Meiryo", "Noto Sans CJK JP", "Microsoft YaHei UI"]
        return ["Microsoft YaHei UI", "Noto Sans CJK SC", "Yu Gothic UI"]

    @staticmethod
    def _normal_mode(mode: str) -> str:
        return {"both": "bilingual", "dst": "focus", "src": "study"}.get(mode, mode)

    def _source_visible(self) -> bool:
        if self._mode == "focus":
            return False
        if self._mode == "bilingual":
            return not self._past
        return True

    def _target_size(self) -> int:
        if self._mode == "focus":
            return max(26, min(32, int(round(self._font_size * 1.4))))
        if self._mode == "bilingual" and self._past:
            return max(14, int(self._font_size * 0.72))
        factor = 0.92 if self._past else 1.0
        return max(12, int(self._font_size * factor))

    def _source_size(self) -> int:
        if self._mode == "focus":
            return 10
        if self._mode == "bilingual":
            return max(10, int(self._font_size * 0.60))
        return max(10, int(self._font_size * (0.88 if self._past else 0.90)))

    def _apply_target_style(self) -> None:
        self.dst.setStyleSheet(
            f"color: #fffaf6; font-size: {self._target_size()}px; font-weight: 600;"
        )

    def _apply_target_text(self) -> None:
        value = self._dst_full or " "
        if self._mode == "bilingual" and self._past:
            self.dst.setWordWrap(False)
            width = max(80, self.dst.width() - 6)
            shown = self.dst.fontMetrics().elidedText(value, Qt.ElideRight, width)
            self.dst.setText(shown or " ")
            self.dst.setToolTip(value.strip())
        else:
            self.dst.setWordWrap(True)
            self.dst.setText(value)
            self.dst.setToolTip("")

    def _apply_source_font(self) -> None:
        src_size = self._source_size()
        src_font = QFont()
        src_font.setFamilies(self._families(self.src.text()))
        src_font.setPixelSize(src_size)
        self.src.setFont(src_font)
        self.src.setStyleSheet(
            f"color: rgba(232,225,255,0.68); font-size: {src_size}px;"
        )
        self.src.setVisible(self._source_visible())
        self._apply_target_style()
        self._apply_target_text()
        self.meta.setStyleSheet(
            "color: rgba(255,179,209,0.78); font-size: 10px;"
        )

    def apply_font(self, size: int) -> None:
        self._font_size = size
        dst_font = QFont()
        dst_font.setFamilies(["Microsoft YaHei UI", "Noto Sans CJK SC"])
        dst_font.setPixelSize(self._target_size())
        dst_font.setWeight(QFont.DemiBold)
        self.dst.setFont(dst_font)
        self._apply_source_font()
        self._update_meta()

    def set_mode(self, mode: str) -> None:
        self._mode = self._normal_mode(mode)
        if self._mode not in ("focus", "bilingual", "study"):
            self._mode = "bilingual"
        self._apply_source_font()
        self._update_meta()
        self.updateGeometry()

    def set_past(self, past: bool) -> None:
        self._past = past
        self._opacity.setOpacity(0.62 if past else 1.0)
        self.accent.setStyleSheet(
            "background: rgba(255,123,180,0.28); border-radius: 1px;"
            if past
            else "background: qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            " stop:0 #ff7bb4, stop:1 #6ee7f9); border-radius: 1px;"
        )
        self._apply_source_font()
        self._update_meta()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._dst_full:
            self._apply_target_text()

    def set_source(self, text: str, partial: bool = False) -> None:
        value = text.strip()
        if partial and value:
            value += " …"
        self.src.setText(value or " ")
        self.src.setVisible(self._source_visible())
        self._apply_source_font()
        self.updateGeometry()

    def set_translation(
        self,
        text: str,
        state: str = "translating",
        error: str = "",
        via_tm: bool = False,
        terms: list[dict[str, str]] | None = None,
    ) -> None:
        self._via_tm = bool(via_tm)
        if terms is not None:
            self._terms = list(terms)
        if error:
            self._dst_full = "⚠ " + error
            self._via_tm = False
            self._terms = []
            self._apply_source_font()
            self.dst.setStyleSheet(
                "color: #ff9ecb; font-size: %dpx;"
                % max(14, int(self._target_size() * 0.64))
            )
            self._update_meta()
            return
        value = text.strip()
        if state == "output" and value:
            value += "▍"
        elif state == "translating" and not value:
            value = "…"
        self._dst_full = value or " "
        self._apply_source_font()
        self._update_meta()
        self.updateGeometry()

    def set_terms(self, terms: list[dict[str, str]]) -> None:
        self._terms = list(terms or [])
        self._update_meta()
        if terms:
            tip = "\n".join(f"{t.get('src')} → {t.get('dst')}" for t in terms[:8])
            self.dst.setToolTip(tip)
            self.src.setToolTip(tip)

    def _update_meta(self) -> None:
        parts: list[str] = []
        if self._terms:
            parts.append(f"术语 {len(self._terms)}")
        if self._via_tm:
            parts.append("记忆命中")
        self._meta_text = "  ·  ".join(parts)
        show = (
            bool(self._meta_text)
            and not self._past
            and self._mode != "focus"
            and not self.dst.isHidden()
        )
        self.meta.setText(self._meta_text)
        self.meta.setVisible(show)
        self.updateGeometry()

    def hasHeightForWidth(self) -> bool:
        return True

    def sizeHint(self) -> QSize:
        return QSize(320, self.heightForWidth(self.width() or 800))

    def heightForWidth(self, width: int) -> int:
        content_width = max(80, int(width) - 14)
        height = 6  # 上下边距 + 两行之间的间距

        def text_height(label: QLabel) -> int:
            text = label.text().strip()
            if not text:
                return 0
            metrics = label.fontMetrics()
            rect = metrics.boundingRect(
                QRect(0, 0, content_width, 100000), Qt.TextWordWrap, text
            )
            return rect.height() + 2

        if self._mode == "focus":
            height += text_height(self.dst)
        elif self._mode == "bilingual" and self._past:
            # 历史句只留一行，避免滚动区被旧内容占满。
            height += text_height(self.dst)
        else:
            if self._source_visible():
                height += text_height(self.src)
            height += text_height(self.dst)
            if self._meta_text and not self._past:
                height += self.meta.fontMetrics().height() + 1
        return max(24, height)


class OverlayWindow(QWidget):
    toggle_requested = Signal()
    workbench_requested = Signal()
    settings_requested = Signal()
    mode_changed = Signal(str)
    click_through_changed = Signal(bool)
    always_on_top_changed = Signal(bool)
    hidden = Signal()
    kana_requested = Signal()
    geometry_changed = Signal(int, int, int)
    quit_requested = Signal()
    font_size_changed = Signal(int)
    opacity_changed = Signal(float)

    def __init__(self, config: ConfigStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self._cards: OrderedDict[str, SubtitleCard] = OrderedDict()
        self._state = "idle"
        self._mode = config.settings.overlay.mode
        self._click_through = False
        self._drag_origin: QPoint | None = None
        self._drag_start: QPoint | None = None
        self._resizing = False
        self._resize_dir: tuple[bool, bool, bool, bool] = (False, False, False, False)
        self._resize_start_geo: QRect | None = None
        self._resize_start_global: QPoint | None = None
        self._manual_height = bool(config.settings.overlay.height > 0)
        self._sized = False
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._emit_geometry)
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.setInterval(0)
        self._fit_timer.timeout.connect(self._fit_height)
        self._hint_timer = QTimer(self)
        self._hint_timer.setSingleShot(True)
        self._hint_timer.timeout.connect(self._restore_hint)
        self._bar_hide_timer = QTimer(self)
        self._bar_hide_timer.setSingleShot(True)
        self._bar_hide_timer.setInterval(2400)
        self._bar_hide_timer.timeout.connect(self._fade_bar)
        self._running = False
        self._default_hint = "拖动移动 · 拖动边缘调整大小"

        flags = Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        if not config.settings.overlay.always_on_top:
            flags &= ~Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setWindowTitle("RoseSI")
        self.setStyleSheet(OVERLAY_QSS)

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(22, 9, 22, 11)
        self._root.setSpacing(5)
        self._build_bar()
        self._build_content()
        self._build_footer()
        self.apply_settings()
        self.set_mode(self._mode)

    # ------------------------------------------------------------------ 构建
    def _build_bar(self) -> None:
        self._bar = QWidget()
        self._bar.setObjectName("OverlayBar")
        self._bar.setFixedHeight(26)
        self._bar.installEventFilter(self)
        bar = QHBoxLayout(self._bar)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(8)

        self.logo = QLabel(self)
        self.logo.setObjectName("OvLogoImage")
        self.logo.setPixmap(app_icon(20).pixmap(20, 20))
        self.logo.setFixedSize(20, 20)
        self.logo.setAlignment(Qt.AlignCenter)
        self.logo.setStyleSheet("background: transparent; border: none;")
        bar.addWidget(self.logo)

        self.title = QLabel("RoseSI", self)
        self.title.setObjectName("OvTitle")
        bar.addWidget(self.title)
        bar.addSpacing(4)
        self.dot = StatusDot("idle", self)
        bar.addWidget(self.dot)
        self.status_label = QLabel("待机", self)
        self.status_label.setObjectName("OvStatus")
        bar.addWidget(self.status_label)
        bar.addStretch(1)

        self.mode_button = QPushButton("双语", self)
        self.mode_button.setObjectName("OvMode")
        self.mode_button.setCursor(Qt.PointingHandCursor)
        self.mode_button.clicked.connect(self._cycle_mode)
        bar.addWidget(self.mode_button)

        self.workbench_button = QPushButton("工作台", self)
        self.workbench_button.setObjectName("OvWorkbench")
        self.workbench_button.setCursor(Qt.PointingHandCursor)
        self.workbench_button.clicked.connect(self.workbench_requested)
        bar.addWidget(self.workbench_button)

        self.start_button = QPushButton("开始", self)
        self.start_button.setObjectName("OvStart")
        self.start_button.setCursor(Qt.PointingHandCursor)
        self.start_button.clicked.connect(self.toggle_requested)
        self.start_button.setFixedWidth(58)
        bar.addWidget(self.start_button)

        self.pin_button = IconButton("", "窗口置顶", 24, self)
        self.pin_button.setIcon(make_icon("pin", "#c3cad8", 36))
        self.pin_button.setIconSize(QSize(13, 13))
        self.pin_button.setCheckable(True)
        self.pin_button.setChecked(self.config.settings.overlay.always_on_top)
        self.pin_button.toggled.connect(self._on_pin)
        bar.addWidget(self.pin_button)

        self.menu_button = IconButton("", "更多", 24, self)
        self.menu_button.setIcon(make_icon("more", "#c3cad8", 36))
        self.menu_button.setIconSize(QSize(14, 14))
        self.menu_button.clicked.connect(self._show_menu)
        bar.addWidget(self.menu_button)

        self.hide_button = IconButton("", "隐藏到托盘", 24, self)
        self.hide_button.setIcon(make_icon("close", "#c3cad8", 36))
        self.hide_button.setIconSize(QSize(12, 12))
        self.hide_button.clicked.connect(self._hide_clicked)
        bar.addWidget(self.hide_button)

        self._bar_effect = QGraphicsOpacityEffect(self._bar)
        self._bar_effect.setOpacity(0.55)
        self._bar.setGraphicsEffect(self._bar_effect)
        self._root.addWidget(self._bar)

    def _build_content(self) -> None:
        self._content = QWidget()
        self._content.setObjectName("OverlayContent")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(4)
        self._empty = QWidget()
        empty_layout = QVBoxLayout(self._empty)
        empty_layout.setContentsMargins(6, 10, 6, 10)
        empty_layout.setSpacing(3)
        empty_title = QLabel("等待声音…")
        empty_title.setObjectName("OvEmptyTitle")
        empty_sub = QLabel("点击「开始」或按 Ctrl+Shift+S 启动同传")
        empty_sub.setObjectName("OvEmptySub")
        empty_layout.addWidget(empty_title)
        empty_layout.addWidget(empty_sub)
        self._empty_title = empty_title
        self._empty_sub = empty_sub
        self._content_layout.addWidget(self._empty)
        self._content_layout.addStretch(1)

        self._scroll = QScrollArea()
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        self._scroll.viewport().setAutoFillBackground(False)
        self._scroll.setWidget(self._content)
        self._scroll.viewport().installEventFilter(self)
        self._content.installEventFilter(self)
        self._root.addWidget(self._scroll, 1)

        self._jump_button = QPushButton("↓  回到最新", self)
        self._jump_button.setObjectName("OvJump")
        self._jump_button.setCursor(Qt.PointingHandCursor)
        self._jump_button.setVisible(False)
        self._jump_button.clicked.connect(lambda: self._scroll_to_bottom(0))
        self._scroll.verticalScrollBar().valueChanged.connect(self._update_jump_button)

    def _build_footer(self) -> None:
        self._footer = QWidget()
        footer_layout = QHBoxLayout(self._footer)
        footer_layout.setContentsMargins(2, 0, 0, 0)
        footer_layout.setSpacing(8)
        self.level_meter = LevelMeter(self)
        footer_layout.addWidget(self.level_meter)
        self.hint = QLabel(self._default_hint, self)
        self.hint.setObjectName("OvHint")
        footer_layout.addWidget(self.hint)
        footer_layout.addStretch(1)
        self.latency = QLabel("ASR — · 翻译 — · 端到端 —", self)
        self.latency.setObjectName("OvLatency")
        footer_layout.addWidget(self.latency)
        self._root.addWidget(self._footer)

    # ------------------------------------------------------------------ 设置
    def apply_settings(self) -> None:
        cfg = self.config.settings.overlay
        self._manual_height = bool(cfg.height > 0)
        self._mode = cfg.mode
        self.set_mode(cfg.mode)
        self._bar.setVisible(cfg.show_toolbar)
        for card in self._cards.values():
            card.apply_font(cfg.font_size)
        self.setMinimumWidth(520)
        self.setMaximumWidth(2400)
        self.setMinimumHeight(140)
        width = max(520, int(cfg.width))
        if self._manual_height:
            self.resize(width, max(140, int(cfg.height)))
        else:
            self.resize(width, max(140, self.height()))
            self._queue_fit()
        self._update_click_through(bool(cfg.click_through), notify=False)
        self._apply_always_on_top(bool(cfg.always_on_top), notify=False)
        self._update_compact()
        if cfg.x < 0 or cfg.y < 0:
            self._position_default()
        else:
            self.move(int(cfg.x), int(cfg.y))

    def _position_default(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if not screen:
            return
        geo = screen.availableGeometry()
        width = self.width()
        height = max(120, self.height())
        x = geo.x() + (geo.width() - width) // 2
        y = geo.y() + geo.height() - height - 72
        self.move(max(geo.x() + 12, x), max(geo.y() + 12, y))

    def set_mode(self, mode: str) -> None:
        mode = {"both": "bilingual", "dst": "focus", "src": "study"}.get(mode, mode)
        if mode not in ("focus", "bilingual", "study"):
            mode = "bilingual"
        self._mode = mode
        self.mode_button.setText(
            {"focus": "专注", "bilingual": "双语", "study": "学习"}[mode]
        )
        self.mode_button.setToolTip(
            {
                "focus": "专注：只显示当前译文，点击切换为双语",
                "bilingual": "双语：原文小、译文大，历史句一行摘要",
                "study": "学习：原文与译文完整对照，点击切换为专注",
            }[mode]
        )
        for card in self._cards.values():
            card.set_mode(mode)
        self._refresh_past()
        self._queue_fit()

    def _cycle_mode(self) -> None:
        order = ["focus", "bilingual", "study"]
        mode = order[(order.index(self._mode) + 1) % len(order)]
        self.set_mode(mode)
        self.config.settings.overlay.mode = mode
        self.config.save()
        self.mode_changed.emit(mode)

    def _on_pin(self, checked: bool) -> None:
        self._apply_always_on_top(checked, notify=True)

    def _apply_always_on_top(self, enabled: bool, notify: bool = True) -> None:
        if enabled == bool(self.windowFlags() & Qt.WindowStaysOnTopHint):
            if notify:
                self.config.settings.overlay.always_on_top = enabled
                self.config.save()
                self.always_on_top_changed.emit(enabled)
            return
        pos = self.pos()
        flags = self.windowFlags()
        if enabled:
            flags |= Qt.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show()
        self.move(pos)
        self.pin_button.blockSignals(True)
        self.pin_button.setChecked(enabled)
        self.pin_button.blockSignals(False)
        self.config.settings.overlay.always_on_top = enabled
        self.config.save()
        if notify:
            self.always_on_top_changed.emit(enabled)

    def set_click_through(self, enabled: bool, notify: bool = True) -> None:
        self._update_click_through(enabled, notify=notify)

    def _update_click_through(self, enabled: bool, notify: bool = True) -> None:
        if enabled == self._click_through:
            return
        self._click_through = enabled
        pos = self.pos()
        flags = self.windowFlags()
        if enabled:
            flags |= Qt.WindowTransparentForInput
        else:
            flags &= ~Qt.WindowTransparentForInput
        self.setWindowFlags(flags)
        self.show()
        self.move(pos)
        self.config.settings.overlay.click_through = enabled
        self.config.save()
        if notify:
            self.click_through_changed.emit(enabled)

    def toggle_click_through(self) -> None:
        self._update_click_through(not self._click_through)

    # ------------------------------------------------------------------ 状态/字幕
    def set_status(self, state: str, message: str = "") -> None:
        self._state = state
        self._running = state == "running"
        if self._running:
            self._reveal_bar()
            QTimer.singleShot(1200, self._schedule_bar_hide)
        else:
            self._bar_hide_timer.stop()
            if getattr(self, "_bar_effect", None) is not None:
                self._bar_effect.setOpacity(0.55)
        self.dot.set_state(state)
        texts = {
            "idle": "待机",
            "loading": "准备中…",
            "running": "同传中",
            "stopping": "正在结束…",
            "error": "出错",
        }
        if state == "running" and message:
            short = "同传中"
            if "等待" in message:
                short = "等待连接…"
            elif "标签页" in message:
                short = "标签页"
            elif "环回" in message:
                short = "环回"
            elif "麦克风" in message:
                short = "麦克风"
            elif "聆听" in message:
                short = "聆听中…"
            self.status_label.setText(short)
            self.status_label.setToolTip(message)
        else:
            self.status_label.setText(texts.get(state, message or state))
            self.status_label.setToolTip(message if message else "")
        if state in ("loading", "stopping"):
            self.start_button.setText("取消" if state == "loading" else "停止中")
            self.start_button.setEnabled(state != "stopping")
            self.set_start_style("loading")
        elif state == "running":
            self.start_button.setText("停止")
            self.start_button.setEnabled(True)
            self.set_start_style("running")
        elif state == "error":
            self.start_button.setText("重试")
            self.start_button.setEnabled(True)
            self.set_start_style("error")
        else:
            self.start_button.setText("开始")
            self.start_button.setEnabled(True)
            self.set_start_style("idle")
        if state == "loading" and message:
            self.status_label.setToolTip(message)
        if state == "running":
            self.set_empty_visible(not self._cards)

    def set_start_style(self, state: str) -> None:
        colors = {
            "idle": ("#2b3444", "#e6e8ee"),
            "running": ("#e5484d", "#ffffff"),
            "loading": ("#3a2f1c", "#f0a020"),
            "error": ("#3a1d20", "#ff9a9e"),
        }
        bg, fg = colors.get(state, colors["idle"])
        self.start_button.setStyleSheet(
            f"QPushButton#OvStart {{ background: {bg}; color: {fg}; border: none;"
            " border-radius: 6px; padding: 3px 12px; font-size: 11px; font-weight: 600; }"
        )

    def set_level(self, level: float) -> None:
        self.level_meter.set_level(level)

    def set_stats(self, stats: dict[str, Any]) -> None:
        def fmt(value: Any, unit: str = "ms") -> str:
            try:
                number = float(value)
            except (TypeError, ValueError):
                return "—"
            if number <= 0:
                return "—"
            return f"{number / 1000:.2f}s" if unit == "ms" else f"{number:.0f}"

        text = (
            f"ASR {fmt(stats.get('asr_ms'))} · 翻译 {fmt(stats.get('ttfb_ms'))} · 端到端 {fmt(stats.get('e2e_ms'))}"
        )
        queue = int(stats.get("queue") or 0)
        lag_ms = float(stats.get("lag_ms") or 0.0)
        if queue > 0:
            text += f" · 队列 {queue}"
        if lag_ms >= 1000:
            text += f" · 落后 {lag_ms / 1000:.1f}s"
        self.latency.setText(text)

    def set_source(self, seg_id: str, text: str, partial: bool = True) -> None:
        card = self._card(seg_id)
        if card is None:
            return
        card.set_source(text, partial=partial)
        self._queue_fit()

    def set_translation(
        self,
        seg_id: str,
        text: str,
        state: str = "output",
        error: str = "",
        via_tm: bool = False,
        terms: list[dict[str, str]] | None = None,
    ) -> None:
        card = self._card(seg_id)
        if card is None:
            return
        card.set_translation(
            text, state=state, error=error, via_tm=via_tm, terms=terms
        )
        self._queue_fit()
        self._update_jump_button()

    def add_segment(self, seg: dict[str, Any]) -> None:
        seg_id = str(seg.get("id"))
        if not seg_id or seg_id in self._cards:
            return
        card = SubtitleCard(self.config.settings.overlay.font_size, self._content)
        card.set_mode(self._mode)
        card.set_source(str(seg.get("src", "")), partial=True)
        card.set_translation("", state="translating")
        self._content_layout.insertWidget(max(0, self._content_layout.count() - 1), card)
        self._cards[seg_id] = card
        limit = 1 + max(0, int(self.config.settings.overlay.past_lines))
        while len(self._cards) > limit:
            old_id, old_card = next(iter(self._cards.items()))
            self._cards.pop(old_id, None)
            self._content_layout.removeWidget(old_card)
            old_card.deleteLater()
        self._refresh_past()
        self.set_empty_visible(False)
        self._scroll_to_bottom(30)
        self._queue_fit()
        self._update_jump_button()

    def update_segment(self, seg: dict[str, Any]) -> None:
        seg_id = str(seg.get("id"))
        card = self._cards.get(seg_id)
        if card is None:
            self.add_segment(seg)
            card = self._cards.get(seg_id)
        if card is None:
            return
        state = seg.get("state", "")
        if seg.get("src"):
            card.set_source(str(seg["src"]), partial=state in ("listening", "transcribing"))
        if seg.get("error"):
            card.set_translation("", error=str(seg["error"]))
        elif seg.get("dst"):
            card.set_translation(str(seg["dst"]), state=state)
        if seg.get("terms"):
            card.set_terms(list(seg["terms"]))
        self._queue_fit()

    def remove_segment(self, seg_id: str) -> None:
        card = self._cards.pop(seg_id, None)
        if card is not None:
            self._content_layout.removeWidget(card)
            card.deleteLater()
        self._refresh_past()
        self.set_empty_visible(not self._cards)
        self._queue_fit()
        self._update_jump_button()

    def clear(self) -> None:
        for seg_id in list(self._cards):
            self.remove_segment(seg_id)
        self.set_empty_visible(True)

    def _card(self, seg_id: str) -> SubtitleCard | None:
        return self._cards.get(seg_id)

    def _refresh_past(self) -> None:
        ids = list(self._cards)
        focus = self._mode == "focus"
        for index, seg_id in enumerate(ids):
            card = self._cards[seg_id]
            past = index != len(ids) - 1
            card.set_past(past)
            # 专注模式只保留当前句；历史句仍留在内存里，切回双语即可恢复。
            card.setVisible(not (focus and past))

    def set_empty_visible(self, visible: bool) -> None:
        self._empty.setVisible(visible)
        self._queue_fit()

    def set_empty_text(self, title: str, subtitle: str) -> None:
        self._empty_title.setText(title)
        self._empty_sub.setText(subtitle)
        self._queue_fit()

    def _queue_fit(self) -> None:
        self._fit_timer.start(0)

    def _fit_height(self) -> None:
        self._root.activate()
        width = max(520, self.width())
        content_width = max(
            100,
            width
            - self._root.contentsMargins().left()
            - self._root.contentsMargins().right()
            - 12,
        )
        for card in self._cards.values():
            card.setFixedHeight(card.heightForWidth(content_width))
            if self._mode != "focus" or card is next(reversed(self._cards.values())):
                card.show()
        visible_cards = [card for card in self._cards.values() if not card.isHidden()]
        if self._manual_height:
            if width != self.width():
                self.resize(width, self.height())
            return
        margins = self._root.contentsMargins()
        if visible_cards:
            gaps = max(0, len(visible_cards) - 1) * self._content_layout.spacing()
            content_height = (
                sum(card.height() for card in visible_cards) + gaps + 4
            )
        else:
            content_height = self._empty.sizeHint().height() + 12
        bar_height = self._bar.sizeHint().height() if self._bar.isVisible() else 0
        footer_height = self._footer.sizeHint().height()
        height = (
            margins.top()
            + margins.bottom()
            + bar_height
            + footer_height
            + content_height
            + self._root.spacing() * 2
            + 8
        )
        screen = QGuiApplication.screenAt(self.pos()) or QGuiApplication.primaryScreen()
        if screen is not None:
            height = min(height, int(screen.availableGeometry().height() * 0.82))
        height = max(140, height)
        at_bottom = self._is_at_bottom()
        if height != self.height() or width != self.width():
            self.resize(width, height)
        self._position_jump_button()
        if at_bottom:
            self._scroll_to_bottom()

    def _is_at_bottom(self) -> bool:
        bar = self._scroll.verticalScrollBar()
        return bar.value() >= bar.maximum() - 40

    def _scroll_to_bottom(self, delay: int = 0) -> None:
        QTimer.singleShot(delay, self._do_scroll_to_bottom)

    def _do_scroll_to_bottom(self) -> None:
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.maximum())
        self._update_jump_button()

    def _update_jump_button(self) -> None:
        button = getattr(self, "_jump_button", None)
        if button is None:
            return
        bar = self._scroll.verticalScrollBar()
        show = bool(self._cards) and bar.maximum() > 0 and bar.maximum() - bar.value() > 24
        button.setVisible(show)
        if show:
            button.raise_()
            self._position_jump_button()

    def _position_jump_button(self) -> None:
        button = getattr(self, "_jump_button", None)
        if button is None or not button.isVisible():
            return
        button.adjustSize()
        x = max(20, self.width() - button.width() - 24)
        y = max(40, self.height() - button.height() - 48)
        button.move(x, y)

    def _update_compact(self) -> None:
        width = self.width()
        self.title.setVisible(width >= 680)
        self.hint.setVisible(width >= 650)
        self.latency.setVisible(self.config.settings.overlay.show_latency and width >= 760)

    # ------------------------------------------------------------------ 事件
    def _reveal_bar(self) -> None:
        self._bar_hide_timer.stop()
        if getattr(self, "_bar_effect", None) is not None:
            self._bar_effect.setOpacity(1.0)

    def _schedule_bar_hide(self) -> None:
        overlay = self.config.settings.overlay
        if not overlay.show_toolbar or not overlay.auto_hide_toolbar:
            return
        if not self._running:
            return
        self._bar_hide_timer.start()

    def _fade_bar(self) -> None:
        if not self.isVisible():
            return
        cursor = self.mapFromGlobal(QCursor.pos())
        if self.rect().contains(cursor):
            return
        self._bar_effect.setOpacity(0.24)

    def enterEvent(self, event) -> None:
        self._reveal_bar()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        if self.config.settings.overlay.auto_hide_toolbar:
            self._schedule_bar_hide()
        else:
            self._bar_effect.setOpacity(0.55)
        if not self._resizing:
            self.setCursor(Qt.ArrowCursor)
        super().leaveEvent(event)

    def eventFilter(self, obj, event) -> bool:
        if obj is self._bar:
            if event.type() == QEvent.Enter:
                self._reveal_bar()
            elif event.type() == QEvent.Leave:
                self._schedule_bar_hide()
        if obj is self._bar or obj is self._content or obj is self._scroll.viewport():
            if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._drag_origin = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                self._drag_start = event.globalPosition().toPoint()
                return obj is not self._bar
            if event.type() == QEvent.MouseMove and self._drag_origin is not None:
                self.move(event.globalPosition().toPoint() - self._drag_origin)
                return obj is not self._bar
            if event.type() == QEvent.MouseButtonRelease:
                self._drag_origin = None
                self._save_timer.start(500)
                return obj is not self._bar
        return super().eventFilter(obj, event)

    def _edges_at(self, pos: QPoint) -> tuple[bool, bool, bool, bool]:
        margin = 7
        rect = self.rect()
        left = pos.x() <= margin
        right = pos.x() >= rect.width() - margin - 1
        top = pos.y() <= margin
        bottom = pos.y() >= rect.height() - margin - 1
        return left, right, top, bottom

    @staticmethod
    def _cursor_for(edges: tuple[bool, bool, bool, bool]):
        left, right, top, bottom = edges
        if (left and top) or (right and bottom):
            return Qt.SizeFDiagCursor
        if (right and top) or (left and bottom):
            return Qt.SizeBDiagCursor
        if left or right:
            return Qt.SizeHorCursor
        if top or bottom:
            return Qt.SizeVerCursor
        return Qt.ArrowCursor

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            edges = self._edges_at(event.position().toPoint())
            if any(edges):
                self._resizing = True
                self._resize_dir = edges
                self._resize_start_geo = self.geometry()
                self._resize_start_global = event.globalPosition().toPoint()
                self._drag_origin = None
                event.accept()
                return
            self._drag_origin = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._drag_start = event.globalPosition().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._resizing and self._resize_start_geo is not None and self._resize_start_global is not None:
            dx = event.globalPosition().toPoint().x() - self._resize_start_global.x()
            dy = event.globalPosition().toPoint().y() - self._resize_start_global.y()
            left, right, top, bottom = self._resize_dir
            geo = QRect(self._resize_start_geo)
            if left:
                geo.setLeft(geo.left() + dx)
            if right:
                geo.setRight(geo.right() + dx)
            if top:
                geo.setTop(geo.top() + dy)
            if bottom:
                geo.setBottom(geo.bottom() + dy)
            if geo.width() < 520:
                if left:
                    geo.setLeft(geo.right() - 520 + 1)
                else:
                    geo.setRight(geo.left() + 520 - 1)
            if geo.height() < 140:
                if top:
                    geo.setTop(geo.bottom() - 140 + 1)
                else:
                    geo.setBottom(geo.top() + 140 - 1)
            self.setGeometry(geo)
            event.accept()
            return
        if self._drag_origin is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_origin)
            event.accept()
            return
        self.setCursor(self._cursor_for(self._edges_at(event.position().toPoint())))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._resizing:
            self._resizing = False
            left, right, top, bottom = self._resize_dir
            if top or bottom:
                self._manual_height = True
            self._resize_start_geo = None
            self._resize_start_global = None
            self._save_timer.start(200)
            self._queue_fit()
            self.setCursor(Qt.ArrowCursor)
            event.accept()
            return
        if self._drag_origin is not None:
            self._drag_origin = None
            self._save_timer.start(500)
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._update_compact()
        self._position_jump_button()
        if self._sized:
            self._save_timer.start(600)
    def moveEvent(self, event) -> None:
        if self._sized:
            self._save_timer.start(600)
        super().moveEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._sized:
            self._sized = True
            if not self._manual_height:
                self._queue_fit()
            if self.config.settings.overlay.x < 0 or self.config.settings.overlay.y < 0:
                self._position_default()
        self._ensure_on_screen()

    def _ensure_on_screen(self) -> None:
        screen = QGuiApplication.screenAt(self.pos()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        x = max(geo.left() + 8, min(self.x(), geo.right() - self.width() - 8))
        y = max(geo.top() + 8, min(self.y(), geo.bottom() - self.height() - 8))
        if (x, y) != (self.x(), self.y()):
            self.move(x, y)

    def closeEvent(self, event) -> None:
        event.ignore()
        self.hide()
        self.hidden.emit()

    def _emit_geometry(self) -> None:
        cfg = self.config.settings.overlay
        cfg.x, cfg.y = self.x(), self.y()
        cfg.width = self.width()
        cfg.height = self.height() if self._manual_height else 0
        self.config.save()
        self.geometry_changed.emit(self.x(), self.y(), self.width())

    def _hide_clicked(self) -> None:
        self.hide()
        self.hidden.emit()

    def flash(self, message: str, level: str = "info", ms: int = 3500) -> None:
        self.hint.setText(message)
        self.hint.setStyleSheet(
            "color: %s; font-size: 10px;"
            % {"info": "#8b93a7", "warn": "#f0a020", "error": "#ff9a9e"}.get(level, "#8b93a7")
        )
        self._hint_timer.start(ms)

    def _restore_hint(self) -> None:
        self.hint.setText(self._default_hint)
        self.hint.setStyleSheet("color: rgba(230,232,238,0.3); font-size: 10px;")

    # ------------------------------------------------------------------ 菜单
    def contextMenuEvent(self, event) -> None:
        self._show_menu()

    def _show_menu(self) -> None:
        menu = QMenu(self)
        menu.addAction("打开工作台", self.workbench_requested.emit)
        menu.addAction("五十音图（Ctrl+Alt+K）", self.kana_requested.emit)
        menu.addAction("设置…", self.settings_requested.emit)
        menu.addSeparator()
        mode_menu = menu.addMenu("字幕模式")
        mode_menu.addAction("专注 · 只看译文", lambda: self._set_mode_and_save("focus"))
        mode_menu.addAction("双语 · 原文小译文大", lambda: self._set_mode_and_save("bilingual"))
        mode_menu.addAction("学习 · 原文译文对照", lambda: self._set_mode_and_save("study"))
        menu.addAction("放大字号", lambda: self._nudge_font(1))
        menu.addAction("缩小字号", lambda: self._nudge_font(-1))
        menu.addAction("增加不透明度", lambda: self._nudge_opacity(0.04))
        menu.addAction("降低不透明度", lambda: self._nudge_opacity(-0.04))
        menu.addSeparator()
        toolbar_action = menu.addAction("显示工具栏")
        toolbar_action.setCheckable(True)
        toolbar_action.setChecked(self.config.settings.overlay.show_toolbar)
        toolbar_action.triggered.connect(self._set_toolbar_visible)
        auto_hide_action = menu.addAction("自动隐藏工具栏")
        auto_hide_action.setCheckable(True)
        auto_hide_action.setChecked(self.config.settings.overlay.auto_hide_toolbar)
        auto_hide_action.triggered.connect(self._set_toolbar_auto_hide)
        position_menu = menu.addMenu("窗口位置")
        position_menu.addAction("屏幕底部居中", lambda: self._move_preset("bottom"))
        position_menu.addAction("屏幕顶部居中", lambda: self._move_preset("top"))
        position_menu.addAction("鼠标所在屏幕底部", lambda: self._move_preset("cursor"))
        screens_menu = position_menu.addMenu("移到指定屏幕")
        for index, screen in enumerate(QGuiApplication.screens()):
            name = screen.name() or f"屏幕 {index + 1}"
            screens_menu.addAction(
                f"{name} · 底部",
                lambda s=screen: self._move_to_screen(s),
            )
        height_action = menu.addAction("自动高度")
        height_action.setCheckable(True)
        height_action.setChecked(not self._manual_height)
        height_action.triggered.connect(self._set_auto_height)
        menu.addAction("重置为默认大小", self._reset_size)
        menu.addSeparator()
        click_action = menu.addAction("鼠标穿透（Ctrl+Alt+T）")
        click_action.setCheckable(True)
        click_action.setChecked(self._click_through)
        click_action.triggered.connect(self.toggle_click_through)
        menu.addAction("隐藏字幕窗（Ctrl+Alt+H）", self._hide_clicked)
        menu.addSeparator()
        menu.addAction("退出 RoseSI", self.quit_requested.emit)
        menu.exec(self.cursor().pos())

    def _set_mode_and_save(self, mode: str) -> None:
        mode = {"both": "bilingual", "dst": "focus", "src": "study"}.get(mode, mode)
        self.set_mode(mode)
        self.config.settings.overlay.mode = mode
        self.config.save()
        self.mode_changed.emit(mode)

    def _nudge_font(self, delta: int) -> None:
        size = max(14, min(40, int(self.config.settings.overlay.font_size) + delta))
        self.config.settings.overlay.font_size = size
        self.config.save()
        self.apply_settings()
        self.font_size_changed.emit(size)

    def _nudge_opacity(self, delta: float) -> None:
        value = max(0.25, min(1.0, float(self.config.settings.overlay.opacity) + delta))
        self.config.settings.overlay.opacity = round(value, 2)
        self.config.save()
        self.update()
        self.opacity_changed.emit(round(value, 2))

    def _set_auto_height(self, enabled: bool) -> None:
        self._manual_height = not enabled
        self.config.settings.overlay.height = 0 if enabled else self.height()
        if enabled:
            self._queue_fit()
        self.config.save()

    def _set_toolbar_visible(self, visible: bool) -> None:
        self.config.settings.overlay.show_toolbar = bool(visible)
        self._bar.setVisible(bool(visible))
        self.config.save()
        self._queue_fit()

    def _set_toolbar_auto_hide(self, enabled: bool) -> None:
        self.config.settings.overlay.auto_hide_toolbar = bool(enabled)
        self.config.save()
        if enabled:
            self._schedule_bar_hide()
        else:
            self._bar_hide_timer.stop()
            self._bar_effect.setOpacity(0.55)

    def _move_to_screen(self, screen) -> None:
        if screen is None:
            return
        geo = screen.availableGeometry()
        x = geo.x() + (geo.width() - self.width()) // 2
        y = geo.bottom() - self.height() - 72
        self.move(max(geo.x() + 8, x), max(geo.y() + 8, y))
        self._save_timer.start(200)
        self._position_jump_button()

    def _move_preset(self, preset: str) -> None:
        screen = (
            QGuiApplication.screenAt(QCursor.pos())
            if preset == "cursor"
            else (QGuiApplication.screenAt(self.pos()) or QGuiApplication.primaryScreen())
        )
        if screen is None:
            return
        geo = screen.availableGeometry()
        x = geo.x() + (geo.width() - self.width()) // 2
        if preset == "top":
            y = geo.y() + 24
        else:
            y = geo.bottom() - self.height() - 72
        self.move(max(geo.x() + 8, x), max(geo.y() + 8, y))
        self._save_timer.start(200)
        self._position_jump_button()

    def _reset_size(self) -> None:
        self._manual_height = False
        self.config.settings.overlay.width = 900
        self.config.settings.overlay.height = 0
        self.resize(900, self.height())
        self._queue_fit()
        self.config.save()

    # ------------------------------------------------------------------ 绘制
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        alpha = int(255 * max(0.2, min(1.0, self.config.settings.overlay.opacity)))
        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0.0, QColor(23, 16, 36, alpha))
        gradient.setColorAt(0.55, QColor(16, 11, 26, alpha))
        gradient.setColorAt(1.0, QColor(10, 7, 18, alpha))
        painter.setBrush(gradient)
        painter.setPen(QPen(QColor(255, 190, 220, 20), 1))
        painter.drawRoundedRect(rect, 13, 13)

        if self._state == "running":
            accent = QLinearGradient(0, 0, self.width(), 0)
            accent.setColorAt(0.0, QColor(255, 111, 169, 0))
            accent.setColorAt(0.25, QColor(255, 111, 169, 135))
            accent.setColorAt(0.75, QColor(139, 123, 255, 110))
            accent.setColorAt(1.0, QColor(139, 123, 255, 0))
            painter.setPen(QPen(QBrush(accent), 1.4))
            painter.drawLine(18, 1, self.width() - 18, 1)

        # 右下角缩放提示
        painter.setPen(QPen(QColor(255, 255, 255, 58), 1))
        base_x, base_y = self.width() - 8, self.height() - 8
        for offset in (3, 6, 9):
            painter.drawLine(base_x - offset, base_y, base_x, base_y - offset)
