"""暗色主题、图标与 Windows 标题栏。"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QLinearGradient,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QApplication, QWidget

COLORS = {
    "bg": "#0d0915",
    "panel": "#171026",
    "panel2": "#211731",
    "border": "#342543",
    "text": "#f6edff",
    "dim": "#b7a6cf",
    "accent": "#ff6fa9",
    "accent2": "#8b7bff",
    "green": "#54e0b0",
    "red": "#ff6b8a",
    "orange": "#ffb86b",
}


def qcolor(name: str, alpha: int | None = None) -> QColor:
    color = QColor(COLORS.get(name, name))
    if alpha is not None:
        color.setAlpha(alpha)
    return color


QSS = """
* { outline: none; }
QWidget {
    color: #f6edff;
    font-family: "Microsoft YaHei UI", "Segoe UI", "PingFang SC", sans-serif;
    font-size: 13px;
}
QMainWindow, QWidget#Root, QDialog { background: #0d0915; }
QWidget#Sidebar {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #1d1131, stop:0.55 #171026, stop:1 #120b1e);
    border-right: 1px solid #342543;
}
QWidget#Content {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 #0d0915, stop:0.55 #100a19, stop:1 #150c21);
}
QWidget#Page { background: transparent; }

QLabel { background: transparent; }
QLabel#BrandName { font-size: 14px; font-weight: 600; color: #f6edff; }
QLabel#BrandSub { font-size: 11px; color: #b7a6cf; }
QLabel#Logo {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ff6fa9, stop:1 #8b7bff);
    border-radius: 10px; color: white; font-size: 18px; font-weight: 700;
}
QLabel#PageTitle { font-size: 21px; font-weight: 700; color: #fff2fb; letter-spacing: 0.4px; }
QLabel#PageSub { font-size: 12px; color: #b7a6cf; }
QLabel#CardTitle { font-size: 13px; font-weight: 600; color: #d9c8ef; }
QLabel#Dim { color: #b7a6cf; font-size: 12px; }
QLabel#Tiny { color: #8f7aa8; font-size: 11px; }
QLabel#Tag {
    background: rgba(255,111,169,0.15); color: #ff9cc7;
    border-radius: 10px; padding: 2px 9px; font-size: 11px;
}
QLabel#Badge {
    background: rgba(139,123,255,0.18); color: #c8beff;
    border: 1px solid rgba(139,123,255,0.35);
    border-radius: 9px; padding: 2px 8px; font-size: 11px;
}
QLabel#WarnTag { background: rgba(255,184,107,0.15); color: #ffb86b; border-radius: 10px; padding: 2px 9px; font-size: 11px; }
QLabel#GoodTag { background: rgba(53,194,107,0.15); color: #54e0b0; border-radius: 10px; padding: 2px 9px; font-size: 11px; }

QFrame#Card {
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 #1a1129, stop:1 #151022);
    border: 1px solid #342543; border-radius: 14px;
}
QFrame#SoftCard { background: #140d20; border: 1px solid #251b34; border-radius: 12px; }
QFrame#Divider { background: #251b34; max-height: 1px; border: none; }
QFrame#Panel { background: #171026; border: 1px solid #342543; border-radius: 10px; }

QTabWidget::pane { border: 1px solid #342543; border-radius: 10px; background: #171026; top: -1px; }
QTabBar::tab {
    background: transparent; color: #b7a6cf; padding: 8px 16px;
    border: 1px solid transparent; border-top-left-radius: 8px; border-top-right-radius: 8px;
    margin-right: 3px;
}
QTabBar::tab:hover { color: #f6edff; background: #211731; }
QTabBar::tab:selected { background: #3a2140; color: #f6edff; border-color: #2f1d3a; }

QPushButton {
    background: #211731; border: 1px solid #342543; border-radius: 8px;
    padding: 7px 14px; color: #f6edff;
}
QPushButton:hover { border-color: #4a355c; background: #251b34; }
QPushButton:pressed { background: #1c1428; }
QPushButton:disabled { color: #7a688f; border-color: #2b1f3a; background: #171026; }
QPushButton[variant="primary"] {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff73ad, stop:1 #9b7bff);
    border: 1px solid rgba(255,190,220,0.36); color: white; font-weight: 600;
}
QPushButton[variant="primary"]:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff5e9c, stop:1 #8667ff);
}
QPushButton[variant="primary"]:disabled {
    background: #2b2038; color: #7a688f; border-color: #38294a;
}
QPushButton[variant="danger"] { background: rgba(255,107,138,0.12); border-color: rgba(255,107,138,0.45); color: #ff9eb5; }
QPushButton[variant="danger"]:hover { background: rgba(255,107,138,0.2); }
QPushButton[variant="danger"]:disabled { background: #211526; color: #7a688f; border-color: #38294a; }
QPushButton[variant="ghost"] { background: transparent; border-color: transparent; color: #b7a6cf; }
QPushButton[variant="ghost"]:hover { background: #211731; color: #f6edff; }
QPushButton[variant="soft"] { background: #1c1329; border-color: #2f233f; }
QPushButton#Nav {
    background: transparent; border: none; text-align: left;
    padding: 10px 12px; color: #b7a6cf; border-radius: 8px; font-size: 13px;
}
QPushButton#Nav:hover { background: #211731; color: #f6edff; }
QPushButton#Nav:checked { background: rgba(255,111,169,0.14); color: #ff9cc7; }
QPushButton#Nav[collapsed="true"] { padding: 10px 0px; text-align: center; }
QPushButton#NavIcon { font-size: 14px; }
QPushButton#SideAction { padding: 8px 12px; border-radius: 8px; font-weight: 600; }
QPushButton#SideToggle {
    background: transparent; border: none; color: #9482b0;
    font-size: 16px; padding: 0px; border-radius: 6px;
}
QPushButton#SideToggle:hover { background: #251b34; color: #f6edff; }
QLabel#NavSection {
    color: #8f7aa8; font-size: 10px; font-weight: 600;
    letter-spacing: 1px; padding: 12px 12px 3px 12px;
}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit {
    background: #211731; border: 1px solid #342543; border-radius: 8px;
    padding: 7px 10px; color: #f6edff; selection-background-color: #ff6fa9;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QTextEdit:focus, QPlainTextEdit:focus { border-color: #ff6fa9; }
QLineEdit:disabled, QComboBox:disabled { color: #7a688f; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow {
    image: url("@CHEVRON_DOWN@"); width: 10px; height: 6px; margin-right: 7px;
}
QComboBox::down-arrow:on { image: url("@CHEVRON_UP@"); }
QComboBox QAbstractItemView {
    background: #211731; border: 1px solid #342543; border-radius: 8px;
    selection-background-color: #352441; padding: 4px;
}
QSpinBox::up-button, QDoubleSpinBox::up-button { border: none; width: 16px; }
QSpinBox::down-button, QDoubleSpinBox::down-button { border: none; width: 16px; }

QCheckBox { spacing: 8px; color: #d8c9ea; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #4a355c; border-radius: 4px; background: #211731; }
QCheckBox::indicator:hover { border-color: #ff6fa9; }
QCheckBox::indicator:checked { background: #ff6fa9; border-color: #ff6fa9; }

QSlider::groove:horizontal { height: 4px; background: #342543; border-radius: 2px; }
QSlider::sub-page:horizontal { background: #ff6fa9; border-radius: 2px; }
QSlider::handle:horizontal { width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; background: #ff6fa9; }
QSlider::handle:horizontal:hover { background: #ff9cc7; }

QTableWidget {
    background: #171026; border: 1px solid #342543; border-radius: 10px;
    gridline-color: #2b1f3a; alternate-background-color: #140e20;
    selection-background-color: #3a2140; selection-color: #ffffff;
}
QTableWidget::item { padding: 6px 8px; border-bottom: 1px solid #2b1f3a; }
QTableWidget::item:selected { background: #3a2140; }
QTableView::indicator, QTableWidget::indicator {
    width: 15px; height: 15px; border: 1px solid #4a355c;
    border-radius: 4px; background: #211731;
}
QTableView::indicator:hover, QTableWidget::indicator:hover { border-color: #ff6fa9; }
QTableView::indicator:checked, QTableWidget::indicator:checked {
    background: #ff6fa9; border-color: #ff6fa9; image: url("@CHECK@");
}
QHeaderView::section {
    background: #1d142b; color: #b7a6cf; border: none;
    border-bottom: 1px solid #342543; padding: 9px 8px; font-weight: 500;
}
QTableCornerButton::section { background: #1d142b; border: none; }

QScrollBar:vertical { background: transparent; width: 9px; margin: 2px; }
QScrollBar::handle:vertical { background: #3a2a4c; border-radius: 4px; min-height: 26px; }
QScrollBar::handle:vertical:hover { background: #4a355c; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { background: transparent; height: 9px; margin: 2px; }
QScrollBar::handle:horizontal { background: #3a2a4c; border-radius: 4px; min-width: 26px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }

QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }

QMenu { background: #171026; border: 1px solid #342543; border-radius: 8px; padding: 6px; }
QMenu::item { padding: 7px 26px 7px 12px; border-radius: 6px; color: #d9dee9; }
QMenu::item:selected { background: #352441; }
QMenu::separator { height: 1px; background: #342543; margin: 5px 8px; }

QToolTip { background: #211731; color: #f6edff; border: 1px solid #4a355c; padding: 6px 8px; border-radius: 6px; }

QDialog QLabel { color: #f6edff; }
QMessageBox { background: #0d0915; }
QMessageBox QLabel { color: #f6edff; }

QProgressBar { background: #211731; border: none; border-radius: 3px; height: 6px; text-align: center; color: transparent; }
QProgressBar::chunk { background: #ff6fa9; border-radius: 3px; }

QSplitter::handle { background: #251b34; }

QKeySequenceEdit { background: #211731; border: 1px solid #342543; border-radius: 8px; padding: 4px 8px; }
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(COLORS["bg"]))
    palette.setColor(QPalette.WindowText, QColor(COLORS["text"]))
    palette.setColor(QPalette.Base, QColor(COLORS["panel"]))
    palette.setColor(QPalette.AlternateBase, QColor(COLORS["panel2"]))
    palette.setColor(QPalette.ToolTipBase, QColor(COLORS["panel2"]))
    palette.setColor(QPalette.ToolTipText, QColor(COLORS["text"]))
    palette.setColor(QPalette.Text, QColor(COLORS["text"]))
    palette.setColor(QPalette.Button, QColor(COLORS["panel2"]))
    palette.setColor(QPalette.ButtonText, QColor(COLORS["text"]))
    palette.setColor(QPalette.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.Highlight, QColor(COLORS["accent"]))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.PlaceholderText, QColor(COLORS["dim"]))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor("#7a688f"))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#7a688f"))
    app.setPalette(palette)
    assets = Path(__file__).resolve().parent / "assets"
    qss = QSS.replace("@CHEVRON_DOWN@", (assets / "chevron_down.png").as_posix())
    qss = qss.replace("@CHEVRON_UP@", (assets / "chevron_up.png").as_posix())
    qss = qss.replace("@CHECK@", (assets / "check.png").as_posix())
    app.setStyleSheet(qss)
    font = QFont("Microsoft YaHei UI", 10)
    font.setStyleStrategy(QFont.PreferAntialias)
    app.setFont(font)


def brand_pixmap(size: int = 64) -> QPixmap:
    """RoseSI 的品牌图；找不到素材时回退到渐变占位图。"""
    asset = Path(__file__).parent / "assets" / "rose.png"
    if asset.exists():
        source = QPixmap(str(asset))
        if not source.isNull():
            return source.scaled(
                size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
    return QPixmap()


def app_icon(size: int = 64) -> QIcon:
    brand = brand_pixmap(size)
    if not brand.isNull():
        return QIcon(brand)
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    rect = QRectF(2, 2, size - 4, size - 4)
    gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
    gradient.setColorAt(0, QColor("#ff6fa9"))
    gradient.setColorAt(1, QColor("#8b7bff"))
    painter.setPen(Qt.NoPen)
    painter.setBrush(gradient)
    painter.drawRoundedRect(rect, size * 0.24, size * 0.24)
    painter.setPen(QPen(QColor(255, 255, 255, 235)))
    font = QFont("Microsoft YaHei UI", int(size * 0.42))
    font.setWeight(QFont.Bold)
    painter.setFont(font)
    painter.drawText(pm.rect().adjusted(0, -1, 0, 0), Qt.AlignCenter, "TL")
    painter.end()
    return QIcon(pm)


def apply_dark_title_bar(widget: QWidget) -> None:
    if sys.platform != "win32":
        return
    try:
        hwnd = int(widget.winId())
        dwmapi = ctypes.windll.dwmapi
        value = ctypes.c_int(1)
        for attr in (20, 19):
            result = dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)
            )
            if result == 0:
                break
    except Exception:
        pass
