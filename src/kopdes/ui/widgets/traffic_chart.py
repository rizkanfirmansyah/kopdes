from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget


class TrafficChartWidget(QWidget):
    def __init__(self, title: str = "Traffic Trend") -> None:
        super().__init__()
        self._title = title
        self._upload_history: list[float] = []
        self._download_history: list[float] = []
        self.setMinimumHeight(160)

    def set_series(self, upload_history: list[float], download_history: list[float]) -> None:
        self._upload_history = upload_history
        self._download_history = download_history
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = self.rect().adjusted(8, 8, -8, -8)
        painter.fillRect(self.rect(), QColor("#101720"))

        painter.setPen(QPen(QColor("#223242"), 1))
        for step in range(1, 5):
            y = rect.top() + step * rect.height() / 5
            painter.drawLine(rect.left(), int(y), rect.right(), int(y))

        title_pen = QPen(QColor("#dce8f2"))
        painter.setPen(title_pen)
        painter.drawText(rect.adjusted(0, 0, 0, -rect.height() + 20), Qt.AlignmentFlag.AlignLeft, self._title)

        self._draw_series(painter, rect.adjusted(0, 24, 0, 0), self._download_history, QColor("#27e08a"), fill=True)
        self._draw_series(painter, rect.adjusted(0, 24, 0, 0), self._upload_history, QColor("#f6a63c"), fill=False)

    def _draw_series(
        self,
        painter: QPainter,
        rect,
        values: list[float],
        color: QColor,
        fill: bool,
    ) -> None:
        if len(values) < 2:
            return
        peak = max(max(values), 1.0)
        points: list[QPointF] = []
        for index, value in enumerate(values):
            x = rect.left() + (rect.width() * index / max(len(values) - 1, 1))
            y = rect.bottom() - (rect.height() * (value / peak))
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
            gradient.setColorAt(0.0, QColor(color.red(), color.green(), color.blue(), 90))
            gradient.setColorAt(1.0, QColor(color.red(), color.green(), color.blue(), 8))
            painter.fillPath(fill_path, gradient)
        painter.setPen(QPen(color, 2))
        painter.drawPath(path)
