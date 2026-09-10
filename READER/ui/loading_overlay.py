import math
import logging
from typing import Optional

from qtpy.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QProgressBar,
    QGraphicsDropShadowEffect,
    QFrame,
)
from qtpy.QtCore import Qt, QTimer, QRectF, QEvent
from qtpy.QtGui import QPainter, QColor, QPen, QBrush, QFont, QConicalGradient

LOGGER = logging.getLogger('READER.loading_overlay')


class SpinnerWidget(QWidget):
    """Custom smooth rotating arc loader widget."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(54, 54)
        self._angle = 0
        self._timer = QTimer(self)
        self._timer.setInterval(16)  # ~60 FPS
        self._timer.timeout.connect(self._rotate)

    def start(self) -> None:
        if not self._timer.isActive():
            self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def _rotate(self) -> None:
        self._angle = (self._angle + 6) % 360
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        rect = QRectF(4, 4, w - 8, h - 8)

        # Track Ring
        pen_bg = QPen(QColor(51, 65, 85, 120), 4)
        painter.setPen(pen_bg)
        painter.drawEllipse(rect)

        # Rotating Gradient Arc
        pen_arc = QPen(QColor(56, 189, 248), 4)
        pen_arc.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen_arc)

        # Draw 120-degree spinning arc
        start_angle = int(-self._angle * 16)
        span_angle = int(120 * 16)
        painter.drawArc(rect, start_angle, span_angle)
        painter.end()


class LoadingOverlay(QWidget):
    """Sleek semi-transparent loading overlay with spinner ring and progress status."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LoadingOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.hide()

        # Dark overlay background
        self.setStyleSheet("background-color: rgba(13, 15, 23, 0.82);")

        main_layout = QVBoxLayout(self)
        main_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Centered Dialog Card
        self.card = QFrame()
        self.card.setFixedSize(360, 200)
        self.card.setStyleSheet(
            """
            QFrame {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 12px;
            }
            """
        )

        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(24)
        shadow.setColor(QColor(0, 0, 0, 160))
        shadow.setOffset(0, 6)
        self.card.setGraphicsEffect(shadow)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(24, 24, 24, 24)
        card_layout.setSpacing(12)
        card_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Spinner
        self.spinner = SpinnerWidget()
        card_layout.addWidget(self.spinner, alignment=Qt.AlignmentFlag.AlignCenter)

        # Title Text
        self.lbl_title = QLabel("Loading...")
        self.lbl_title.setStyleSheet("color: #f8fafc; font-size: 15px; font-weight: bold; border: none;")
        self.lbl_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.lbl_title)

        # Subtitle Status Text
        self.lbl_subtitle = QLabel("")
        self.lbl_subtitle.setStyleSheet("color: #94a3b8; font-size: 12px; border: none;")
        self.lbl_subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_subtitle.setWordWrap(True)
        card_layout.addWidget(self.lbl_subtitle)

        # Progress Bar (Shown for multi-item tasks)
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setStyleSheet(
            """
            QProgressBar {
                background-color: #0f172a;
                border-radius: 3px;
                border: none;
            }
            QProgressBar::chunk {
                background-color: #0284c7;
                border-radius: 3px;
            }
            """
        )
        self.progress_bar.hide()
        card_layout.addWidget(self.progress_bar)

        main_layout.addWidget(self.card)

        if parent:
            parent.installEventFilter(self)
            self.resize(parent.size())

    def start_loading(self, title: str = "Loading...", subtitle: str = "", total: int = 0) -> None:
        """Show loading overlay and start spinner animation."""
        self.lbl_title.setText(title)
        self.lbl_subtitle.setText(subtitle)
        
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(0)
            self.progress_bar.show()
            self.card.setFixedHeight(220)
        else:
            self.progress_bar.hide()
            self.card.setFixedHeight(190)

        if self.parentWidget():
            self.resize(self.parentWidget().size())

        self.raise_()
        self.show()
        self.spinner.start()

    def update_progress(self, value: int, total: int, subtitle: Optional[str] = None) -> None:
        """Update progress bar value and status text."""
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(value)
            self.progress_bar.show()
            self.card.setFixedHeight(220)
        
        if subtitle is not None:
            self.lbl_subtitle.setText(subtitle)

    def stop_loading(self) -> None:
        """Hide overlay and stop spinner animation."""
        self.spinner.stop()
        self.hide()

    def eventFilter(self, watched, event) -> bool:
        if watched is not self.parentWidget():
            return super().eventFilter(watched, event)
        if event.type() == QEvent.Resize:
            self.resize(watched.size())
        return super().eventFilter(watched, event)
