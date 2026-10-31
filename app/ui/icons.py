"""用 QPainter 绘制简单的线性图标，避免依赖图标字体。"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap


def _pen(color: str, width: float = 1.7) -> QPen:
    pen = QPen(QColor(color), width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def make_icon(name: str, color: str = "#9aa3b5", size: int = 40) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.scale(size / 24.0, size / 24.0)
    painter.setPen(_pen(color))
    painter.setBrush(Qt.NoBrush)

    if name == "live":
        painter.drawEllipse(QRectF(4, 4, 16, 16))
        path = QPainterPath()
        path.moveTo(10, 8.5)
        path.lineTo(16, 12)
        path.lineTo(10, 15.5)
        path.closeSubpath()
        painter.setBrush(QColor(color))
        painter.drawPath(path)
    elif name == "terms":
        for y in (6.5, 12, 17.5):
            painter.drawLine(QPointF(7, y), QPointF(20, y))
            painter.setBrush(QColor(color))
            painter.drawEllipse(QPointF(4, y), 1.3, 1.3)
    elif name == "corpus":
        painter.drawEllipse(QRectF(4, 3.5, 16, 5))
        painter.drawLine(QPointF(4, 6), QPointF(4, 18))
        painter.drawLine(QPointF(20, 6), QPointF(20, 18))
        painter.drawArc(QRectF(4, 15.5, 16, 5), 180 * 16, 180 * 16)
        painter.drawArc(QRectF(4, 9.5, 16, 5), 180 * 16, 180 * 16)
    elif name == "history":
        painter.drawEllipse(QRectF(4, 4, 16, 16))
        painter.drawLine(QPointF(12, 7.5), QPointF(12, 12))
        painter.drawLine(QPointF(12, 12), QPointF(15.5, 14))
    elif name == "export":
        painter.drawLine(QPointF(12, 3.5), QPointF(12, 14))
        painter.drawLine(QPointF(8, 10), QPointF(12, 14))
        painter.drawLine(QPointF(16, 10), QPointF(12, 14))
        painter.drawLine(QPointF(4, 15), QPointF(4, 20))
        painter.drawLine(QPointF(4, 20), QPointF(20, 20))
        painter.drawLine(QPointF(20, 15), QPointF(20, 20))
    elif name == "settings":
        painter.drawEllipse(QRectF(8.5, 8.5, 7, 7))
        for angle in range(0, 360, 45):
            radians = math.radians(angle)
            x1 = 12 + math.cos(radians) * 6
            y1 = 12 + math.sin(radians) * 6
            x2 = 12 + math.cos(radians) * 8.5
            y2 = 12 + math.sin(radians) * 8.5
            painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
    elif name == "pin":
        painter.drawEllipse(QRectF(8.5, 4, 7, 7))
        painter.drawLine(QPointF(12, 11), QPointF(12, 20))
        painter.drawLine(QPointF(8, 20), QPointF(16, 20))
    elif name == "more":
        painter.setBrush(QColor(color))
        painter.setPen(Qt.NoPen)
        for x in (6.5, 12, 17.5):
            painter.drawEllipse(QPointF(x, 12), 1.4, 1.4)
    elif name == "close":
        painter.drawLine(QPointF(7, 7), QPointF(17, 17))
        painter.drawLine(QPointF(17, 7), QPointF(7, 17))
    elif name == "overlay":
        painter.drawRoundedRect(QRectF(3.5, 5, 17, 12), 2, 2)
        painter.drawLine(QPointF(3.5, 9), QPointF(20.5, 9))
        painter.drawLine(QPointF(8, 20), QPointF(16, 20))
    elif name == "workbench":
        painter.drawRoundedRect(QRectF(3.5, 4.5, 17, 15), 2, 2)
        painter.drawLine(QPointF(9, 4.5), QPointF(9, 19.5))
        painter.drawLine(QPointF(12, 9), QPointF(17.5, 9))
        painter.drawLine(QPointF(12, 13), QPointF(17.5, 13))
    else:
        painter.drawEllipse(QRectF(6, 6, 12, 12))
    painter.end()
    return QIcon(pixmap)
