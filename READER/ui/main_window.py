import os
import os.path as osp
import sys
import subprocess
import logging

from qtpy.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QStackedWidget,
    QFrame,
    QLabel,
    QPushButton,
    QFileDialog,
    QShortcut,
    QApplication,
)
from qtpy.QtCore import Qt, QSize
from qtpy.QtGui import QIcon, QKeySequence, QKeyEvent

from READER.core.scanner import MangaItem
from READER.ui.library_view import LibraryView
from READER.ui.reader_view import ReaderView
from READER.ui.styles import DARK_THEME_QSS

LOGGER = logging.getLogger('READER.main_window')


class ReaderMainWindow(QMainWindow):
    """Main Application Window for Manga Reader."""

    def __init__(self, translated_dir: str, open_manga_path: str = '', parent=None):
        super().__init__(parent)
        self.translated_dir = osp.abspath(translated_dir)

        self.setWindowTitle("BalloonsTranslator - Manga Reader")
        self.resize(1280, 850)
        self.setStyleSheet(DARK_THEME_QSS)

        # Central Widget & Stack
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # App Header Bar
        self.header = QFrame()
        self.header.setObjectName("HeaderBar")
        head_layout = QHBoxLayout(self.header)
        head_layout.setContentsMargins(16, 6, 16, 6)
        head_layout.setSpacing(12)

        self.btn_nav_library = QPushButton("📚 Manga Library")
        self.btn_nav_library.setObjectName("PrimaryButton")
        self.btn_nav_library.clicked.connect(self.show_library)
        head_layout.addWidget(self.btn_nav_library)

        app_title = QLabel("Balloons Manga Reader")
        app_title.setObjectName("HeaderTitle")
        head_layout.addWidget(app_title, stretch=1)

        self.btn_change_dir = QPushButton("📁 Change Folder")
        self.btn_change_dir.clicked.connect(self._select_custom_dir)
        head_layout.addWidget(self.btn_change_dir)

        self.btn_fullscreen = QPushButton("⛶ Fullscreen")
        self.btn_fullscreen.clicked.connect(self.toggle_fullscreen)
        head_layout.addWidget(self.btn_fullscreen)

        layout.addWidget(self.header)

        # Stacked Views (Library vs Reader)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack, stretch=1)

        # 0: Library View
        self.library_view = LibraryView(self.translated_dir)
        self.library_view.manga_selected.connect(self.open_manga_item)
        self.library_view.open_translator.connect(self.launch_translator_for_manga)
        self.stack.addWidget(self.library_view)

        # 1: Reader View
        self.reader_view = ReaderView()
        self.reader_view.back_to_library.connect(self._back_from_reader)
        self.reader_view.open_in_translator.connect(self.launch_translator_for_manga)
        self.stack.addWidget(self.reader_view)

        # Shortcuts
        self.sc_fullscreen = QShortcut(QKeySequence("F11"), self)
        self.sc_fullscreen.activated.connect(self.toggle_fullscreen)

        self.sc_esc = QShortcut(QKeySequence("Esc"), self)
        self.sc_esc.activated.connect(self._on_esc_pressed)

        # Handle initial manga path if passed
        if open_manga_path and osp.exists(open_manga_path):
            self.open_manga_by_path(open_manga_path)

    def show_library(self) -> None:
        """Go to the top-level author grid (nav-bar Library button)."""
        self.library_view.scan_library()
        self.stack.setCurrentIndex(0)
        self.header.show()

    def _back_from_reader(self) -> None:
        """Return from reader back to the author's manga grid (no rescan)."""
        self.stack.setCurrentIndex(0)
        self.header.show()
        self.library_view.return_to_author()

    def open_manga_item(self, item: MangaItem) -> None:
        self.reader_view.load_manga(item.path, json_path=item.json_path)
        self.header.hide()  # Maximise reading area
        self.stack.setCurrentIndex(1)

    def open_manga_by_path(self, manga_path: str) -> None:
        self.reader_view.load_manga(manga_path)
        self.header.hide()
        self.stack.setCurrentIndex(1)

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
            self.btn_fullscreen.setText("⛶ Fullscreen")
        else:
            self.showFullScreen()
            self.btn_fullscreen.setText("🗗 Exit Fullscreen")

    def _on_esc_pressed(self) -> None:
        if self.isFullScreen():
            self.showNormal()
            self.btn_fullscreen.setText("\u26f6 Fullscreen")
        elif self.stack.currentIndex() == 1:
            self._back_from_reader()

    def _select_custom_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Translated Manga Directory",
            self.translated_dir,
        )
        if folder and osp.exists(folder):
            self.translated_dir = osp.abspath(folder)
            self.library_view.set_root_dir(self.translated_dir)
            self.show_library()

    def launch_translator_for_manga(self, manga_dir: str) -> None:
        """Launch the main BalloonsTranslator application for a specific manga."""
        parent_root = osp.abspath(osp.join(osp.dirname(__file__), '..', '..'))
        launch_script = osp.join(parent_root, 'ballontranslator', 'launch.py')

        if osp.exists(launch_script):
            cmd = [sys.executable, launch_script, '--proj-dir', manga_dir]
            LOGGER.info(f"Launching translator command: {cmd}")
            subprocess.Popen(cmd, cwd=parent_root)
        else:
            LOGGER.warning(f"Could not locate launch script at {launch_script}")
