"""工作台 · 术语库。"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ... import exporter, importers
from ...config import ConfigStore
from ...db import Database
from ...models import Term
from ..widgets import Card, Dialog, PageHeader, Switch, button
from .common import ask_confirm

if TYPE_CHECKING:
    from ...pipeline import Pipeline

log = logging.getLogger(__name__)

COLUMNS = ["启用", "原文", "译文", "别名", "领域", "备注", "优先级"]


class BankDialog(Dialog):
    def __init__(self, parent: QWidget | None = None, name: str = "", description: str = "") -> None:
        super().__init__("新建术语库" if not name else "编辑术语库", parent, width=440)
        self.name_edit = QLineEdit(name)
        self.name_edit.setPlaceholderText("例如：AI / 医学 / 公司产品名")
        self.desc_edit = QLineEdit(description)
        self.desc_edit.setPlaceholderText("可选说明")
        self.add_widget(_field("名称", self.name_edit))
        self.add_widget(_field("说明", self.desc_edit))
        self.name_edit.setFocus()

    def accept(self) -> None:
        if not self.name_edit.text().strip():
            self.name_edit.setFocus()
            return
        super().accept()

    @property
    def name(self) -> str:
        return self.name_edit.text().strip()

    @property
    def description(self) -> str:
        return self.desc_edit.text().strip()


class TermDialog(Dialog):
    def __init__(self, term: Term | None = None, parent: QWidget | None = None) -> None:
        super().__init__("编辑术语" if term else "添加术语", parent, width=480)
        self.term = term
        self.src = QLineEdit(term.src if term else "")
        self.src.setPlaceholderText("原文，例如 VAD")
        self.dst = QLineEdit(term.dst if term else "")
        self.dst.setPlaceholderText("译文，例如 语音活动检测")
        self.aliases = QLineEdit(term.aliases if term else "")
        self.aliases.setPlaceholderText("可选，多个用逗号分隔")
        self.domain = QLineEdit(term.domain if term else "")
        self.domain.setPlaceholderText("可选，例如 技术")
        self.note = QPlainTextEdit(term.note if term else "")
        self.note.setPlaceholderText("可选备注")
        self.note.setFixedHeight(62)
        self.priority = QSpinBox()
        self.priority.setRange(0, 100)
        self.priority.setValue(term.priority if term else 0)
        self.case_sensitive = QCheckBox("区分大小写")
        self.case_sensitive.setChecked(term.case_sensitive if term else False)
        self.whole_word = QCheckBox("全词匹配（英文/数字）")
        self.whole_word.setChecked(term.whole_word if term else True)
        options = QHBoxLayout()
        options.addWidget(self.case_sensitive)
        options.addWidget(self.whole_word)
        options.addStretch(1)
        self.add_widget(_field("原文", self.src))
        self.add_widget(_field("译文", self.dst))
        self.add_widget(_field("别名", self.aliases))
        self.add_widget(_field("领域", self.domain))
        self.add_widget(_field("备注", self.note))
        self.add_widget(_field("优先级", self.priority))
        self.add_layout(options)
        self.src.setFocus()

    def accept(self) -> None:
        if not self.src.text().strip() or not self.dst.text().strip():
            (self.src if not self.src.text().strip() else self.dst).setFocus()
            return
        super().accept()


def _field(label: str, widget: QWidget) -> QWidget:
    wrap = QWidget()
    layout = QVBoxLayout(wrap)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(5)
    lbl = QLabel(label)
    lbl.setObjectName("Dim")
    layout.addWidget(lbl)
    layout.addWidget(widget)
    return wrap


class TermsPage(QWidget):
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
        self._bank_id = 0
        self._bank_builtin = False
        self._build()
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(220)
        self._search_timer.timeout.connect(self.reload_terms)
        self.reload_banks()

    # ------------------------------------------------------------------ UI
    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)
        header = PageHeader("术语库", "按句命中后只注入当前句命中的术语；多个术语库可同时参与匹配")
        new_btn = button("新建术语库", "soft")
        new_btn.clicked.connect(self._new_bank)
        self.import_btn = button("导入", "soft")
        self.import_btn.clicked.connect(self._import)
        export_btn = button("导出", "ghost")
        export_btn.clicked.connect(self._export)
        self.add_btn = button("添加术语", "primary")
        self.add_btn.clicked.connect(self._add_term)
        for btn in (new_btn, self.import_btn, export_btn, self.add_btn):
            header.add_action(btn)
        root.addWidget(header)

        bar = Card()
        bar_layout = QHBoxLayout()
        bar_layout.setSpacing(10)
        bar_layout.addWidget(QLabel("当前术语库"))
        self.bank_combo = QComboBox()
        self.bank_combo.setMinimumWidth(240)
        self.bank_combo.currentIndexChanged.connect(self._on_bank_changed)
        bar_layout.addWidget(self.bank_combo)
        self.bank_badge = QLabel("")
        self.bank_badge.setObjectName("Badge")
        bar_layout.addWidget(self.bank_badge)
        self.bank_count = QLabel("")
        self.bank_count.setObjectName("Dim")
        bar_layout.addWidget(self.bank_count)
        bar_layout.addSpacing(8)
        self.enable_switch = Switch()
        self.enable_switch.toggled.connect(self._toggle_bank)
        bar_layout.addWidget(self.enable_switch)
        self.enable_label = QLabel("参与匹配")
        self.enable_label.setObjectName("Dim")
        bar_layout.addWidget(self.enable_label)
        bar_layout.addStretch(1)
        self.copy_btn = button("复制为我的库", "soft")
        self.copy_btn.clicked.connect(self._copy_bank)
        self.copy_btn.setVisible(False)
        bar_layout.addWidget(self.copy_btn)
        self.rename_btn = button("重命名", "ghost")
        self.rename_btn.clicked.connect(self._rename_bank)
        self.delete_bank_btn = button("删除库", "ghost")
        self.delete_bank_btn.clicked.connect(self._delete_bank)
        bar_layout.addWidget(self.rename_btn)
        bar_layout.addWidget(self.delete_bank_btn)
        bar.add_layout(bar_layout)

        tools = QHBoxLayout()
        tools.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索原文 / 译文 / 别名 / 备注…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda: self._search_timer.start())
        self.search.setMinimumWidth(300)
        self.search.setMaximumWidth(360)
        tools.addWidget(self.search)
        tools.addStretch(1)
        self.delete_btn = button("删除选中", "danger")
        self.delete_btn.clicked.connect(self._delete_selected)
        tools.addWidget(self.delete_btn)
        bar.add_layout(tools)
        root.addWidget(bar)

        table_card = Card("术语列表（双击单元格直接编辑）")
        self.table_card = table_card
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
        )
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(1, QHeaderView.Stretch)
        header_view.setSectionResizeMode(2, QHeaderView.Stretch)
        header_view.setSectionResizeMode(3, QHeaderView.Stretch)
        header_view.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(5, QHeaderView.Stretch)
        header_view.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.setMinimumHeight(360)
        table_card.add_widget(self.table)
        self.footer = QLabel("")
        self.footer.setObjectName("Dim")
        table_card.add_widget(self.footer)
        root.addWidget(table_card, 1)

        delete_shortcut = QShortcut(QKeySequence.Delete, self.table)
        delete_shortcut.activated.connect(self._delete_selected)
        add_shortcut = QShortcut(QKeySequence("Ctrl+N"), self)
        add_shortcut.activated.connect(self._add_term)
        find_shortcut = QShortcut(QKeySequence("Ctrl+F"), self)
        find_shortcut.activated.connect(self.search.setFocus)
        self._build_context_menu()

    def _build_context_menu(self) -> None:
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)

    def _show_context_menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        if self._bank_builtin:
            menu.addAction("复制为我的术语库", self._copy_bank)
        else:
            menu.addAction("添加术语", self._add_term)
            menu.addAction("编辑选中", self._edit_selected)
            menu.addSeparator()
            menu.addAction("删除选中", self._delete_selected)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------ 数据
    def reload_banks(self, select_id: int | None = None) -> None:
        banks = self.db.list_banks()
        self.bank_combo.blockSignals(True)
        self.bank_combo.clear()
        for bank in banks:
            text = bank.name + ("" if bank.enabled else "（停用）")
            if bank.builtin:
                text += "  [内置]"
            self.bank_combo.addItem(text, bank.id)
        if select_id is not None:
            target = select_id
        elif self._bank_id:
            target = self._bank_id
        elif self.config.settings.ui.active_bank_id:
            target = self.config.settings.ui.active_bank_id
        else:
            target = banks[0].id if banks else 0
        index = self.bank_combo.findData(target)
        if index < 0 and self.bank_combo.count():
            index = 0
        if index >= 0:
            self.bank_combo.setCurrentIndex(index)
        self.bank_combo.blockSignals(False)
        if index >= 0:
            self._bank_id = int(self.bank_combo.itemData(index))
            self.config.settings.ui.active_bank_id = self._bank_id
        self._sync_bank_controls()
        self.reload_terms()

    def _sync_bank_controls(self) -> None:
        bank = self.db.get_bank(self._bank_id) if self._bank_id else None
        enabled = bool(bank and bank.enabled)
        self._bank_builtin = bool(bank and bank.builtin)
        self.enable_switch.blockSignals(True)
        self.enable_switch.setChecked(enabled)
        self.enable_switch.blockSignals(False)
        self.enable_label.setText("参与匹配" if enabled else "未参与匹配")
        self.enable_label.setStyleSheet(
            "color: #54e0b0;" if enabled else "color: #8f82a8;"
        )
        self.bank_count.setText(f"{bank.term_count if bank else 0} 条" if bank else "无术语库")
        self.bank_badge.setText("内置基础库 · 只读" if self._bank_builtin else "")
        self.bank_badge.setVisible(self._bank_builtin)
        if self.table_card.title_label is not None:
            self.table_card.title_label.setText(
                "术语列表 · 内置库只读"
                if self._bank_builtin
                else "术语列表（双击单元格直接编辑）"
            )
        self.copy_btn.setVisible(self._bank_builtin)
        self.add_btn.setEnabled(not self._bank_builtin)
        self.import_btn.setEnabled(not self._bank_builtin)
        self.delete_btn.setEnabled(not self._bank_builtin)
        self.rename_btn.setEnabled(not self._bank_builtin)
        self.delete_bank_btn.setEnabled(not self._bank_builtin)
        self.add_btn.setToolTip(
            "内置基础库只读；可复制为自己的术语库后编辑"
            if self._bank_builtin
            else ""
        )
        self.table.setEnabled(bank is not None)
        self.table.setEditTriggers(
            QAbstractItemView.NoEditTriggers
            if self._bank_builtin
            else QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
        )

    def reload_terms(self) -> None:
        if not self._bank_id:
            self.table.setRowCount(0)
            self.footer.setText("还没有术语库，点击右上角「新建术语库」开始。")
            return
        terms = self.db.list_terms(self._bank_id, self.search.text())
        self._loading = True
        self.table.setRowCount(0)
        for row, term in enumerate(terms):
            self.table.insertRow(row)
            check = QTableWidgetItem()
            check.setFlags(
                Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            check.setCheckState(Qt.Checked if term.enabled else Qt.Unchecked)
            check.setData(Qt.UserRole, term.id)
            self.table.setItem(row, 0, check)
            values = [
                term.src,
                term.dst,
                term.aliases,
                term.domain,
                term.note,
                str(term.priority),
            ]
            for col, value in enumerate(values, start=1):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, term.id)
                if self._bank_builtin:
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                if col == 6:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, col, item)
            self.table.setRowHeight(row, 36)
        self._loading = False
        bank = self.db.get_bank(self._bank_id)
        total = bank.term_count if bank else 0
        if self._bank_builtin:
            self.footer.setText(
                f"当前显示 {len(terms)} 条 · 内置基础库只读，可整体停用，"
                "或点「复制为我的库」后编辑"
            )
        else:
            self.footer.setText(
                f"当前显示 {len(terms)} 条 · 本库共 {total} 条 · "
                "启用后仅注入当前句命中的术语"
            )
        self._sync_bank_controls()

    def _on_bank_changed(self, index: int) -> None:
        bank_id = self.bank_combo.itemData(index)
        if not bank_id:
            return
        self._bank_id = int(bank_id)
        self.config.settings.ui.active_bank_id = self._bank_id
        self.config.save()
        self._sync_bank_controls()
        self.reload_terms()

    def _toggle_bank(self, enabled: bool) -> None:
        if not self._bank_id:
            return
        self.db.set_bank_enabled(self._bank_id, enabled)
        self.pipeline.reload_glossary()
        self._sync_bank_controls()
        self.changed.emit()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading:
            return
        term_id = item.data(Qt.UserRole)
        if not term_id:
            return
        col = item.column()
        try:
            if col == 0:
                self.db.update_term(term_id, enabled=item.checkState() == Qt.Checked)
            elif col == 1:
                if not item.text().strip():
                    raise ValueError("原文不能为空")
                self.db.update_term(term_id, src=item.text())
            elif col == 2:
                if not item.text().strip():
                    raise ValueError("译文不能为空")
                self.db.update_term(term_id, dst=item.text())
            elif col == 3:
                self.db.update_term(term_id, aliases=item.text())
            elif col == 4:
                self.db.update_term(term_id, domain=item.text())
            elif col == 5:
                self.db.update_term(term_id, note=item.text())
            elif col == 6:
                self.db.update_term(term_id, priority=int(item.text() or 0))
        except Exception as exc:
            self.notify.emit(f"保存术语失败：{exc}", "error")
            self.reload_terms()
            return
        self.pipeline.reload_glossary(silent=True)
        self._sync_bank_controls()
        self.changed.emit()

    # ------------------------------------------------------------------ 操作
    def _add_term(self) -> None:
        if self._bank_builtin:
            self.notify.emit("内置基础库只读；请先点「复制为我的库」", "warn")
            return
        if not self._bank_id:
            self._new_bank()
            if not self._bank_id:
                return
        dialog = TermDialog(parent=self)
        if dialog.exec():
            try:
                self.db.add_term(
                    self._bank_id,
                    dialog.src.text(),
                    dialog.dst.text(),
                    aliases=dialog.aliases.text(),
                    domain=dialog.domain.text(),
                    note=dialog.note.toPlainText(),
                    case_sensitive=dialog.case_sensitive.isChecked(),
                    whole_word=dialog.whole_word.isChecked(),
                    priority=dialog.priority.value(),
                )
            except Exception as exc:
                self.notify.emit(str(exc), "error")
                return
            self.reload_banks(self._bank_id)
            self.pipeline.reload_glossary(silent=True)
            self.changed.emit()

    def _edit_selected(self) -> None:
        if self._bank_builtin:
            self.notify.emit("内置基础库只读；请先点「复制为我的库」", "warn")
            return
        row = self.table.currentRow()
        if row < 0:
            return
        term_id = self.table.item(row, 0).data(Qt.UserRole)
        term = self.db.get_term(term_id)
        if not term:
            return
        dialog = TermDialog(term, self)
        if dialog.exec():
            try:
                self.db.update_term(
                    term.id,
                    src=dialog.src.text(),
                    dst=dialog.dst.text(),
                    aliases=dialog.aliases.text(),
                    domain=dialog.domain.text(),
                    note=dialog.note.toPlainText(),
                    case_sensitive=dialog.case_sensitive.isChecked(),
                    whole_word=dialog.whole_word.isChecked(),
                    priority=dialog.priority.value(),
                )
            except Exception as exc:
                self.notify.emit(str(exc), "error")
                return
            self.reload_terms()
            self.pipeline.reload_glossary(silent=True)
            self.changed.emit()

    def _delete_selected(self) -> None:
        if self._bank_builtin:
            self.notify.emit("内置基础库只读，不能删除术语", "warn")
            return
        rows = sorted({index.row() for index in self.table.selectedIndexes()})
        if not rows:
            return
        if not ask_confirm(self, "删除术语", f"确定删除选中的 {len(rows)} 条术语？"):
            return
        ids = [self.table.item(row, 0).data(Qt.UserRole) for row in rows]
        self.db.delete_terms(ids)
        self.reload_banks(self._bank_id)
        self.pipeline.reload_glossary(silent=True)
        self.changed.emit()

    def _new_bank(self) -> None:
        dialog = BankDialog(self)
        if dialog.exec():
            try:
                bank_id = self.db.create_bank(dialog.name, dialog.description)
            except Exception as exc:
                self.notify.emit(str(exc), "error")
                return
            self.reload_banks(bank_id)
            self.pipeline.reload_glossary(silent=True)
            self.changed.emit()

    def _rename_bank(self) -> None:
        if self._bank_builtin:
            self.notify.emit("内置基础库不能重命名", "warn")
            return
        bank = self.db.get_bank(self._bank_id) if self._bank_id else None
        if not bank:
            return
        dialog = BankDialog(self, bank.name, bank.description)
        if dialog.exec():
            try:
                self.db.update_bank(bank.id, name=dialog.name, description=dialog.description)
            except Exception as exc:
                self.notify.emit(str(exc), "error")
                return
            self.reload_banks(bank.id)
            self.changed.emit()

    def _delete_bank(self) -> None:
        if self._bank_builtin:
            self.notify.emit("内置基础库不能删除，可整体停用", "warn")
            return
        if not self._bank_id:
            return
        banks = self.db.list_banks()
        if len(banks) <= 1:
            self.notify.emit("至少保留一个术语库", "warn")
            return
        bank = self.db.get_bank(self._bank_id)
        if not bank:
            return
        if not ask_confirm(self, "删除术语库", f"确定删除「{bank.name}」及其 {bank.term_count} 条术语？"):
            return
        self.db.delete_bank(bank.id)
        self._bank_id = 0
        self.reload_banks()
        self.pipeline.reload_glossary(silent=True)
        self.changed.emit()

    def _import(self) -> None:
        if self._bank_builtin:
            self.notify.emit("内置基础库只读，不能导入术语；请先复制为自己的库", "warn")
            return
        if not self._bank_id:
            self.notify.emit("请先选择术语库", "warn")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "导入术语", "", "术语文件 (*.csv *.tsv *.txt *.xlsx *.json)"
        )
        if not path:
            return
        try:
            rows = importers.read_term_file(path)
        except Exception as exc:
            self.notify.emit(f"读取文件失败：{exc}", "error")
            return
        if not rows:
            self.notify.emit("没有识别到有效术语（需要原文和译文两列）", "warn")
            return
        added, updated = self.db.import_terms(self._bank_id, rows)
        self.reload_banks(self._bank_id)
        self.pipeline.reload_glossary(silent=True)
        self.changed.emit()
        self.notify.emit(f"导入完成：新增 {added} 条，更新 {updated} 条", "success")

    def _copy_bank(self) -> None:
        bank = self.db.get_bank(self._bank_id) if self._bank_id else None
        if not bank or not bank.builtin:
            return
        dialog = BankDialog(self, f"{bank.name} 副本", "由内置基础库复制，可自由编辑")
        if not dialog.exec():
            return
        try:
            new_id = self.db.create_bank(dialog.name, dialog.description)
            for term in self.db.list_terms(bank.id, limit=100000):
                self.db.add_term(
                    new_id,
                    term.src,
                    term.dst,
                    aliases=term.aliases,
                    note=term.note,
                    domain=term.domain,
                    case_sensitive=term.case_sensitive,
                    whole_word=term.whole_word,
                    enabled=term.enabled,
                    priority=term.priority,
                )
        except Exception as exc:
            self.notify.emit(f"复制基础库失败：{exc}", "error")
            return
        self.reload_banks(new_id)
        self.pipeline.reload_glossary(silent=True)
        self.changed.emit()
        self.notify.emit(f"已复制为「{dialog.name}」，现在可以编辑", "success")

    def _export(self) -> None:
        if not self._bank_id:
            return
        bank = self.db.get_bank(self._bank_id)
        if not bank:
            return
        terms = self.db.list_terms(self._bank_id, limit=100000)
        path, selected = QFileDialog.getSaveFileName(
            self,
            "导出术语库",
            str(Path.home() / f"{bank.name}.csv"),
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
            exporter.export_terms(terms, path, fmt)
            self.notify.emit(f"已导出到 {path}", "success")
        except Exception as exc:
            self.notify.emit(f"导出失败：{exc}", "error")
