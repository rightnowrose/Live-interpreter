"""页面公共工具。"""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget


def ask_confirm(parent: QWidget, title: str, text: str) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(QMessageBox.Question)
    yes = box.addButton("确定", QMessageBox.AcceptRole)
    box.addButton("取消", QMessageBox.RejectRole)
    box.exec()
    return box.clickedButton() is yes


def ask_text(parent: QWidget, title: str, text: str) -> str:
    from PySide6.QtWidgets import QInputDialog

    value, ok = QInputDialog.getText(parent, title, text)
    return value if ok else ""
