"""工作台 · 语料库（翻译记忆）与候选审核。"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ... import exporter, importers
from ...candidates import auto_approvable
from ...config import ConfigStore, target_language_name
from ...db import Database
from ...models import TMCandidate
from ...reviewer import AIReviewer
from ..widgets import Card, Dialog, PageHeader, Switch, button
from .common import ask_confirm

if TYPE_CHECKING:
    from ...pipeline import Pipeline


class TMDialog(Dialog):
    def __init__(self, src: str = "", dst: str = "", parent: QWidget | None = None) -> None:
        super().__init__("添加语料", parent, width=520)
        self.src = QLineEdit(src)
        self.src.setPlaceholderText("原文整句")
        self.dst = QLineEdit(dst)
        self.dst.setPlaceholderText("参考译文")
        self.add_widget(self._field("原文", self.src))
        self.add_widget(self._field("译文", self.dst))
        self.src.setFocus()

    def _field(self, text: str, widget: QWidget) -> QWidget:
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        label = QLabel(text)
        label.setObjectName("Dim")
        layout.addWidget(label)
        layout.addWidget(widget)
        return wrap

    def accept(self) -> None:
        if not self.src.text().strip() or not self.dst.text().strip():
            (self.src if not self.src.text().strip() else self.dst).setFocus()
            return
        super().accept()


class ReviewThread(QThread):
    progress = Signal(int, int)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, reviewer: AIReviewer, candidates: list[TMCandidate], parent=None) -> None:
        super().__init__(parent)
        self.reviewer = reviewer
        self.candidates = candidates

    def run(self) -> None:
        try:
            results = self.reviewer.review_candidates(
                self.candidates,
                on_progress=lambda done, total: self.progress.emit(int(done), int(total)),
            )
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI
            self.failed.emit(str(exc))
            return
        self.done.emit(results)


class PendingPanel(QWidget):
    changed = Signal()
    notify = Signal(str, str)

    FILTERS = [
        ("全部待审核", "all"),
        ("本次会话", "session"),
        ("高规则分", "high"),
        ("含术语", "terms"),
        ("仅出现一次", "once"),
        ("低 ASR 置信", "low_asr"),
        ("疑似重复", "duplicate"),
        ("AI 建议通过", "ai_approve"),
        ("AI 需人工", "ai_manual"),
        ("AI 建议拒绝", "ai_reject"),
    ]

    def __init__(
        self, pipeline: "Pipeline", db: Database, config: ConfigStore, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.pipeline = pipeline
        self.db = db
        self.config = config
        self._candidates: dict[int, TMCandidate] = {}
        self._loading = False
        self._thread: ReviewThread | None = None
        self._review_ids: list[int] = []
        self._build()
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(220)
        self._search_timer.timeout.connect(self.reload)
        self.search.textChanged.connect(lambda: self._search_timer.start())
        self.filter.currentIndexChanged.connect(self.reload)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.filter = QComboBox()
        for label, data in self.FILTERS:
            self.filter.addItem(label, data)
        self.filter.setMinimumWidth(150)
        top.addWidget(self.filter)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索候选原文 / 译文…")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(280)
        top.addWidget(self.search)
        top.addStretch(1)
        self.progress_label = QLabel("")
        self.progress_label.setObjectName("Dim")
        top.addWidget(self.progress_label)
        self.ai_btn = button("AI 预审", "soft")
        self.ai_btn.setToolTip("只对选中的候选运行；未选择时处理当前列表")
        self.ai_btn.clicked.connect(self._ai_review)
        top.addWidget(self.ai_btn)
        root.addLayout(top)

        split = QSplitter(Qt.Horizontal)
        split.setChildrenCollapsible(False)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["原文", "译文", "规则分", "次数", "AI 建议", "标记", "时间"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        for col in range(2, 7):
            hh.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._show_detail)
        self.filter.currentIndexChanged.connect(self.reload)
        self.search.textChanged.connect(self.reload)
        split.addWidget(self.table)

        detail = QFrame()
        detail.setObjectName("Panel")
        detail.setMinimumWidth(300)
        detail.setMaximumWidth(390)
        d = QVBoxLayout(detail)
        d.setContentsMargins(14, 12, 14, 12)
        d.setSpacing(8)
        title = QLabel("候选详情")
        title.setStyleSheet("font-weight: 600;")
        d.addWidget(title)
        d.addWidget(QLabel("原文"))
        self.src_view = QTextEdit()
        self.src_view.setFixedHeight(76)
        d.addWidget(self.src_view)
        d.addWidget(QLabel("译文（可编辑）"))
        self.dst_view = QTextEdit()
        self.dst_view.setFixedHeight(88)
        d.addWidget(self.dst_view)
        self.meta = QLabel("—")
        self.meta.setObjectName("Dim")
        self.meta.setWordWrap(True)
        self.meta.setMinimumHeight(52)
        d.addWidget(self.meta)
        self.ai_info = QLabel("")
        self.ai_info.setWordWrap(True)
        self.ai_info.setStyleSheet("color: #8fb0ff;")
        d.addWidget(self.ai_info)
        d.addStretch(1)

        row1 = QHBoxLayout()
        self.save_btn = button("保存修改", "soft")
        self.save_btn.clicked.connect(self._save_selected)
        self.approve_btn = button("通过", "primary")
        self.approve_btn.clicked.connect(self._approve_selected)
        row1.addWidget(self.save_btn)
        row1.addWidget(self.approve_btn)
        d.addLayout(row1)
        row2 = QHBoxLayout()
        self.ai_apply_btn = button("采纳 AI 译文", "ghost")
        self.ai_apply_btn.clicked.connect(self._apply_ai_translation)
        self.reject_btn = button("拒绝", "danger")
        self.reject_btn.clicked.connect(self._reject_selected)
        row2.addWidget(self.ai_apply_btn)
        row2.addWidget(self.reject_btn)
        d.addLayout(row2)
        split.addWidget(detail)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        root.addWidget(split, 1)

        actions = QHBoxLayout()
        self.footer = QLabel("")
        self.footer.setObjectName("Dim")
        actions.addWidget(self.footer)
        actions.addStretch(1)
        batch_ok = button("通过选中", "soft")
        batch_ok.clicked.connect(self._approve_selected)
        batch_no = button("拒绝选中", "danger")
        batch_no.clicked.connect(self._reject_selected)
        adopt = button("采纳 AI 高置信", "ghost")
        adopt.clicked.connect(self._adopt_ai)
        actions.addWidget(batch_ok)
        actions.addWidget(batch_no)
        actions.addWidget(adopt)
        root.addLayout(actions)
        self._set_detail_enabled(False)

    def _set_detail_enabled(self, enabled: bool) -> None:
        for widget in (
            self.save_btn,
            self.approve_btn,
            self.reject_btn,
            self.ai_apply_btn,
            self.src_view,
            self.dst_view,
        ):
            widget.setEnabled(enabled)

    def _selected(self) -> list[TMCandidate]:
        ids = set()
        for index in self.table.selectedIndexes():
            item = self.table.item(index.row(), 0)
            if item is not None:
                ids.add(item.data(Qt.UserRole))
        return [self._candidates[i] for i in sorted(ids) if i in self._candidates]

    def _current(self) -> TMCandidate | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return self._candidates.get(item.data(Qt.UserRole)) if item else None

    def _show_detail(self) -> None:
        candidate = self._current()
        if not candidate:
            self._set_detail_enabled(False)
            self.src_view.setPlainText("")
            self.dst_view.setPlainText("")
            self.meta.setText("—")
            self.ai_info.setText("")
            return
        self._set_detail_enabled(True)
        self.src_view.setPlainText(candidate.src)
        self.dst_view.setPlainText(candidate.dst)
        flags = "、".join(candidate.flags) if candidate.flags else "无"
        terms = "、".join(
            f"{item.get('src', '')}→{item.get('dst', '')}" for item in candidate.terms
        ) or "无"
        self.meta.setText(
            f"规则分 {candidate.quality:.2f} · 出现 {candidate.occurrences} 次 · "
            f"{candidate.duration_s:.1f}s · 标记：{flags} · 术语：{terms}\n"
            f"{candidate.mt_model or '—'} · {candidate.asr_model or '—'}"
        )
        if candidate.ai_state == "done":
            issues = "、".join(candidate.ai_issues) or "无"
            self.ai_info.setText(
                f"AI：{candidate.ai_label} · {candidate.ai_score or 0:.2f}\n"
                f"{candidate.ai_reason or '—'}\n问题：{issues}"
            )
        else:
            self.ai_info.setText(f"AI：{candidate.ai_label}")
        self.ai_apply_btn.setEnabled(bool(candidate.ai_suggested_dst))

    def reload(self) -> None:
        pending = self.db.list_candidates(status="pending", query=self.search.text(), limit=800)
        mode = self.filter.currentData() or "all"
        session_id = getattr(self.pipeline, "_session_id", "") or getattr(
            self.pipeline, "session_id", ""
        )
        if mode == "session":
            pending = [c for c in pending if session_id and c.session_id == session_id]
        elif mode == "high":
            pending = [c for c in pending if c.quality >= 0.85]
        elif mode == "terms":
            pending = [c for c in pending if c.terms]
        elif mode == "once":
            pending = [c for c in pending if c.occurrences <= 1]
        elif mode == "low_asr":
            pending = [c for c in pending if {"low_asr", "asr_unscored"} & set(c.flags)]
        elif mode == "duplicate":
            pending = [c for c in pending if "duplicate" in c.flags]
        elif mode == "ai_approve":
            pending = [c for c in pending if c.ai_decision == "approve"]
        elif mode == "ai_manual":
            pending = [c for c in pending if c.ai_decision == "needs_human"]
        elif mode == "ai_reject":
            pending = [c for c in pending if c.ai_decision == "reject"]

        current = self._current()
        current_id = current.id if current else None
        self._loading = True
        self._candidates = {c.id: c for c in pending}
        self.table.setRowCount(0)
        for row, candidate in enumerate(pending):
            self.table.insertRow(row)
            src = QTableWidgetItem(candidate.src)
            src.setData(Qt.UserRole, candidate.id)
            src.setToolTip(candidate.src)
            dst = QTableWidgetItem(candidate.dst)
            dst.setToolTip(candidate.dst)
            src.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            dst.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            quality = QTableWidgetItem(f"{candidate.quality:.2f}")
            quality.setTextAlignment(Qt.AlignCenter)
            times = QTableWidgetItem(str(candidate.occurrences))
            times.setTextAlignment(Qt.AlignCenter)
            ai = QTableWidgetItem(candidate.ai_label)
            flags = QTableWidgetItem("、".join(candidate.flags[:3]))
            when = QTableWidgetItem(candidate.last_seen_at.replace("T", " ")[:16])
            for col, item in enumerate((src, dst, quality, times, ai, flags, when)):
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self.table.setItem(row, col, item)
            if candidate.ai_decision == "approve":
                ai.setForeground(Qt.GlobalColor.green)
            elif candidate.ai_decision == "reject":
                ai.setForeground(Qt.GlobalColor.red)
            if candidate.quality < 0.7:
                quality.setForeground(Qt.GlobalColor.yellow)
            self.table.setRowHeight(row, 36)
        self._loading = False
        total = len(pending)
        self.footer.setText(f"显示 {total} 条待审核")
        self._refresh_buttons()
        if current_id is not None:
            for row in range(self.table.rowCount()):
                if self.table.item(row, 0).data(Qt.UserRole) == current_id:
                    self.table.selectRow(row)
                    break
        elif self.table.rowCount():
            self.table.selectRow(0)
        self._show_detail()

    def _refresh_buttons(self) -> None:
        has_rows = self.table.rowCount() > 0
        self.ai_btn.setEnabled(has_rows and self._thread is None)
        self.ai_btn.setText("审核中…" if self._thread is not None else "AI 预审")

    def _notify(self, text: str, level: str = "info") -> None:
        self.notify.emit(text, level)

    def _save_selected(self) -> None:
        candidate = self._current()
        if not candidate:
            return
        try:
            self.db.update_candidate(
                candidate.id,
                src=self.src_view.toPlainText().strip(),
                dst=self.dst_view.toPlainText().strip(),
            )
        except Exception as exc:  # noqa: BLE001
            self._notify(str(exc), "error")
            return
        self._notify("候选已保存", "success")
        self.changed.emit()

    def _approve_selected(self) -> None:
        rows = self._selected()
        if not rows:
            return
        if not ask_confirm(self, "通过候选", f"将通过 {len(rows)} 条候选并写入正式语料库？"):
            return
        current = self._current()
        for candidate in rows:
            src = self.src_view.toPlainText().strip() if current and candidate.id == current.id else None
            dst = self.dst_view.toPlainText().strip() if current and candidate.id == current.id else None
            try:
                self.db.approve_candidate(candidate.id, src=src or None, dst=dst or None, origin="human")
            except Exception as exc:  # noqa: BLE001
                self._notify(str(exc), "error")
                continue
        self._notify(f"已通过 {len(rows)} 条候选", "success")
        self.changed.emit()

    def _reject_selected(self) -> None:
        rows = self._selected()
        if not rows:
            return
        if not ask_confirm(self, "拒绝候选", f"拒绝选中的 {len(rows)} 条候选？"):
            return
        for candidate in rows:
            self.db.reject_candidate(candidate.id, "人工拒绝")
        self._notify(f"已拒绝 {len(rows)} 条候选", "success")
        self.changed.emit()

    def _apply_ai_translation(self) -> None:
        candidate = self._current()
        if not candidate or not candidate.ai_suggested_dst:
            return
        self.dst_view.setPlainText(candidate.ai_suggested_dst)
        self._notify("已填入 AI 建议译文，确认后点击「保存修改」或「通过」", "info")

    def _adopt_ai(self) -> None:
        candidates = [
            c
            for c in self._candidates.values()
            if c.ai_decision == "approve"
            and c.ai_score is not None
            and c.ai_score >= 0.9
            and not c.ai_issues
            and c.quality >= 0.85
            and c.occurrences >= 2
        ]
        if not candidates:
            self._notify("没有满足自动采纳条件的候选", "info")
            return
        if not ask_confirm(
            self, "采纳 AI 建议", f"将通过 {len(candidates)} 条 AI 高置信候选并写入正式语料库？"
        ):
            return
        for candidate in candidates:
            self.db.approve_candidate(candidate.id, origin="human")
        self._notify(f"已采纳 {len(candidates)} 条 AI 建议", "success")
        self.changed.emit()

    def _ai_review(self) -> None:
        reviewer = AIReviewer(self.config)
        ready, message = reviewer.readiness()
        if not ready:
            self._notify(message, "error")
            return
        selected = self._selected()
        candidates = selected or list(self._candidates.values())
        if not candidates:
            return
        self._review_ids = [c.id for c in candidates]
        self.db.set_candidate_ai_state(self._review_ids, "queued")
        self._thread = ReviewThread(reviewer, candidates, self)
        self._thread.progress.connect(self._on_ai_progress)
        self._thread.done.connect(self._on_ai_done)
        self._thread.failed.connect(self._on_ai_failed)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()
        self._refresh_buttons()
        self.progress_label.setText("AI 审核中…")

    def _on_ai_progress(self, done: int, total: int) -> None:
        self.progress_label.setText(f"AI 审核 {done}/{total}")

    def _on_ai_done(self, results: object) -> None:
        self._thread = None
        auto_count = 0
        reviewed = 0
        for candidate, result, error in results or []:
            if candidate.id not in self._candidates and not self.db.get_candidate(candidate.id):
                continue
            if error or result is None:
                self.db.set_candidate_ai_state([candidate.id], "error")
                continue
            self.db.save_ai_review(
                candidate.id,
                result.decision,
                result.score,
                result.issues,
                result.suggested_dst,
                result.reason,
                result.model,
                self.config.settings.review.prompt_version,
                result.latency_ms,
            )
            reviewed += 1
            if self.config.settings.review.auto_approve:
                fresh = self.db.get_candidate(candidate.id)
                if fresh and auto_approvable(
                    fresh,
                    result.decision,
                    result.score,
                    result.issues,
                    min_score=float(self.config.settings.review.min_auto_score or 0.9),
                    min_occurrences=int(self.config.settings.translate.auto_approve_min_occurrences or 2),
                ):
                    if self.db.approve_candidate(candidate.id, origin="auto"):
                        auto_count += 1
        self.progress_label.setText("")
        self._review_ids = []
        self._refresh_buttons()
        self._notify(f"AI 已审核 {reviewed} 条" + (f"，自动采纳 {auto_count} 条" if auto_count else ""), "success")
        self.changed.emit()

    def _on_ai_failed(self, message: str) -> None:
        self._thread = None
        self.progress_label.setText("")
        self.db.set_candidate_ai_state(self._review_ids, "error")
        self._refresh_buttons()
        self._notify(message, "error")
        self.changed.emit()

    def shutdown(self) -> None:
        thread = self._thread
        if thread is None or not thread.isRunning():
            return
        thread.requestInterruption()
        if not thread.wait(1500):
            thread.terminate()
            thread.wait(500)
        self._thread = None


class RejectedPanel(QWidget):
    changed = Signal()
    notify = Signal(str, str)

    def __init__(self, db: Database, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.db = db
        self._ids: dict[int, int] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["原文", "译文", "拒绝原因", "时间"])
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        layout.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.footer = QLabel("")
        self.footer.setObjectName("Dim")
        row.addWidget(self.footer)
        row.addStretch(1)
        restore = button("恢复为待审核", "soft")
        restore.clicked.connect(self._restore)
        remove = button("删除选中", "danger")
        remove.clicked.connect(self._delete)
        clear = button("清空已拒绝", "ghost")
        clear.clicked.connect(self._clear)
        row.addWidget(restore)
        row.addWidget(remove)
        row.addWidget(clear)
        layout.addLayout(row)

    def reload(self) -> None:
        items = self.db.list_candidates(status="rejected", limit=1000)
        self._ids = {i: c.id for i, c in enumerate(items)}
        self.table.setRowCount(0)
        for row, c in enumerate(items):
            self.table.insertRow(row)
            for col, text in enumerate(
                (c.src, c.dst, "、".join(c.flags[-2:]) or "人工拒绝", c.last_seen_at.replace("T", " ")[:16])
            ):
                item = QTableWidgetItem(text)
                item.setData(Qt.UserRole, c.id)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                self.table.setItem(row, col, item)
            self.table.setRowHeight(row, 36)
        self.footer.setText(f"{len(items)} 条已拒绝")

    def _selected(self) -> list[int]:
        return sorted({self.table.item(i.row(), 0).data(Qt.UserRole) for i in self.table.selectedIndexes()})

    def _restore(self) -> None:
        ids = self._selected()
        for candidate_id in ids:
            self.db.restore_candidate(candidate_id)
        if ids:
            self.notify.emit(f"已恢复 {len(ids)} 条候选", "success")
            self.changed.emit()

    def _delete(self) -> None:
        ids = self._selected()
        if ids and ask_confirm(self, "删除候选", f"永久删除选中的 {len(ids)} 条？"):
            self.db.delete_candidates(ids)
            self.notify.emit(f"已删除 {len(ids)} 条", "success")
            self.changed.emit()

    def _clear(self) -> None:
        if ask_confirm(self, "清空已拒绝", "永久清空全部已拒绝候选？"):
            count = self.db.clear_candidates("rejected")
            self.notify.emit(f"已清空 {count} 条", "success")
            self.changed.emit()


class CorpusPage(QWidget):
    changed = Signal()
    notify = Signal(str, str)

    def __init__(
        self, pipeline: "Pipeline", db: Database, config: ConfigStore, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.pipeline = pipeline
        self.db = db
        self.config = config
        self._loading = False
        self._build()
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(220)
        self._search_timer.timeout.connect(self._reload_approved)
        self.search.textChanged.connect(lambda: self._search_timer.start())
        self.reload()
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.shutdown)

    def shutdown(self) -> None:
        self.pending.shutdown()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)
        header = PageHeader(
            "语料库 · 翻译记忆",
            "自动学习的译文先进入「待审核」；只有人工通过或明确采纳的条目才会参与整句匹配",
        )
        import_btn = button("导入", "soft")
        import_btn.clicked.connect(self._import)
        export_btn = button("导出", "ghost")
        export_btn.clicked.connect(self._export)
        add_btn = button("添加语料", "primary")
        add_btn.clicked.connect(self._add)
        for btn in (import_btn, export_btn, add_btn):
            header.add_action(btn)
        root.addWidget(header)

        top = Card()
        row = QHBoxLayout()
        row.setSpacing(14)
        stat_box = QVBoxLayout()
        stat_box.setSpacing(2)
        self.count_label = QLabel("0 条")
        self.count_label.setStyleSheet("font-size: 22px; font-weight: 600;")
        self.hits_label = QLabel("累计命中 0 次")
        self.hits_label.setObjectName("Dim")
        stat_box.addWidget(self.count_label)
        stat_box.addWidget(self.hits_label)
        row.addLayout(stat_box)
        row.addSpacing(20)
        self.pending_label = QLabel("待审核 0")
        self.pending_label.setStyleSheet("color: #f0b45a; font-weight: 600;")
        self.rejected_label = QLabel("已拒绝 0")
        self.rejected_label.setObjectName("Dim")
        row.addWidget(self.pending_label)
        row.addWidget(self.rejected_label)
        row.addSpacing(18)
        split = QWidget()
        split_layout = QHBoxLayout(split)
        split_layout.setContentsMargins(0, 0, 0, 0)
        split_layout.setSpacing(8)
        self.use_switch = Switch()
        self.use_switch.setChecked(self.config.settings.translate.use_tm)
        self.use_switch.toggled.connect(self._toggle_use)
        split_layout.addWidget(self.use_switch)
        split_layout.addWidget(QLabel("使用语料库"))
        split_layout.addSpacing(14)
        self.learn_switch = Switch()
        self.learn_switch.setChecked(self.config.settings.translate.auto_learn_mode != "off")
        self.learn_switch.toggled.connect(self._toggle_learn)
        split_layout.addWidget(self.learn_switch)
        split_layout.addWidget(QLabel("候选学习"))
        row.addWidget(split)
        row.addStretch(1)
        top.add_layout(row)
        root.addWidget(top)

        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.approved_tab = self._build_approved()
        self.pending = PendingPanel(self.pipeline, self.db, self.config)
        self.rejected = RejectedPanel(self.db)
        self.tabs.addTab(self.approved_tab, "已审核")
        self.tabs.addTab(self.pending, "待审核")
        self.tabs.addTab(self.rejected, "已拒绝")
        root.addWidget(self.tabs, 1)
        self.pending.changed.connect(self._after_change)
        self.pending.notify.connect(self.notify)
        self.rejected.changed.connect(self._after_change)
        self.rejected.notify.connect(self.notify)

    def _build_approved(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)
        card = Card("已审核语料")
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索原文 / 译文…")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(320)
        card.add_widget(self.search)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["原文", "译文", "目标语言", "质量", "命中", "更新时间"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
        )
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        for col in (2, 3, 4, 5):
            hh.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.setMinimumHeight(300)
        card.add_widget(self.table)
        actions = QHBoxLayout()
        self.footer = QLabel("")
        self.footer.setObjectName("Dim")
        actions.addWidget(self.footer)
        actions.addStretch(1)
        rebuild_btn = button("重建索引", "soft")
        rebuild_btn.clicked.connect(self._rebuild)
        delete_btn = button("删除选中", "danger")
        delete_btn.clicked.connect(self._delete_selected)
        clear_btn = button("清空语料库", "ghost")
        clear_btn.clicked.connect(self._clear)
        actions.addWidget(rebuild_btn)
        actions.addWidget(delete_btn)
        actions.addWidget(clear_btn)
        card.add_layout(actions)
        layout.addWidget(card, 1)
        return page

    # ------------------------------------------------------------------
    def reload(self) -> None:
        self._reload_approved()
        self.pending.reload()
        self.rejected.reload()
        self._update_stats()

    def _reload_approved(self) -> None:
        target = self.config.settings.translate.target_lang
        entries = self.db.list_tm(tgt_lang=target, query=self.search.text(), limit=5000)
        self._loading = True
        self.table.setRowCount(0)
        for row, entry in enumerate(entries):
            self.table.insertRow(row)
            src = QTableWidgetItem(entry.src)
            src.setData(Qt.UserRole, entry.id)
            dst = QTableWidgetItem(entry.dst)
            dst.setData(Qt.UserRole, entry.id)
            lang = QTableWidgetItem(entry.tgt_lang)
            quality = QTableWidgetItem(f"{entry.quality:.2f}")
            quality.setTextAlignment(Qt.AlignCenter)
            hits = QTableWidgetItem(str(entry.hits))
            hits.setTextAlignment(Qt.AlignCenter)
            updated = QTableWidgetItem(entry.updated_at.replace("T", " ")[:16])
            for item in (lang, quality, hits, updated):
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            for col, item in enumerate((src, dst, lang, quality, hits, updated)):
                self.table.setItem(row, col, item)
            self.table.setRowHeight(row, 36)
        self._loading = False
        self.footer.setText(f"显示 {len(entries)} 条")
        self._update_stats(target)

    def _update_stats(self, target: str | None = None) -> None:
        target = target or self.config.settings.translate.target_lang
        all_entries = self.db.list_tm(tgt_lang=target, limit=50000)
        total_hits = sum(e.hits for e in all_entries)
        stats = self.db.candidate_stats()
        self.count_label.setText(f"{len(all_entries)} 条")
        self.hits_label.setText(f"累计命中 {total_hits} 次 · {target_language_name(target)}")
        self.pending_label.setText(f"待审核 {stats.get('pending', 0)}")
        self.rejected_label.setText(f"已拒绝 {stats.get('rejected', 0)}")
        self.tabs.setTabText(0, f"已审核 {len(all_entries)}")
        self.tabs.setTabText(1, f"待审核 {stats.get('pending', 0)}")
        self.tabs.setTabText(2, f"已拒绝 {stats.get('rejected', 0)}")

    def _after_change(self) -> None:
        self.reload()
        self.changed.emit()

    def _on_tab_changed(self, index: int) -> None:
        if index == 1:
            self.pending.reload()
        elif index == 2:
            self.rejected.reload()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading:
            return
        term_id = item.data(Qt.UserRole)
        if not term_id or item.column() not in (0, 1):
            return
        row = item.row()
        try:
            self.db.update_tm(
                term_id, self.table.item(row, 0).text(), self.table.item(row, 1).text()
            )
        except Exception as exc:  # noqa: BLE001
            self.notify.emit(str(exc), "error")
            self._reload_approved()
            return
        self._reload_memory()
        self.changed.emit()

    def _reload_memory(self) -> None:
        if hasattr(self.pipeline, "_memory"):
            self.pipeline._memory.reload()

    def _toggle_use(self, enabled: bool) -> None:
        self.config.settings.translate.use_tm = enabled
        self.config.save()
        self.pipeline.apply_settings()

    def _toggle_learn(self, enabled: bool) -> None:
        self.config.settings.translate.auto_learn_mode = "candidates" if enabled else "off"
        self.config.settings.translate.auto_learn = enabled
        self.config.save()
        self.pipeline.apply_settings()

    def _add(self) -> None:
        dialog = TMDialog(parent=self)
        if dialog.exec():
            self.db.upsert_tm(
                dialog.src.text(),
                dialog.dst.text(),
                src_lang=self.config.settings.asr.language,
                tgt_lang=self.config.settings.translate.target_lang,
                origin="human",
            )
            self._reload_memory()
            self._after_change()

    def _delete_selected(self) -> None:
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        if not rows:
            return
        if not ask_confirm(self, "删除语料", f"确定删除选中的 {len(rows)} 条语料？"):
            return
        ids = [self.table.item(row, 0).data(Qt.UserRole) for row in rows]
        self.db.delete_tm(ids)
        self._reload_memory()
        self._after_change()

    def _clear(self) -> None:
        if not ask_confirm(self, "清空语料库", "确定清空全部翻译记忆？此操作不可撤销。"):
            return
        self.db.clear_tm()
        self._reload_memory()
        self._after_change()

    def _rebuild(self) -> None:
        self._reload_memory()
        self.notify.emit("语料索引已重建", "success")
        self._reload_approved()

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "导入语料", "", "语料文件 (*.csv *.tsv *.txt *.xlsx *.json)"
        )
        if not path:
            return
        try:
            rows = importers.read_tm_file(path)
        except Exception as exc:  # noqa: BLE001
            self.notify.emit(f"读取失败：{exc}", "error")
            return
        target = self.config.settings.translate.target_lang
        count = 0
        for row in rows:
            self.db.upsert_tm(
                row.get("src", ""),
                row.get("dst", ""),
                src_lang=self.config.settings.asr.language,
                tgt_lang=target,
                origin="import",
            )
            count += 1
        self._reload_memory()
        self._after_change()
        self.notify.emit(f"导入 {count} 条语料", "success")

    def _export(self) -> None:
        entries = self.db.list_tm(
            tgt_lang=self.config.settings.translate.target_lang, limit=100000
        )
        path, selected = QFileDialog.getSaveFileName(
            self,
            "导出语料库",
            str(Path.home() / "translation_memory.csv"),
            "CSV (*.csv);;Excel (*.xlsx);;JSON (*.json)",
        )
        if not path:
            return
        fmt = "csv"
        if selected.startswith("Excel") or path.lower().endswith(".xlsx"):
            fmt = "xlsx"
            if not path.lower().endswith(".xlsx"):
                path += ".xlsx"
        elif selected.startswith("JSON") or path.lower().endswith(".json"):
            fmt = "json"
            if not path.lower().endswith(".json"):
                path += ".json"
        elif not path.lower().endswith(".csv"):
            path += ".csv"
        try:
            exporter.export_tm(entries, path, fmt)
            self.notify.emit(f"已导出到 {path}", "success")
        except Exception as exc:  # noqa: BLE001
            self.notify.emit(f"导出失败：{exc}", "error")
