"""工作台 · 会话记录。"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ... import exporter, paths
from ...config import language_name, target_language_name
from ...db import Database
from ...models import Session
from ..widgets import Card, Dialog, PageHeader, button
from .common import ask_confirm

if TYPE_CHECKING:
    from ...pipeline import Pipeline


def _fmt_duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    if seconds >= 3600:
        return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"
    if seconds >= 60:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds}s"


class SessionDetailDialog(Dialog):
    def __init__(self, db: Database, session: Session, parent: QWidget | None = None) -> None:
        super().__init__(f"会话详情 · {session.title}", parent, width=940)
        self.db = db
        self.session = session
        self.segments = db.session_segments(session.id)
        self.setMinimumHeight(560)

        info = QLabel(
            f"开始：{session.started_at.replace('T', ' ')}    时长：{_fmt_duration(session.duration_s)}    "
            f"语言：{language_name(session.source_lang)} → {target_language_name(session.target_lang)}    "
            f"片段：{session.segment_count}    平均延迟：{session.avg_latency_ms:.0f} ms\n"
            f"音频源：{session.audio_source}    模型：{session.asr_model}"
        )
        info.setObjectName("Dim")
        info.setWordWrap(True)
        self.add_widget(info)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["#", "原文", "译文", "延迟", "语料库"])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        for row, seg in enumerate(self.segments):
            self.table.insertRow(row)
            values = [
                str(seg.seq),
                seg.src,
                seg.dst,
                f"{seg.total_ms:.0f} ms" if seg.total_ms else "—",
                "是" if seg.via_tm else "",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col in (0, 3, 4):
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, col, item)
            self.table.setRowHeight(row, 34)
        self.table.setMinimumHeight(330)
        self.add_widget(self.table)

        actions = QHBoxLayout()
        self.format = QComboBox()
        for key, name in exporter.FORMATS.items():
            self.format.addItem(name, key)
        self.mode = QComboBox()
        self.mode.addItem("双语", "both")
        self.mode.addItem("仅译文", "dst")
        self.mode.addItem("仅原文", "src")
        self.export_btn = button("导出此会话", "primary")
        self.export_btn.clicked.connect(self._export)
        actions.addWidget(QLabel("格式"))
        actions.addWidget(self.format)
        actions.addWidget(QLabel("内容"))
        actions.addWidget(self.mode)
        actions.addStretch(1)
        actions.addWidget(self.export_btn)
        self.add_layout(actions)
        self.cancel_button.setText("关闭")
        self.ok_button.setVisible(False)

    def _export(self) -> None:
        fmt = self.format.currentData()
        mode = self.mode.currentData()
        suggested = paths.exports_dir() / exporter.suggest_filename(self.session, fmt)
        path, _ = QFileDialog.getSaveFileName(
            self, "导出同传记录", str(suggested), f"{exporter.FORMATS[fmt]} (*.{fmt})"
        )
        if not path:
            return
        if not path.lower().endswith("." + fmt):
            path += "." + fmt
        try:
            exporter.export_session(self.session, self.segments, path, fmt, mode)
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(self, "导出失败", str(exc))
            return
        from PySide6.QtWidgets import QMessageBox

        box = QMessageBox(self)
        box.setWindowTitle("导出完成")
        box.setText(f"已保存到：\n{path}")
        open_btn = box.addButton("打开文件", QMessageBox.AcceptRole)
        box.addButton("关闭", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is open_btn:
            os.startfile(path)


class HistoryPage(QWidget):
    changed = Signal()
    notify = Signal(str, str)

    def __init__(
        self, pipeline: "Pipeline", db: Database, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.pipeline = pipeline
        self.db = db
        self._sessions: list[Session] = []
        self._build()
        self.reload()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)
        header = PageHeader("会话记录", "每次同传自动落盘；可回看、搜索并导出为字幕或文本")
        refresh = button("刷新", "soft")
        refresh.clicked.connect(self.reload)
        clear = button("清理全部", "ghost")
        clear.clicked.connect(self._clear)
        header.add_action(refresh)
        header.add_action(clear)
        root.addWidget(header)

        card = Card("历史会话")
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["开始时间", "时长", "语言", "片段", "平均延迟", "状态", "操作"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.doubleClicked.connect(lambda _: self._view_selected())
        card.add_widget(self.table)
        self.footer = QLabel("")
        self.footer.setObjectName("Dim")
        card.add_widget(self.footer)
        root.addWidget(card, 1)

    def reload(self) -> None:
        self._sessions = self.db.list_sessions(limit=300)
        self.table.setRowCount(0)
        for row, session in enumerate(self._sessions):
            self.table.insertRow(row)
            values = [
                session.started_at.replace("T", " "),
                _fmt_duration(session.duration_s),
                f"{language_name(session.source_lang)} → {target_language_name(session.target_lang)}",
                str(session.segment_count),
                f"{session.avg_latency_ms:.0f} ms" if session.avg_latency_ms else "—",
                {"done": "完成", "running": "进行中", "aborted": "中断"}.get(
                    session.status, session.status
                ),
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col in (1, 3, 4, 5):
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, col, item)
            actions = QWidget()
            layout = QHBoxLayout(actions)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(4)
            view_btn = button("查看", "ghost")
            view_btn.setStyleSheet("padding: 2px 8px; font-size: 11px;")
            view_btn.clicked.connect(lambda _=False, s=session: self._view(s))
            export_btn = button("导出", "ghost")
            export_btn.setStyleSheet("padding: 2px 8px; font-size: 11px;")
            export_btn.clicked.connect(lambda _=False, s=session: self._export(s))
            layout.addWidget(view_btn)
            layout.addWidget(export_btn)
            self.table.setCellWidget(row, 6, actions)
            self.table.setRowHeight(row, 40)
        self.footer.setText(f"共 {len(self._sessions)} 条会话")

    def _selected(self) -> Session | None:
        row = self.table.currentRow()
        if 0 <= row < len(self._sessions):
            return self._sessions[row]
        return None

    def _view_selected(self) -> None:
        session = self._selected()
        if session:
            self._view(session)

    def _view(self, session: Session) -> None:
        dialog = SessionDetailDialog(self.db, session, self)
        dialog.exec()

    def _export(self, session: Session) -> None:
        suggested = paths.exports_dir() / exporter.suggest_filename(session, "srt")
        path, selected = QFileDialog.getSaveFileName(
            self,
            "导出会话",
            str(suggested),
            "SRT (*.srt);;文本 (*.txt);;Markdown (*.md);;JSON (*.json);;CSV (*.csv);;Excel (*.xlsx)",
        )
        if not path:
            return
        fmt = path.rsplit(".", 1)[-1].lower() if "." in path else "srt"
        if fmt not in exporter.FORMATS:
            fmt = "srt"
            path += ".srt"
        try:
            exporter.export_session(
                session, self.db.session_segments(session.id), path, fmt, "both"
            )
            self.notify.emit(f"已导出到 {path}", "success")
        except Exception as exc:
            self.notify.emit(f"导出失败：{exc}", "error")

    def _clear(self) -> None:
        active = self.pipeline.session_id
        message = "确定删除全部历史会话与片段？此操作不可撤销。"
        if active:
            message += "\n\n当前正在进行的会话会保留。"
        if not ask_confirm(self, "清理会话", message):
            return
        self.db.clear_sessions(keep_id=active or None)
        self.reload()
        self.changed.emit()
