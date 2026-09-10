"""
Styles and CSS design system for Manga Reader.
"""

DARK_THEME_QSS = """
/* Global Application Style */
QWidget {
    background-color: #161822;
    color: #e2e8f0;
    font-family: 'Segoe UI', 'Microsoft YaHei UI', Ubuntu, sans-serif;
    font-size: 13px;
}

/* Header and Navigation Bar */
QFrame#HeaderBar {
    background-color: #1e2230;
    border-bottom: 1px solid #2d3348;
    min-height: 48px;
    max-height: 48px;
}

QLabel#HeaderTitle {
    font-size: 16px;
    font-weight: bold;
    color: #60a5fa;
}

QLabel#HeaderSubtitle {
    font-size: 11px;
    color: #94a3b8;
}

/* Buttons */
QPushButton {
    background-color: #262b3d;
    color: #f1f5f9;
    border: 1px solid #3b4259;
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #323850;
    border-color: #3b82f6;
    color: #ffffff;
}

QPushButton:pressed {
    background-color: #1d4ed8;
    border-color: #1d4ed8;
}

QPushButton#PrimaryButton {
    background-color: #2563eb;
    border: 1px solid #3b82f6;
    color: #ffffff;
    font-weight: 600;
}

QPushButton#PrimaryButton:hover {
    background-color: #1d4ed8;
    border-color: #60a5fa;
}

QPushButton#IconButton {
    background-color: transparent;
    border: none;
    border-radius: 4px;
    padding: 4px;
}

QPushButton#IconButton:hover {
    background-color: #2d3348;
}

/* Line Edit / Search Bar */
QLineEdit {
    background-color: #1e2230;
    border: 1px solid #3b4259;
    border-radius: 6px;
    padding: 6px 12px;
    color: #f8fafc;
    selection-background-color: #2563eb;
}

QLineEdit:focus {
    border-color: #3b82f6;
}

/* Combo Box */
QComboBox {
    background-color: #1e2230;
    border: 1px solid #3b4259;
    border-radius: 6px;
    padding: 5px 10px;
    color: #f8fafc;
}

QComboBox:hover {
    border-color: #3b82f6;
}

QComboBox::drop-down {
    border: none;
    width: 20px;
}

QComboBox QAbstractItemView {
    background-color: #1e2230;
    border: 1px solid #3b4259;
    selection-background-color: #2563eb;
    color: #f8fafc;
}

/* Slider */
QSlider::groove:horizontal {
    border: none;
    height: 6px;
    background: #2d3348;
    border-radius: 3px;
}

QSlider::sub-page:horizontal {
    background: #3b82f6;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background: #60a5fa;
    border: 2px solid #ffffff;
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
}

QSlider::handle:horizontal:hover {
    background: #93c5fd;
}

/* ScrollBars */
QScrollBar:vertical {
    border: none;
    background: #161822;
    width: 10px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background: #2d3348;
    min-height: 20px;
    border-radius: 5px;
}

QScrollBar::handle:vertical:hover {
    background: #3b82f6;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QScrollBar:horizontal {
    border: none;
    background: #161822;
    height: 10px;
    margin: 0px;
}

QScrollBar::handle:horizontal {
    background: #2d3348;
    min-width: 20px;
    border-radius: 5px;
}

QScrollBar::handle:horizontal:hover {
    background: #3b82f6;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* Manga Library Card Grid */
QScrollArea {
    border: none;
    background-color: transparent;
}

QFrame#MangaCard {
    background-color: #1e2230;
    border: 1px solid #2d3348;
    border-radius: 8px;
}

QFrame#MangaCard:hover {
    border-color: #3b82f6;
    background-color: #24293a;
}

QLabel#CardTitle {
    font-size: 13px;
    font-weight: 600;
    color: #f1f5f9;
}

QLabel#CardMeta {
    font-size: 11px;
    color: #94a3b8;
}

QLabel#Badge {
    background-color: #1e3a8a;
    color: #93c5fd;
    border-radius: 4px;
    padding: 2px 6px;
    font-size: 10px;
    font-weight: 600;
}

/* Graphics View / Canvas */
QGraphicsView {
    border: none;
    background-color: #0d0f17;
}

/* ToolBar and Floating Control Bars */
QFrame#ReaderControlBar {
    background-color: rgba(30, 34, 48, 0.92);
    border: 1px solid #2d3348;
    border-radius: 8px;
}

QToolTip {
    background-color: #1e2230;
    color: #ffffff;
    border: 1px solid #3b82f6;
    padding: 4px 8px;
    border-radius: 4px;
}
"""
