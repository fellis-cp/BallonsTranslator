import os
import os.path as osp
import logging
from typing import Optional, List


from qtpy.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QLabel,
    QPushButton,
    QComboBox,
    QShortcut,
    QProgressDialog,
    QProgressBar,
    QMessageBox,
    QSplitter,
    QListWidget,
    QListWidgetItem,
    QApplication,
)
from qtpy.QtCore import Qt, Signal, QTimer
from qtpy.QtGui import QKeySequence, QKeyEvent, QFont

from READER.core.loader import MangaProjectData, load_manga_project
from READER.core.favorites import FAVORITES
from READER.core.translation_worker import TranslationTaskWorker
from READER.ui.manga_canvas import MangaCanvas, OverlayMode, FitMode
from READER.ui.text_panel import SideTextPanel
from READER.ui.loading_overlay import LoadingOverlay

LOGGER = logging.getLogger('READER.reader_view')


class ReaderView(QWidget):
    """Full-featured manga page viewer panel with toolbar controls, side-by-side text editor, verification status, and translation task runner."""

    back_to_library = Signal()
    open_in_translator = Signal(str)  # emits manga_dir path

    def __init__(self, parent=None):
        super().__init__(parent)
        self.project_data: Optional[MangaProjectData] = None
        self.current_page_idx: int = 0
        self.right_to_left: bool = True  # Japanese Manga standard RTL reading
        self.worker: Optional[TranslationTaskWorker] = None
        self.progress_dialog: Optional[QProgressDialog] = None
        self.loading_overlay = LoadingOverlay(self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Top Control Bar (Row 1: Navigation & Main Info)
        self.top_bar = QFrame()
        self.top_bar.setObjectName("ReaderControlBar")
        top_layout = QHBoxLayout(self.top_bar)
        top_layout.setContentsMargins(12, 6, 12, 6)
        top_layout.setSpacing(10)

        self.btn_back = QPushButton("← Library")
        self.btn_back.clicked.connect(self.back_to_library.emit)
        top_layout.addWidget(self.btn_back)

        self.btn_fav = QPushButton("☆")
        self.btn_fav.setFixedWidth(36)
        self.btn_fav.setToolTip("Toggle Favorite Status")
        self.btn_fav.clicked.connect(self._toggle_favorite)
        top_layout.addWidget(self.btn_fav)

        self.lbl_title = QLabel("No Manga Loaded")
        self.lbl_title.setObjectName("HeaderTitle")
        top_layout.addWidget(self.lbl_title, stretch=1)

        # Verification Checklist Combobox
        self.combo_status = QComboBox()
        self.combo_status.addItem("Status: Unverified", "unverified")
        self.combo_status.addItem("Status: ✓ Verified", "verified")
        self.combo_status.addItem("Status: ⚠ Needs Fix / Retranslate", "needs_fix")
        self.combo_status.currentIndexChanged.connect(self._on_status_changed)
        top_layout.addWidget(self.combo_status)

        # Translation Pipeline Action Buttons
        self.btn_trans_page = QPushButton("⚡ Translate Page")
        self.btn_trans_page.setToolTip("Run OCR & Translator pipeline on current page")
        self.btn_trans_page.clicked.connect(self.translate_current_page)
        top_layout.addWidget(self.btn_trans_page)

        self.btn_trans_vol = QPushButton("🖥 Open in BallonsTranslator")
        self.btn_trans_vol.setToolTip("Open current manga folder in the full BallonsTranslator application")
        self.btn_trans_vol.clicked.connect(self.translate_full_volume)
        top_layout.addWidget(self.btn_trans_vol)

        # Prev / Next nav buttons in top bar
        self.btn_prev = QPushButton("◀")
        self.btn_prev.setFixedWidth(32)
        self.btn_prev.setToolTip("Previous page  (A / ← / ↑)")
        self.btn_prev.clicked.connect(self.prev_page)
        top_layout.addWidget(self.btn_prev)

        # Page Counter Display
        self.lbl_page_num = QLabel("0 / 0")
        self.lbl_page_num.setStyleSheet("font-weight: bold; font-size: 14px;")
        top_layout.addWidget(self.lbl_page_num)

        self.btn_next = QPushButton("▶")
        self.btn_next.setFixedWidth(32)
        self.btn_next.setToolTip("Next page  (D / → / ↓)")
        self.btn_next.clicked.connect(self.next_page)
        top_layout.addWidget(self.btn_next)

        layout.addWidget(self.top_bar)

        # Sub-Control Bar (Row 2: Overlay, View Modes, Side Panel & Zoom)
        self.sub_bar = QFrame()
        self.sub_bar.setObjectName("ReaderControlBar")
        sub_layout = QHBoxLayout(self.sub_bar)
        sub_layout.setContentsMargins(12, 4, 12, 4)
        sub_layout.setSpacing(10)

        # Text Overlay Mode Selector
        self.combo_overlay = QComboBox()
        self.combo_overlay.addItem("💬 Translated", OverlayMode.TRANSLATED)
        self.combo_overlay.addItem("🈁 Original", OverlayMode.ORIGINAL)
        self.combo_overlay.addItem("🖼️ Clean Image", OverlayMode.RAW_ONLY)
        self.combo_overlay.currentIndexChanged.connect(self._on_overlay_changed)
        sub_layout.addWidget(self.combo_overlay)

        # Background Image Type Selector
        self.combo_bg = QComboBox()
        self.combo_bg.addItem("Inpainted Clean BG", True)
        self.combo_bg.addItem("Original Raw BG", False)
        self.combo_bg.currentIndexChanged.connect(self._on_bg_changed)
        sub_layout.addWidget(self.combo_bg)

        # Side Panel Toggle Button
        self.btn_toggle_panel = QPushButton("📋 Text Panel")
        self.btn_toggle_panel.setToolTip("Toggle Side-by-Side Original & Translated Text Panel")
        self.btn_toggle_panel.clicked.connect(self._toggle_side_panel)
        sub_layout.addWidget(self.btn_toggle_panel)

        # Fit Mode Controls
        self.btn_fit_screen = QPushButton("Fit Screen")
        self.btn_fit_screen.clicked.connect(lambda: self.canvas.set_fit_mode(FitMode.FIT_SCREEN))
        sub_layout.addWidget(self.btn_fit_screen)

        self.btn_fit_width = QPushButton("Fit Width")
        self.btn_fit_width.clicked.connect(lambda: self.canvas.set_fit_mode(FitMode.FIT_WIDTH))
        sub_layout.addWidget(self.btn_fit_width)

        self.btn_zoom_in = QPushButton("+")
        self.btn_zoom_in.setFixedWidth(32)
        self.btn_zoom_in.clicked.connect(lambda: self.canvas.zoom_in())
        sub_layout.addWidget(self.btn_zoom_in)

        self.btn_zoom_out = QPushButton("-")
        self.btn_zoom_out.setFixedWidth(32)
        self.btn_zoom_out.clicked.connect(lambda: self.canvas.zoom_out())
        sub_layout.addWidget(self.btn_zoom_out)

        self.btn_save = QPushButton("💾 Save JSON")
        self.btn_save.setObjectName("PrimaryButton")
        self.btn_save.setToolTip("Save translation changes back to .json (Ctrl+S)")
        self.btn_save.clicked.connect(self.save_project)
        sub_layout.addWidget(self.btn_save)

        layout.addWidget(self.sub_bar)

        # Page Loading Indicator Bar
        self.page_loading_bar = QProgressBar()
        self.page_loading_bar.setFixedHeight(3)
        self.page_loading_bar.setTextVisible(False)
        self.page_loading_bar.setStyleSheet(
            """
            QProgressBar {
                background-color: #0f172a;
                border: none;
            }
            QProgressBar::chunk {
                background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #38bdf8, stop:1 #2563eb);
            }
            """
        )
        self.page_loading_bar.hide()
        layout.addWidget(self.page_loading_bar)

        # Ctrl+S — save; Ctrl+T — translate current page
        self.sc_save = QShortcut(QKeySequence("Ctrl+S"), self)
        self.sc_save.activated.connect(self.save_project)

        self.sc_translate = QShortcut(QKeySequence("Ctrl+T"), self)
        self.sc_translate.activated.connect(self.translate_current_page)

        # Debounce timer for verification-status saves (avoids save-on-every-scroll)
        self._status_save_timer = QTimer(self)
        self._status_save_timer.setSingleShot(True)
        self._status_save_timer.setInterval(500)
        self._status_save_timer.timeout.connect(self._do_save_status)

        # ── Page Number Sidebar (left strip) + main content ──────────────────
        # Outer horizontal layout holds [page sidebar | main splitter]
        self.content_frame = QWidget()
        content_h_layout = QHBoxLayout(self.content_frame)
        content_h_layout.setContentsMargins(0, 0, 0, 0)
        content_h_layout.setSpacing(0)

        # Left page-number sidebar
        self.page_list = QListWidget()
        self.page_list.setObjectName("PageSidebar")
        self.page_list.setFixedWidth(58)
        self.page_list.setSpacing(2)
        self.page_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.page_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.page_list.setStyleSheet("""
            QListWidget#PageSidebar {
                background: #0d1117;
                border: none;
                border-right: 2px solid #1e293b;
            }
            QListWidget#PageSidebar::item {
                color: #94a3b8;
                font-size: 12px;
                font-weight: 600;
                text-align: center;
                padding: 6px 0px;
                border-radius: 4px;
                margin: 1px 4px;
            }
            QListWidget#PageSidebar::item:hover {
                background: #1e293b;
                color: #e2e8f0;
            }
            QListWidget#PageSidebar::item:selected {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #2563eb, stop:1 #38bdf8);
                color: #ffffff;
            }
        """)
        self.page_list.currentRowChanged.connect(self._on_page_list_clicked)
        content_h_layout.addWidget(self.page_list)

        # Main Splitter Area: Graphics Canvas & Side Text Panel
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.canvas = MangaCanvas()
        self.side_panel = SideTextPanel()

        self.main_splitter.addWidget(self.canvas)
        self.main_splitter.addWidget(self.side_panel)
        self.main_splitter.setSizes([750, 420])
        content_h_layout.addWidget(self.main_splitter, stretch=1)

        layout.addWidget(self.content_frame, stretch=1)

        # Connect Canvas & Side Panel Signals
        self.canvas.block_clicked.connect(self.side_panel.select_block)
        self.side_panel.block_selected.connect(self.canvas.highlight_block)
        self.side_panel.text_modified.connect(self._on_text_modified)
        self.side_panel.translate_page_requested.connect(self._on_panel_translate_page)
        self.side_panel.translate_block_requested.connect(self._on_panel_translate_block)

        # Reading-direction toggle (kept in sub bar area below zoom buttons)
        self.btn_reading_dir = QPushButton("📖 RTL")
        self.btn_reading_dir.setToolTip("Toggle reading direction")
        self.btn_reading_dir.clicked.connect(self._toggle_reading_dir)
        sub_layout.addWidget(self.btn_reading_dir)

    def load_manga(self, manga_dir: str, json_path: Optional[str] = None) -> None:
        """Load and display a manga volume."""
        self.loading_overlay.start_loading("Opening Manga", "Loading pages and dialogue data...")
        QApplication.processEvents()
        try:
            self.project_data = load_manga_project(manga_dir, json_path=json_path)
            self.lbl_title.setText(self.project_data.title)

            # Update favorite icon state
            self.btn_fav.setText("⭐" if FAVORITES.is_favorite(manga_dir) else "☆")

            # Update verification combobox
            status = getattr(self.project_data, 'verification_status', 'unverified')
            idx = self.combo_status.findData(status)
            if idx >= 0:
                self.combo_status.blockSignals(True)
                self.combo_status.setCurrentIndex(idx)
                self.combo_status.blockSignals(False)

            count = self.project_data.page_count
            self._build_page_sidebar(count)

            self.current_page_idx = 0
            self._show_page(0)
        finally:
            self.loading_overlay.stop_loading()

    def _toggle_side_panel(self) -> None:
        """Toggle visibility of the side-by-side text panel."""
        self.side_panel.setVisible(not self.side_panel.isVisible())

    def _toggle_favorite(self) -> None:
        if not self.project_data:
            return
        is_fav = FAVORITES.toggle_favorite(self.project_data.manga_dir)
        self.btn_fav.setText("⭐" if is_fav else "☆")

    def _on_status_changed(self) -> None:
        if not self.project_data:
            return
        new_status = self.combo_status.currentData()
        if new_status:
            self.project_data.verification_status = new_status
            # Debounce: only save 500 ms after the user stops changing
            self._status_save_timer.start()

    def _do_save_status(self) -> None:
        """Persisted save called by debounce timer after status change settles."""
        self.save_project()

    def _on_text_modified(self, block_idx: int) -> None:
        """Handle inline text edits from side panel."""
        self.canvas.reload_current_page()
        if self.project_data:
            self.lbl_title.setText(f"{self.project_data.title}  (Modified *)")

    def save_project(self) -> bool:
        """Save project dialogue updates to .json translation file."""
        if not self.project_data:
            return False
        success = self.project_data.save()
        if success:
            original_title = self.project_data.title
            self.lbl_title.setText(f"{original_title}  (Saved ✓)")
            LOGGER.info(f"Saved project JSON: {self.project_data.json_path}")
        return success

    # Translation Triggers
    def translate_current_page(self) -> None:
        if not self.project_data:
            return
        page = self.project_data.get_page(self.current_page_idx)
        if not page:
            return
        self._start_translation_task(page_names=[page.page_name])

    def translate_full_volume(self) -> None:
        """Open the current manga folder in the full BallonsTranslator application."""
        if not self.project_data:
            return
        self.open_in_translator.emit(self.project_data.manga_dir)

    def _on_panel_translate_page(self, engine: str, src: str, tgt: str) -> None:
        if not self.project_data:
            return
        page = self.project_data.get_page(self.current_page_idx)
        if page:
            self._start_translation_task(
                page_names=[page.page_name],
                engine=engine,
                src_lang=src,
                tgt_lang=tgt,
            )

    def _on_panel_translate_block(self, block_idx: int, engine: str, src: str, tgt: str) -> None:
        if not self.project_data:
            return
        page = self.project_data.get_page(self.current_page_idx)
        if page:
            self._start_translation_task(
                page_names=[page.page_name],
                target_blocks=[block_idx],
                engine=engine,
                src_lang=src,
                tgt_lang=tgt,
            )

    def _start_translation_task(
        self,
        page_names: Optional[List[str]] = None,
        target_blocks: Optional[List[int]] = None,
        engine: str = "Gemini Playwright",
        src_lang: str = "日本語",
        tgt_lang: str = "English",
    ) -> None:
        if not self.project_data:
            return

        # Cancel any in-flight worker before starting a new one
        if self.worker and self.worker.isRunning():
            self.worker.request_cancel()
            self.worker.wait()

        pages = page_names or [p.page_name for p in self.project_data.pages]

        self.loading_overlay.start_loading(
            title=f"Translating ({engine})",
            subtitle="Initializing translation pipeline...",
            total=len(pages)
        )

        self.worker = TranslationTaskWorker(
            manga_dir=self.project_data.manga_dir,
            json_path=self.project_data.json_path,
            target_pages=pages,
            target_block_indices=target_blocks,
            translator_engine=engine,
            source_lang=src_lang,
            target_lang=tgt_lang,
        )
        self.worker.progress.connect(self._on_trans_progress)
        self.worker.task_completed.connect(self._on_trans_finished)

        self.worker.start()

    def _on_trans_progress(self, current: int, total: int, msg: str) -> None:
        self.loading_overlay.update_progress(value=current, total=total, subtitle=msg)

    def _on_trans_finished(self, success: bool, msg: str) -> None:
        self.loading_overlay.stop_loading()
        if success:
            QMessageBox.information(self, "Translation Finished", msg)
            if self.project_data:
                saved_idx = self.current_page_idx
                self.load_manga(self.project_data.manga_dir, self.project_data.json_path)
                self._change_page_idx(saved_idx)
        else:
            QMessageBox.warning(self, "Translation Status", msg)

    # Page Navigation
    def prev_page(self) -> None:
        """Navigate to previous page (page index - 1)."""
        self._change_page_idx(self.current_page_idx - 1)

    def next_page(self) -> None:
        """Navigate to next page (page index + 1)."""
        self._change_page_idx(self.current_page_idx + 1)

    def go_first_page(self) -> None:
        self._change_page_idx(0)

    def go_last_page(self) -> None:
        if self.project_data:
            self._change_page_idx(self.project_data.page_count - 1)

    def _change_page_idx(self, new_idx: int) -> None:
        if not self.project_data or self.project_data.page_count == 0:
            return
        new_idx = max(0, min(self.project_data.page_count - 1, new_idx))
        if new_idx != self.current_page_idx or self.lbl_page_num.text() == "0 / 0":
            self.current_page_idx = new_idx
            self._show_page(self.current_page_idx)

    def _show_page(self, idx: int) -> None:
        if not self.project_data:
            return
        page = self.project_data.get_page(idx)
        if page:
            self.page_loading_bar.setRange(0, 100)
            self.page_loading_bar.setValue(25)
            self.page_loading_bar.show()
            QApplication.processEvents()

            self.setUpdatesEnabled(False)
            try:
                self.page_loading_bar.setValue(50)
                self.canvas.load_page(page)
                self.page_loading_bar.setValue(80)
                self.side_panel.load_page_blocks(page)
                total = self.project_data.page_count
                self.lbl_page_num.setText(f"{idx + 1} / {total}")
                self._sync_page_list(idx)
                self.page_loading_bar.setValue(100)
            finally:
                self.setUpdatesEnabled(True)
                QTimer.singleShot(250, self.page_loading_bar.hide)

    # ── Page sidebar helpers ──────────────────────────────────────────────────

    def _build_page_sidebar(self, count: int) -> None:
        """Populate the page sidebar with numbered items (1 … count)."""
        self.page_list.blockSignals(True)
        self.page_list.clear()
        for n in range(1, count + 1):
            item = QListWidgetItem(str(n))
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.page_list.addItem(item)
        self.page_list.blockSignals(False)

    def _sync_page_list(self, idx: int) -> None:
        """Highlight the sidebar row for *idx* without re-triggering navigation."""
        self.page_list.blockSignals(True)
        self.page_list.setCurrentRow(idx)
        self.page_list.blockSignals(False)
        # Ensure the selected item is visible in the scroll area
        item = self.page_list.item(idx)
        if item:
            self.page_list.scrollToItem(item)

    def _on_page_list_clicked(self, row: int) -> None:
        """Navigate to page when user clicks a sidebar row."""
        if row >= 0:
            self._change_page_idx(row)

    def _on_overlay_changed(self) -> None:
        mode = self.combo_overlay.currentData()
        if mode:
            self.canvas.set_overlay_mode(mode)

    def _on_bg_changed(self) -> None:
        use_inp = self.combo_bg.currentData()
        self.canvas.set_use_inpainted_bg(use_inp)

    def _toggle_reading_dir(self) -> None:
        self.right_to_left = not self.right_to_left
        label = "📖 RTL" if self.right_to_left else "📖 LTR"
        self.btn_reading_dir.setText(label)

    # Key Navigation
    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        if key in (Qt.Key.Key_Left, Qt.Key.Key_A, Qt.Key.Key_Up, Qt.Key.Key_PageUp):
            self.prev_page()
            event.accept()
        elif key in (Qt.Key.Key_Right, Qt.Key.Key_D, Qt.Key.Key_Down, Qt.Key.Key_PageDown):
            self.next_page()
            event.accept()
        elif key == Qt.Key.Key_Home:
            self.go_first_page()
            event.accept()
        elif key == Qt.Key.Key_End:
            self.go_last_page()
            event.accept()
        elif key in (Qt.Key.Key_Plus, Qt.Key.Key_Equal):
            self.canvas.zoom_in()
            event.accept()
        elif key in (Qt.Key.Key_Minus, Qt.Key.Key_Underscore):
            self.canvas.zoom_out()
            event.accept()
        else:
            super().keyPressEvent(event)
