"""通用 UI 组件。"""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractButton,
    QDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .theme import COLORS


class Card(QFrame):
    def __init__(self, title: str | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(18, 16, 18, 16)
        self._outer.setSpacing(12)
        self.header_layout: QHBoxLayout | None = None
        self.title_label: QLabel | None = None
        if title is not None:
            self.header_layout = QHBoxLayout()
            self.header_layout.setContentsMargins(0, 0, 0, 0)
            self.title_label = QLabel(title)
            self.title_label.setObjectName("CardTitle")
            self.header_layout.addWidget(self.title_label)
            self.header_layout.addStretch(1)
            self._outer.addLayout(self.header_layout)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(10)
        self._outer.addLayout(self.body)

    def add_widget(self, widget: QWidget) -> None:
        self.body.addWidget(widget)

    def add_layout(self, layout) -> None:
        self.body.addLayout(layout)

    def add_header_action(self, widget: QWidget) -> None:
        if self.header_layout is not None:
            self.header_layout.addWidget(widget)


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        text_box = QVBoxLayout()
        text_box.setSpacing(3)
        self.title = QLabel(title)
        self.title.setObjectName("PageTitle")
        text_box.addWidget(self.title)
        self.subtitle = QLabel(subtitle)
        self.subtitle.setObjectName("PageSub")
        self.subtitle.setWordWrap(True)
        self.subtitle.setVisible(bool(subtitle))
        text_box.addWidget(self.subtitle)
        layout.addLayout(text_box)
        layout.addStretch(1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        layout.addLayout(self.actions)

    def add_action(self, widget: QWidget) -> None:
        self.actions.addWidget(widget)


class Switch(QAbstractButton):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(44, 24)
        self.setCursor(Qt.PointingHandCursor)
        self._hover = False

    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        track = QRectF(0, 1, 44, 22)
        if self.isChecked():
            color = QColor("#5b95ff") if self._hover else QColor(COLORS["accent"])
        else:
            color = QColor("#353c4a") if self._hover else QColor("#2a2f3a")
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(track, 11, 11)
        knob = 16.0
        x = 44 - knob - 4 if self.isChecked() else 4
        painter.setBrush(QColor("#ffffff"))
        painter.drawEllipse(QRectF(x, 4, knob, knob))


class StatusDot(QWidget):
    def __init__(self, state: str = "idle", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self.setFixedSize(10, 10)

    def set_state(self, state: str) -> None:
        self._state = state
        self.update()

    def paintEvent(self, event) -> None:
        color = {
            "running": COLORS["green"],
            "loading": COLORS["orange"],
            "error": COLORS["red"],
            "stopping": COLORS["orange"],
            "idle": "#5b6375",
        }.get(self._state, COLORS["green"])
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(color))
        painter.drawEllipse(QRectF(1, 1, 8, 8))


class LevelMeter(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._level = 0.0
        self.setFixedSize(38, 18)

    def set_level(self, level: float) -> None:
        self._level = max(0.0, min(1.0, float(level)))
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        bars = 5
        gap = 2.0
        width = (self.width() - gap * (bars - 1)) / bars
        active = int(round(self._level * bars + 0.49))
        for index in range(bars):
            height = 6 + index * 2.8
            rect = QRectF(index * (width + gap), self.height() - height, width, height)
            painter.setBrush(
                QColor(COLORS["green"]) if index < active else QColor("#2c3340")
            )
            painter.drawRoundedRect(rect, 1.5, 1.5)


class Tag(QLabel):
    def __init__(self, text: str, kind: str = "normal", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setObjectName(
            {"normal": "Tag", "good": "GoodTag", "warn": "WarnTag"}.get(kind, "Tag")
        )
        self.setAlignment(Qt.AlignCenter)


class StatRow(QWidget):
    def __init__(self, label: str, value: str = "—", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 7, 0, 7)
        layout.setSpacing(12)
        self.label = QLabel(label)
        self.label.setObjectName("Dim")
        self.value = QLabel(value)
        self.value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.value.setStyleSheet("font-weight: 600;")
        layout.addWidget(self.label)
        layout.addStretch(1)
        layout.addWidget(self.value)
        self._line = QFrame()
        self._line.setObjectName("Divider")
        self._line.setFixedHeight(1)

    def set_value(self, text: str, tone: str = "") -> None:
        self.value.setText(text)
        color = {
            "good": COLORS["green"],
            "warn": COLORS["orange"],
            "bad": COLORS["red"],
            "": COLORS["text"],
        }.get(tone, COLORS["text"])
        self.value.setStyleSheet(f"color: {color}; font-weight: 600;")


class FormRow(QWidget):
    def __init__(
        self,
        label: str,
        control: QWidget,
        hint: str = "",
        label_width: int = 138,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(2)
        self.label = QLabel(label)
        self.label.setMinimumWidth(label_width)
        self.label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        left.addWidget(self.label)
        if hint:
            hint_label = QLabel(hint)
            hint_label.setObjectName("Tiny")
            hint_label.setWordWrap(True)
            hint_label.setMaximumWidth(560)
            left.addWidget(hint_label)
        layout.addLayout(left)
        layout.addStretch(1)
        layout.addWidget(control, 0, Qt.AlignRight | Qt.AlignVCenter)


class Toast(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._label = QLabel("", self)
        self._label.setWordWrap(True)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setContentsMargins(18, 10, 18, 10)
        self._effect = QGraphicsOpacityEffect(self)
        self._label.setGraphicsEffect(self._effect)
        self._effect.setOpacity(0.0)
        self._anim = QPropertyAnimation(self._effect, b"opacity", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)
        parent.installEventFilter(self)
        self.hide()

    def show_message(self, text: str, level: str = "info", ms: int = 3200) -> None:
        colors = {
            "info": ("#23304a", "#cfe0ff", "rgba(79,140,255,0.55)"),
            "warn": ("#332a18", "#ffd08a", "rgba(240,160,32,0.55)"),
            "error": ("#3a1d20", "#ffb3b6", "rgba(229,72,77,0.6)"),
            "success": ("#173026", "#a6f0c6", "rgba(53,194,107,0.55)"),
        }
        bg, fg, border = colors.get(level, colors["info"])
        self._label.setStyleSheet(
            f"background: {bg}; color: {fg}; border: 1px solid {border};"
            " border-radius: 10px; font-size: 12px;"
        )
        self._label.setText(text)
        self._label.adjustSize()
        self._label.setFixedWidth(min(560, max(220, self._label.sizeHint().width() + 8)))
        self._label.adjustSize()
        self.resize(self._label.size())
        self._reposition()
        self.show()
        self.raise_()
        self._effect.setOpacity(0.0)
        self._anim.stop()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()
        self._timer.start(ms)

    def _fade_out(self) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._effect.opacity())
        self._anim.setEndValue(0.0)
        self._anim.finished.connect(self._hide_once)
        self._anim.start()

    def _hide_once(self) -> None:
        try:
            self._anim.finished.disconnect(self._hide_once)
        except Exception:
            pass
        if self._effect.opacity() <= 0.01:
            self.hide()

    def _reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        x = (parent.width() - self.width()) // 2
        y = parent.height() - self.height() - 28
        self.move(max(12, x), max(12, y))

    def eventFilter(self, obj, event) -> bool:
        if obj is self.parentWidget() and event.type() == QEvent.Resize:
            self._reposition()
        return super().eventFilter(obj, event)


class IconButton(QPushButton):
    def __init__(
        self, glyph: str, tooltip: str = "", size: int = 30, parent: QWidget | None = None
    ) -> None:
        super().__init__(glyph, parent)
        self.setObjectName("IconButton")
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tooltip)
        self.setStyleSheet(
            "QPushButton { background: transparent; border: none; border-radius: 7px;"
            " color: #aeb6c6; font-size: 15px; }"
            "QPushButton:hover { background: rgba(255,255,255,0.07); color: #ffffff; }"
            "QPushButton:checked { background: rgba(79,140,255,0.2); color: #7ea8ff; }"
        )


class Dialog(QDialog):
    def __init__(self, title: str, parent: QWidget | None = None, width: int = 460) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(width)
        self.setModal(True)
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(14)
        self.title = QLabel(title)
        self.title.setStyleSheet("font-size: 16px; font-weight: 600;")
        root.addWidget(self.title)
        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        root.addLayout(self.body)
        root.addStretch(1)
        footer = QHBoxLayout()
        footer.addStretch(1)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setProperty("variant", "ghost")
        self.cancel_button.clicked.connect(self.reject)
        self.ok_button = QPushButton("确定")
        self.ok_button.setProperty("variant", "primary")
        self.ok_button.clicked.connect(self.accept)
        footer.addWidget(self.cancel_button)
        footer.addWidget(self.ok_button)
        root.addLayout(footer)

    def add_widget(self, widget: QWidget) -> None:
        self.body.addWidget(widget)

    def add_layout(self, layout) -> None:
        self.body.addLayout(layout)


def hline() -> QFrame:
    line = QFrame()
    line.setObjectName("Divider")
    line.setFixedHeight(1)
    return line


def button(text: str, variant: str = "", tooltip: str = "") -> QPushButton:
    btn = QPushButton(text)
    if variant:
        btn.setProperty("variant", variant)
    if tooltip:
        btn.setToolTip(tooltip)
    btn.setCursor(Qt.PointingHandCursor)
    return btn


def label(text: str, object_name: str = "") -> QLabel:
    lbl = QLabel(text)
    if object_name:
        lbl.setObjectName(object_name)
    return lbl
