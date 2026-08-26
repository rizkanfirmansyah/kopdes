from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QStyledItemDelegate


class TrafficChartDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option, index) -> None:  # type: ignore[override]
        upload = index.data(Qt.ItemDataRole.UserRole + 1) or []
        download = index.data(Qt.ItemDataRole.UserRole + 2) or []
        painter.save()
        rect = option.rect.adjusted(6, 6, -6, -6)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(option.rect, QColor("#121a24"))
        self._draw_series(painter, rect, download, QColor("#2ce598"), fill=True)
        self._draw_series(painter, rect, upload, QColor("#f9a23f"), fill=False)
        painter.restore()

    def _draw_series(self, painter: QPainter, rect, values: list[float], color: QColor, fill: bool) -> None:
        if len(values) < 2:
            painter.setPen(QPen(QColor("#2b3a47"), 1))
            painter.drawRoundedRect(rect, 4, 4)
            return
        peak = max(max(values), 1.0)
        points: list[QPointF] = []
        for index, value in enumerate(values):
            x = rect.left() + rect.width() * index / max(len(values) - 1, 1)
            y = rect.bottom() - rect.height() * (value / peak)
            points.append(QPointF(x, y))
        path = QPainterPath(points[0])
        for point in points[1:]:
            path.lineTo(point)
        if fill:
            fill_path = QPainterPath(path)
            fill_path.lineTo(points[-1].x(), rect.bottom())
            fill_path.lineTo(points[0].x(), rect.bottom())
            fill_path.closeSubpath()
            gradient = QLinearGradient(rect.left(), rect.top(), rect.left(), rect.bottom())
            gradient.setColorAt(0.0, QColor(color.red(), color.green(), color.blue(), 80))
            gradient.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), 8))
            painter.fillPath(fill_path, gradient)
        painter.setPen(QPen(color, 1.8))
        painter.drawPath(path)
