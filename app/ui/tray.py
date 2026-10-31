"""系统托盘。"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .theme import app_icon


class TrayIcon(QSystemTrayIcon):
    toggle_overlay_requested = Signal()
    workbench_requested = Signal()
    kana_requested = Signal()
    toggle_session_requested = Signal()
    click_through_toggled = Signal(bool)
    quit_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(app_icon(), parent)
        self.setToolTip("RoseSI · 本地同传")
        self._menu = QMenu()
        self._show_action = self._menu.addAction("显示 / 隐藏字幕窗")
        self._show_action.triggered.connect(self.toggle_overlay_requested)
        self._workbench_action = self._menu.addAction("打开工作台")
        self._workbench_action.triggered.connect(self.workbench_requested)
        self._kana_action = self._menu.addAction("五十音图")
        self._kana_action.triggered.connect(self.kana_requested)
        self._menu.addSeparator()
        self._session_action = self._menu.addAction("开始同传")
        self._session_action.triggered.connect(self.toggle_session_requested)
        self._click_action = self._menu.addAction("鼠标穿透")
        self._click_action.setCheckable(True)
        self._click_action.toggled.connect(self.click_through_toggled)
        self._menu.addSeparator()
        self._quit_action = self._menu.addAction("退出")
        self._quit_action.triggered.connect(self.quit_requested)
        self.setContextMenu(self._menu)
        self.activated.connect(self._on_activated)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.DoubleClick:
            self.workbench_requested.emit()

    def set_state(self, state: str) -> None:
        if state in ("running", "loading", "stopping"):
            self._session_action.setText("停止同传" if state == "running" else "取消启动")
        else:
            self._session_action.setText("开始同传")
        self.setToolTip(
            {
                "idle": "RoseSI · 待机",
                "loading": "RoseSI · 准备中",
                "running": "RoseSI · 同传中",
                "stopping": "RoseSI · 正在结束",
                "error": "RoseSI · 出错",
            }.get(state, "RoseSI")
        )

    def set_click_through(self, enabled: bool) -> None:
        self._click_action.blockSignals(True)
        self._click_action.setChecked(enabled)
        self._click_action.blockSignals(False)
