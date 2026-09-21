import os
import os.path as osp
import sys
import subprocess
import logging
import json
from typing import List, Optional, Union

from qtpy.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QLabel,
    QPushButton,
    QFileDialog,
    QShortcut,
    QApplication,
    QComboBox,
    QInputDialog,
    QLineEdit,
    QMessageBox,
)
from qtpy.QtCore import Qt, QSize, QTimer
from qtpy.QtGui import QIcon, QKeySequence, QKeyEvent

from READER.core.scanner import DEFAULT_LANGUAGE, MangaItem, normalize_language
from READER.ui.library_view import LibraryView
from READER.ui.loading_overlay import LoadingOverlay
from READER.ui.styles import DARK_THEME_QSS

LOGGER = logging.getLogger('READER.main_window')


class ReaderMainWindow(QMainWindow):
    """Main Application Window for Manga Library & Translator Launcher."""

    def __init__(self, translated_dir: str, open_manga_path: str = '', parent=None):
        super().__init__(parent)
        self.translated_dir = osp.abspath(translated_dir)
        self.language = DEFAULT_LANGUAGE
        self._launch_timer: Optional[QTimer] = None

        self.setWindowTitle("BalloonsTranslator - Manga Library")
        self.resize(1280, 850)
        self.setStyleSheet(DARK_THEME_QSS)

        # Central Widget
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

        app_title = QLabel("Balloons Manga Library")
        app_title.setObjectName("HeaderTitle")
        head_layout.addWidget(app_title, stretch=1)

        head_layout.addWidget(QLabel("Language"))
        self.language_combo = QComboBox()
        self.language_combo.addItem("English", "ENG")
        self.language_combo.addItem("Bahasa Indonesia", "IND")
        self.language_combo.currentIndexChanged.connect(self._on_language_changed)
        head_layout.addWidget(self.language_combo)

        self.btn_change_dir = QPushButton("📁 Change Folder")
        self.btn_change_dir.clicked.connect(self._select_custom_dir)
        head_layout.addWidget(self.btn_change_dir)

        self.btn_batch_selected = QPushButton("Batch Selected")
        self.btn_batch_selected.setEnabled(False)
        self.btn_batch_selected.clicked.connect(self._on_batch_selected_clicked)
        head_layout.addWidget(self.btn_batch_selected)

        self.btn_fullscreen = QPushButton("⛶ Fullscreen")
        self.btn_fullscreen.clicked.connect(self.toggle_fullscreen)
        head_layout.addWidget(self.btn_fullscreen)

        layout.addWidget(self.header)

        # Library View
        self.library_view = LibraryView(self.translated_dir, language=self.language)
        self.library_view.manga_selected.connect(self.open_manga_item)
        self.library_view.open_translator.connect(self.launch_translator_for_manga)
        self.library_view.batch_render_requested.connect(self.batch_render_manga_items)
        self.library_view.selection_changed.connect(self._on_selection_changed)
        layout.addWidget(self.library_view, stretch=1)

        # Global Loading Overlay
        self.loading_overlay = LoadingOverlay(self)

        # Shortcuts
        self.sc_fullscreen = QShortcut(QKeySequence("F11"), self)
        self.sc_fullscreen.activated.connect(self.toggle_fullscreen)

        self.sc_esc = QShortcut(QKeySequence("Esc"), self)
        self.sc_esc.activated.connect(self._on_esc_pressed)

        # Handle initial manga path if passed
        if open_manga_path and osp.exists(open_manga_path):
            self.launch_translator_for_manga(open_manga_path)

    def show_library(self) -> None:
        """Go to the top-level author grid (nav-bar Library button)."""
        self.library_view.scan_library()

    def open_manga_item(self, item: MangaItem) -> None:
        """Open picked manga directly in BalloonsTranslator."""
        self.launch_translator_for_manga(item.json_path or item.path)

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
            self.btn_fullscreen.setText("⛶ Fullscreen")

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

    def _on_language_changed(self) -> None:
        self.language = normalize_language(self.language_combo.currentData())
        self.library_view.set_language(self.language)
        self._on_selection_changed(0)

    def _on_selection_changed(self, count: int) -> None:
        self.btn_batch_selected.setEnabled(count > 0)
        self.btn_batch_selected.setText(
            f"Batch Selected ({count})" if count else "Batch Selected"
        )

    def _on_batch_selected_clicked(self) -> None:
        self.batch_render_manga_items(self.library_view.selected_items())

    def launch_translator_for_manga(self, manga_dir: str) -> None:
        """Launch the main BalloonsTranslator application for a specific manga."""
        parent_root = osp.abspath(osp.join(osp.dirname(__file__), '..', '..'))
        launch_script = osp.join(parent_root, 'ballontranslator', 'launch.py')

        if not osp.exists(launch_script):
            LOGGER.warning(f"Could not locate launch script at {launch_script}")
            return

        project_path = osp.abspath(manga_dir)
        display_path = project_path
        if osp.isfile(project_path):
            display_path = osp.dirname(project_path)
            if osp.basename(display_path).upper() in {"ENG", "IND"}:
                display_path = osp.dirname(display_path)
        manga_name = osp.basename(display_path.rstrip('/\\')) or "Manga"
        self.loading_overlay.start_loading(
            title="Opening BalloonsTranslator",
            subtitle=f"Launching workspace for '{manga_name}'...",
        )
        QApplication.processEvents()

        try:
            cmd = [sys.executable, launch_script, '--proj-dir', project_path]
            LOGGER.info(f"Launching translator command: {cmd}")
            subprocess.Popen(cmd, cwd=parent_root)
        except Exception as e:
            LOGGER.error(f"Failed to launch translator: {e}", exc_info=True)
            self.loading_overlay.stop_loading()
            return

        if self._launch_timer is not None:
            self._launch_timer.stop()

        self._launch_timer = QTimer(self)
        self._launch_timer.setSingleShot(True)
        self._launch_timer.timeout.connect(self._on_launch_completed)
        self._launch_timer.start(2200)

    def batch_render_manga_items(self, items: List[MangaItem]) -> None:
        project_paths = []
        seen = set()
        for item in items:
            project_path = osp.abspath(item.json_path or item.path)
            if project_path not in seen and osp.exists(project_path):
                seen.add(project_path)
                project_paths.append(project_path)

        if not project_paths:
            QMessageBox.warning(
                self,
                "Batch Translate",
                "Select one or more manga first.",
            )
            return

        default_target = "Bahasa Indonesia" if self.language == "IND" else "English"
        target_language, accepted = QInputDialog.getText(
            self,
            "Batch Translate Target",
            f"Target language for {len(project_paths)} selected manga:",
            getattr(QLineEdit, 'EchoMode', QLineEdit).Normal,
            default_target,
        )
        if not accepted or not target_language.strip():
            return
        target_language = target_language.strip()

        font_modes = [
            "Use current manga font settings",
            "Set one font size for all selected manga",
        ]
        font_mode, accepted = QInputDialog.getItem(
            self,
            "Batch Translate Font Mode",
            "Font handling:",
            font_modes,
            0,
            False,
        )
        if not accepted:
            return

        preserve_font_settings = font_mode == font_modes[0]
        font_size = None
        if not preserve_font_settings:
            font_size, accepted = QInputDialog.getDouble(
                self,
                "Batch Translate Font Size",
                "Font size:",
                24.0,
                1.0,
                1000.0,
                1,
            )
            if not accepted:
                return

        instance_options = [str(value) for value in range(1, min(3, len(project_paths)) + 1)]
        instance_count_text, accepted = QInputDialog.getItem(
            self,
            "Batch Translate Instances",
            "BalloonsTranslator instances:",
            instance_options,
            0,
            False,
        )
        if not accepted:
            return

        self.launch_batch_translate(
            project_paths,
            target_language,
            font_size,
            int(instance_count_text),
            preserve_font_settings=preserve_font_settings,
        )

    def launch_batch_translate(
        self,
        project_paths: List[str],
        target_language: str,
        font_size: Optional[float],
        instance_count: int = 1,
        preserve_font_settings: bool = False,
    ) -> None:
        parent_root = osp.abspath(osp.join(osp.dirname(__file__), '..', '..'))
        launch_script = osp.join(parent_root, 'ballontranslator', 'launch.py')

        if not osp.exists(launch_script):
            LOGGER.warning(f"Could not locate launch script at {launch_script}")
            return

        instance_count = max(1, min(3, int(instance_count), len(project_paths)))
        path_groups = [
            project_paths[index::instance_count]
            for index in range(instance_count)
        ]

        self.loading_overlay.start_loading(
            title="Batch Translating",
            subtitle=(
                f"Opening {len(project_paths)} selected manga "
                f"in {instance_count} instance(s)..."
            ),
        )
        QApplication.processEvents()

        try:
            for group in path_groups:
                if not group:
                    continue
                cmd = [
                    sys.executable,
                    launch_script,
                    '--exec-paths-json',
                    json.dumps(group),
                    '--batch-translate-target',
                    target_language,
                ]
                if preserve_font_settings:
                    cmd.append('--batch-preserve-font-settings')
                elif font_size is not None:
                    cmd.extend(['--batch-font-size', str(font_size)])
                LOGGER.info(f"Launching batch translate command: {cmd}")
                subprocess.Popen(cmd, cwd=parent_root)
        except Exception as e:
            LOGGER.error(f"Failed to launch batch translate: {e}", exc_info=True)
            self.loading_overlay.stop_loading()
            return

        if self._launch_timer is not None:
            self._launch_timer.stop()

        self._launch_timer = QTimer(self)
        self._launch_timer.setSingleShot(True)
        self._launch_timer.timeout.connect(self._on_launch_completed)
        self._launch_timer.start(2200)

    def _on_launch_completed(self) -> None:
        self.loading_overlay.stop_loading()
