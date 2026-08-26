from __future__ import annotations

from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class TopologyView(QWidget):
    def paintEvent(self, event) -> None:  # type: ignore[override]
        del event
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#0d141c"))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        pen = QPen(QColor("#2f93d1"))
        pen.setWidth(2)
        painter.setPen(pen)

        height = self.height()
        width = self.width()
        left_x = 80
        center_x = width // 2
        right_x = width - 80
        y = height // 2

        painter.drawEllipse(left_x - 30, y - 30, 60, 60)
        painter.drawText(left_x - 20, y + 50, "Host")

        for offset, label in [(-60, "VPN-A"), (0, "VPN-B"), (60, "VPN-C")]:
            painter.drawLine(left_x + 30, y, center_x - 35, y + offset)
            painter.drawEllipse(center_x - 35, y + offset - 20, 70, 40)
            painter.drawText(center_x - 20, y + offset + 5, label)
            painter.drawLine(center_x + 35, y + offset, right_x - 30, y + offset)
            painter.drawEllipse(right_x - 30, y + offset - 25, 60, 50)
            painter.drawText(right_x - 18, y + offset + 5, "Peer")
