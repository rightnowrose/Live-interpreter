"""工作台 · 导出 / 下载同传文件。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ... import exporter, paths
from ...db import Database
from ..widgets import Card, PageHeader, Switch, button

if TYPE_CHECKING:
    from ...pipeline import Pipeline


class ExportPage(QWidget):
    notify = Signal(str, str)

    def __init__(
        self, pipeline: "Pipeline", db: Database, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.pipeline = pipeline
        self.db = db
        self._sessions = []
        self._build()
        self.reload()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)
        header = PageHeader("导出同传文件", "把本次或历史会话保存为 SRT / TXT / Markdown / JSON / CSV / Excel")
        open_dir_btn = button("打开导出文件夹", "ghost")
        open_dir_btn.clicked.connect(self._open_exports_dir)
        header.add_action(open_dir_btn)
        root.addWidget(header)

        card = Card("新建导出")
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(QLabel("会话"))
        self.session_combo = QComboBox()
        self.session_combo.setMinimumWidth(340)
        self.session_combo.currentIndexChanged.connect(lambda _: self._update_summary())
        row.addWidget(self.session_combo, 1)
        refresh = button("刷新", "ghost")
        refresh.clicked.connect(self.reload)
        row.addWidget(refresh)
        card.add_layout(row)

        row2 = QHBoxLayout()
        row2.setSpacing(8)
        row2.addWidget(QLabel("格式"))
        self.format_combo = QComboBox()
        for key, name in exporter.FORMATS.items():
            self.format_combo.addItem(name, key)
        self.format_combo.currentIndexChanged.connect(self._update_path_suffix)
        row2.addWidget(self.format_combo)
        row2.addSpacing(14)
        row2.addWidget(QLabel("内容"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("原文 + 译文", "both")
        self.mode_combo.addItem("仅译文", "dst")
        self.mode_combo.addItem("仅原文", "src")
        row2.addWidget(self.mode_combo)
        row2.addSpacing(14)
        self.meta_switch = Switch()
        self.meta_switch.setChecked(True)
        row2.addWidget(self.meta_switch)
        row2.addWidget(QLabel("包含元数据"))
        row2.addStretch(1)
        card.add_layout(row2)

        row3 = QHBoxLayout()
        row3.setSpacing(8)
        row3.addWidget(QLabel("保存到"))
        self.path_edit = QLineEdit()
        self.path_edit.setMinimumWidth(420)
        row3.addWidget(self.path_edit, 1)
        browse = button("浏览", "soft")
        browse.clicked.connect(self._browse)
        row3.addWidget(browse)
        card.add_layout(row3)

        self.summary = QLabel("")
        self.summary.setObjectName("Dim")
        self.summary.setWordWrap(True)
        card.add_widget(self.summary)

        action_row = QHBoxLayout()
        action_row.addStretch(1)
        self.export_btn = button("导出文件", "primary")
        self.export_btn.setMinimumWidth(120)
        self.export_btn.clicked.connect(self._export)
        action_row.addWidget(self.export_btn)
        card.add_layout(action_row)
        root.addWidget(card)

        recent_card = Card("最近导出")
        self.recent_table = QTableWidget(0, 3)
        self.recent_table.setHorizontalHeaderLabels(["文件", "大小", "时间"])
        self.recent_table.verticalHeader().setVisible(False)
        self.recent_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.recent_table.setSelectionBehavior(QTableWidget.SelectRows)
        hh = self.recent_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.recent_table.doubleClicked.connect(lambda _: self._open_selected_recent())
        self.recent_table.setMinimumHeight(200)
        recent_card.add_widget(self.recent_table)
        recent_buttons = QHBoxLayout()
        recent_buttons.addStretch(1)
        open_selected = button("打开选中文件", "soft")
        open_selected.clicked.connect(self._open_selected_recent)
        recent_buttons.addWidget(open_selected)
        recent_card.add_layout(recent_buttons)
        root.addWidget(recent_card, 1)

        self._refresh_recent()

    # ------------------------------------------------------------------
    def reload(self) -> None:
        current = self.session_combo.currentData()
        self._sessions = self.db.list_sessions(limit=300)
        self.session_combo.blockSignals(True)
        self.session_combo.clear()
        for session in self._sessions:
            label = (
                f"{session.started_at.replace('T', ' ')[:16]} · {session.title} · "
                f"{session.segment_count} 段"
            )
            self.session_combo.addItem(label, session.id)
        if current:
            index = self.session_combo.findData(current)
            if index >= 0:
                self.session_combo.setCurrentIndex(index)
        self.session_combo.blockSignals(False)
        self._update_summary()
        self._refresh_recent()

    def _current_session(self):
        session_id = self.session_combo.currentData()
        if not session_id:
            return None
        for session in self._sessions:
            if session.id == session_id:
                return session
        return self.db.get_session(session_id)

    def _update_summary(self) -> None:
        session = self._current_session()
        if session is None:
            self.summary.setText("还没有会话记录。先开始一次同传。")
            self.export_btn.setEnabled(False)
            return
        self.export_btn.setEnabled(True)
        fmt = self.format_combo.currentData()
        suggested = paths.exports_dir() / exporter.suggest_filename(session, fmt)
        self.path_edit.setText(str(suggested))
        self.summary.setText(
            f"{session.segment_count} 个片段 · 时长 {int(session.duration_s // 60)} 分 "
            f"{int(session.duration_s % 60)} 秒 · 平均延迟 {session.avg_latency_ms:.0f} ms\n"
            f"{session.audio_source} · {session.asr_model}"
        )

    def _update_path_suffix(self) -> None:
        session = self._current_session()
        if session is None:
            return
        fmt = self.format_combo.currentData()
        base = self.path_edit.text().strip()
        if not base:
            base = str(paths.exports_dir() / exporter.suggest_filename(session, fmt))
        else:
            base = str(Path(base).with_suffix("." + fmt))
        self.path_edit.setText(base)

    def _browse(self) -> None:
        fmt = self.format_combo.currentData()
        path, _ = QFileDialog.getSaveFileName(
            self, "选择保存位置", self.path_edit.text(), f"{exporter.FORMATS[fmt]} (*.{fmt})"
        )
        if path:
            if not path.lower().endswith("." + fmt):
                path += "." + fmt
            self.path_edit.setText(path)

    def _export(self) -> None:
        session = self._current_session()
        if session is None:
            return
        path = self.path_edit.text().strip()
        if not path:
            self._browse()
            path = self.path_edit.text().strip()
        if not path:
            return
        fmt = self.format_combo.currentData()
        if not path.lower().endswith("." + fmt):
            path += "." + fmt
        segments = self.db.session_segments(session.id)
        try:
            exporter.export_session(
                session,
                segments,
                path,
                fmt,
                self.mode_combo.currentData(),
                include_meta=self.meta_switch.isChecked(),
            )
        except Exception as exc:
            self.notify.emit(f"导出失败：{exc}", "error")
            return
        self._refresh_recent()
        self.notify.emit(f"已导出：{path}", "success")
        self._ask_open(path)

    def _ask_open(self, path: str) -> None:
        from PySide6.QtWidgets import QMessageBox

        box = QMessageBox(self)
        box.setWindowTitle("导出完成")
        box.setText(f"文件已保存：\n{path}")
        open_btn = box.addButton("打开文件", QMessageBox.AcceptRole)
        folder_btn = box.addButton("打开文件夹", QMessageBox.ActionRole)
        box.addButton("关闭", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is open_btn:
            os.startfile(path)
        elif box.clickedButton() is folder_btn:
            os.startfile(str(Path(path).parent))

    def _refresh_recent(self) -> None:
        folder = paths.exports_dir()
        files = sorted(
            [p for p in folder.glob("*") if p.is_file()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:20]
        self.recent_table.setRowCount(0)
        for row, path in enumerate(files):
            self.recent_table.insertRow(row)
            stat = path.stat()
            name = QTableWidgetItem(path.name)
            name.setData(Qt.UserRole, str(path))
            size = QTableWidgetItem(f"{stat.st_size / 1024:.1f} KB")
            import datetime

            when = datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%m-%d %H:%M")
            time_item = QTableWidgetItem(when)
            self.recent_table.setItem(row, 0, name)
            self.recent_table.setItem(row, 1, size)
            self.recent_table.setItem(row, 2, time_item)
            self.recent_table.setRowHeight(row, 34)

    def _open_selected_recent(self) -> None:
        row = self.recent_table.currentRow()
        if row < 0:
            return
        item = self.recent_table.item(row, 0)
        if item:
            os.startfile(item.data(Qt.UserRole))

    def _open_exports_dir(self) -> None:
        os.startfile(paths.exports_dir())
