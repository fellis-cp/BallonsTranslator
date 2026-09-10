import logging
from typing import List, Optional, Any

from qtpy.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFrame,
    QLabel,
    QPushButton,
    QComboBox,
    QScrollArea,
    QPlainTextEdit,
    QLineEdit,
    QApplication,
    QSizePolicy,
)
from qtpy.QtCore import Qt, Signal, QSize, QTimer

from READER.core.loader import MangaPage
from READER.core.translation_worker import OCR_ENGINE_LIST, HAS_OCR_MODULES

LOGGER = logging.getLogger('READER.text_panel')

HAS_TRANSLATORS = False
# Only populated with real keys after successful import; empty = modules unavailable
TRANSLATOR_LIST: List[str] = []
try:
    import ballontranslator.modules.translators.trans_playwrigt as _tp  # noqa: F401
    from ballontranslator.modules.translators.base import TRANSLATORS
    HAS_TRANSLATORS = True
    available_keys = list(TRANSLATORS.module_dict.keys())
    if available_keys:
        TRANSLATOR_LIST = available_keys
        # Keep Gemini Playwright first when present
        if "Gemini Playwright" in TRANSLATOR_LIST:
            TRANSLATOR_LIST.remove("Gemini Playwright")
            TRANSLATOR_LIST.insert(0, "Gemini Playwright")
except ImportError:
    pass


class BlockRowCard(QFrame):
    """Side-by-side editable card for one text block (original + translation)."""

    selected = Signal(int)
    text_modified = Signal(int)
    text_committed = Signal(int, str, object, object)
    translate_requested = Signal(int)
    ocr_requested = Signal(int)
    delete_requested = Signal(int)
    style_requested = Signal(int)

    def __init__(self, block_idx: int, block: Any, parent=None):
        super().__init__(parent)
        self.block_idx = block_idx
        self.block = block
        self._is_selected = False
        self._updating_ui = False
        self._initial_orig = ""
        self._initial_trans = ""

        self._commit_timer = QTimer(self)
        self._commit_timer.setSingleShot(True)
        self._commit_timer.setInterval(600)
        self._commit_timer.timeout.connect(self._on_commit_timeout)

        self.setObjectName("BlockRowCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        # Allow the card to shrink/grow vertically with content
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        # ── Header row ──────────────────────────────────────────────────────
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)

        self.lbl_idx = QLabel(f"Block #{block_idx + 1}")
        self.lbl_idx.setStyleSheet("font-weight: bold; color: #38bdf8; font-size: 13px;")
        header_layout.addWidget(self.lbl_idx)

        rect_str = ""
        if hasattr(block, 'xyxy') and block.xyxy:
            x1, y1, x2, y2 = block.xyxy
            rect_str = f"({int(x1)}, {int(y1)}) {int(x2-x1)}×{int(y2-y1)}px"
        elif isinstance(block, dict):
            rect = block.get('_bounding_rect') or block.get('xyxy') or []
            if len(rect) == 4:
                rect_str = f"({int(rect[0])}, {int(rect[1])})"

        self.lbl_info = QLabel(rect_str)
        self.lbl_info.setStyleSheet("color: #94a3b8; font-size: 11px;")
        header_layout.addWidget(self.lbl_info, stretch=1)

        # Apply style single block button
        self.btn_style = QPushButton("🎨")
        self.btn_style.setFixedWidth(28)
        self.btn_style.setToolTip("Apply page dialogue styling to this block")
        self.btn_style.setStyleSheet(
            "padding: 2px; font-size: 11px; background: #6d28d9; color: white; border-radius: 4px;"
        )
        self.btn_style.clicked.connect(self._emit_style_requested)
        header_layout.addWidget(self.btn_style)

        # Copy translated text button
        self.btn_copy = QPushButton("📋")
        self.btn_copy.setFixedWidth(28)
        self.btn_copy.setToolTip("Copy translation to clipboard")
        self.btn_copy.setStyleSheet(
            "padding: 2px; font-size: 11px; background: #1e293b; border: 1px solid #334155;"
            " border-radius: 4px; color: #94a3b8;"
        )
        self.btn_copy.clicked.connect(self._copy_translation)
        header_layout.addWidget(self.btn_copy)

        # Quick OCR single block button
        self.btn_ocr = QPushButton("🔍")
        self.btn_ocr.setFixedWidth(28)
        self.btn_ocr.setToolTip("Run OCR on this block")
        self.btn_ocr.setStyleSheet(
            "padding: 2px; font-size: 11px; background: #0f766e; color: white; border-radius: 4px;"
        )
        self.btn_ocr.clicked.connect(self._emit_ocr_requested)
        header_layout.addWidget(self.btn_ocr)

        # Quick Translate single block button
        self.btn_trans_single = QPushButton("⚡")
        self.btn_trans_single.setFixedWidth(28)
        self.btn_trans_single.setToolTip("Translate this block")
        self.btn_trans_single.setStyleSheet(
            "padding: 2px; font-size: 11px; background: #0284c7; color: white; border-radius: 4px;"
        )
        self.btn_trans_single.clicked.connect(self._emit_translate_requested)
        header_layout.addWidget(self.btn_trans_single)

        # Delete single block button
        self.btn_del = QPushButton("🗑")
        self.btn_del.setFixedWidth(28)
        self.btn_del.setToolTip("Delete this block")
        self.btn_del.setStyleSheet(
            "padding: 2px; font-size: 11px; background: #881337; color: #fecdd3; border-radius: 4px;"
        )
        self.btn_del.clicked.connect(self._emit_delete_requested)
        header_layout.addWidget(self.btn_del)

        layout.addLayout(header_layout)

        # ── Side-by-side editors ─────────────────────────────────────────────
        editors_layout = QHBoxLayout()
        editors_layout.setSpacing(10)

        # Original column
        orig_col = QVBoxLayout()
        orig_col.setSpacing(2)
        lbl_orig = QLabel("Original")
        lbl_orig.setStyleSheet("color: #a1a1aa; font-size: 11px; font-weight: bold;")
        orig_col.addWidget(lbl_orig)

        self.txt_original = QPlainTextEdit()
        self.txt_original.setPlaceholderText("Original text…")
        self.txt_original.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.txt_original.setStyleSheet(
            "background-color: #18181b; color: #f4f4f5;"
            " border: 1px solid #3f3f46; border-radius: 4px; padding: 4px;"
        )
        orig_col.addWidget(self.txt_original)
        editors_layout.addLayout(orig_col, stretch=1)

        # Translated column
        trans_col = QVBoxLayout()
        trans_col.setSpacing(2)
        lbl_trans = QLabel("Translation")
        lbl_trans.setStyleSheet("color: #a1a1aa; font-size: 11px; font-weight: bold;")
        trans_col.addWidget(lbl_trans)

        self.txt_translated = QPlainTextEdit()
        self.txt_translated.setPlaceholderText("Translated text…")
        self.txt_translated.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self.txt_translated.setStyleSheet(
            "background-color: #18181b; color: #38bdf8;"
            " border: 1px solid #0284c7; border-radius: 4px; padding: 4px;"
        )
        trans_col.addWidget(self.txt_translated)
        editors_layout.addLayout(trans_col, stretch=1)

        layout.addLayout(editors_layout)

        self.txt_original.textChanged.connect(self._on_original_changed)
        self.txt_translated.textChanged.connect(self._on_translated_changed)
        # Auto-resize editors to content after every change
        self.txt_original.document().contentsChanged.connect(self._resize_editors)
        self.txt_translated.document().contentsChanged.connect(self._resize_editors)

        self.update_content()
        self._apply_style()

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _emit_translate_requested(self) -> None:
        """Bound slot — avoids lambda capturing self in a signal."""
        self.translate_requested.emit(self.block_idx)

    def _emit_ocr_requested(self) -> None:
        """Bound slot for OCR request."""
        self.ocr_requested.emit(self.block_idx)

    def _emit_delete_requested(self) -> None:
        """Bound slot for Delete request."""
        self.delete_requested.emit(self.block_idx)

    def _emit_style_requested(self) -> None:
        """Bound slot for applying page style to this block."""
        self.style_requested.emit(self.block_idx)

    def _on_commit_timeout(self) -> None:
        """Emit committed text changes for undo stack registration."""
        cur_orig = self.txt_original.toPlainText()
        if cur_orig != self._initial_orig:
            old_lines = self._initial_orig.split('\n')
            new_lines = cur_orig.split('\n')
            self._initial_orig = cur_orig
            self.text_committed.emit(self.block_idx, 'text', old_lines, new_lines)

        cur_trans = self.txt_translated.toPlainText()
        if cur_trans != self._initial_trans:
            old_trans = self._initial_trans
            self._initial_trans = cur_trans
            self.text_committed.emit(self.block_idx, 'translation', old_trans, cur_trans)

    def _copy_translation(self) -> None:
        text = self.txt_translated.toPlainText()
        if text:
            QApplication.clipboard().setText(text)

    def _resize_editors(self) -> None:
        """Auto-fit editor height to content (min 3 lines, max 10 lines)."""
        for editor in (self.txt_original, self.txt_translated):
            doc = editor.document()
            fm = editor.fontMetrics()
            line_h = fm.lineSpacing()
            margins = editor.contentsMargins()
            v_margin = margins.top() + margins.bottom() + 8
            lines = max(3, min(10, int(doc.size().height() / max(1, line_h))))
            new_h = lines * line_h + v_margin
            editor.setFixedHeight(new_h)

    # ── Data I/O ─────────────────────────────────────────────────────────────

    def update_content(self) -> None:
        """Refresh editor text from the block object without triggering recursive signals."""
        self._updating_ui = True
        try:
            orig_str = ""
            trans_str = ""
            if hasattr(self.block, 'text'):
                orig_str = "\n".join(self.block.text) if self.block.text else ""
            elif isinstance(self.block, dict):
                orig_str = "\n".join(self.block.get('text', []))

            if hasattr(self.block, 'translation'):
                trans_str = self.block.translation or ""
            elif isinstance(self.block, dict):
                trans_str = self.block.get('translation', "")

            if self.txt_original.toPlainText() != orig_str:
                self.txt_original.setPlainText(orig_str)
            if self.txt_translated.toPlainText() != trans_str:
                self.txt_translated.setPlainText(trans_str)

            self._initial_orig = orig_str
            self._initial_trans = trans_str
        finally:
            self._updating_ui = False
        self._resize_editors()

    def replace_block(self, block_idx: int, block: Any) -> None:
        """Update this card to display a different block in-place (avoids widget recreation)."""
        self.block_idx = block_idx
        self.block = block
        self.lbl_idx.setText(f"Block #{block_idx + 1}")
        rect_str = ""
        if hasattr(block, 'xyxy') and block.xyxy:
            x1, y1, x2, y2 = block.xyxy
            rect_str = f"({int(x1)}, {int(y1)}) {int(x2-x1)}×{int(y2-y1)}px"
        elif isinstance(block, dict):
            rect = block.get('_bounding_rect') or block.get('xyxy') or []
            if len(rect) == 4:
                rect_str = f"({int(rect[0])}, {int(rect[1])})"
        self.lbl_info.setText(rect_str)
        self.set_selected(False)
        self.update_content()

    def _on_original_changed(self) -> None:
        if self._updating_ui:
            return
        lines = self.txt_original.toPlainText().split('\n')
        if hasattr(self.block, 'text'):
            self.block.text = lines
        elif isinstance(self.block, dict):
            self.block['text'] = lines
        self.text_modified.emit(self.block_idx)
        self._commit_timer.start()

    def _on_translated_changed(self) -> None:
        if self._updating_ui:
            return
        val = self.txt_translated.toPlainText()
        if hasattr(self.block, 'translation'):
            self.block.translation = val
            if hasattr(self.block, 'rich_text'):
                self.block.rich_text = ""
        elif isinstance(self.block, dict):
            self.block['translation'] = val
            self.block['rich_text'] = ""
        self.text_modified.emit(self.block_idx)
        self._commit_timer.start()

    # ── Selection / style ────────────────────────────────────────────────────

    def set_selected(self, val: bool) -> None:
        if self._is_selected != val:
            self._is_selected = val
            self._apply_style()

    def _apply_style(self) -> None:
        if self._is_selected:
            self.setStyleSheet(
                "QFrame#BlockRowCard { background-color: #1e293b;"
                " border: 2px solid #0284c7; border-radius: 6px; }"
            )
        else:
            self.setStyleSheet(
                "QFrame#BlockRowCard { background-color: #0f172a;"
                " border: 1px solid #334155; border-radius: 6px; }"
            )

    def mousePressEvent(self, event) -> None:
        self.selected.emit(self.block_idx)
        super().mousePressEvent(event)

    def matches_filter(self, query: str) -> bool:
        """Return True if either editor text contains *query* (case-insensitive)."""
        q = query.lower()
        return (
            q in self.txt_original.toPlainText().lower()
            or q in self.txt_translated.toPlainText().lower()
        )


class SideTextPanel(QWidget):
    """Side panel with search, block count badge, OCR and translator controls, and scrollable block cards."""

    block_selected = Signal(int)
    text_modified = Signal(int)
    text_committed = Signal(int, str, object, object)
    translate_page_requested = Signal(str, str, str)       # (engine, src, tgt)
    translate_block_requested = Signal(int, str, str, str)  # (block_idx, engine, src, tgt)
    ocr_page_requested = Signal(str)                       # (ocr_engine)
    ocr_block_requested = Signal(int, str)                 # (block_idx, ocr_engine)
    add_box_clicked = Signal()
    delete_block_requested = Signal(int)
    style_block_requested = Signal(int)
    sync_style_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_page: Optional[MangaPage] = None
        # Only BlockRowCard objects; _empty_label kept separately
        self.cards: List[BlockRowCard] = []
        self._empty_label: Optional[QLabel] = None
        self.selected_block_idx: int = -1

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # ── Header with block count badge and Box action buttons ─────────────
        hdr_row = QHBoxLayout()
        lbl_header = QLabel("📋 Dialogue Blocks")
        lbl_header.setStyleSheet("font-size: 14px; font-weight: bold; color: #f8fafc;")
        hdr_row.addWidget(lbl_header, stretch=1)

        self.btn_sync_style = QPushButton("🎨 Style")
        self.btn_sync_style.setToolTip("Sync dialogue font style (font, stroke, colors) across blocks")
        self.btn_sync_style.setStyleSheet(
            "background-color: #6d28d9; color: white; font-weight: bold; border-radius: 4px; padding: 2px 8px;"
        )
        self.btn_sync_style.clicked.connect(self.sync_style_requested.emit)
        hdr_row.addWidget(self.btn_sync_style)

        self.btn_add_box = QPushButton("+ Add Box")
        self.btn_add_box.setToolTip("Click and drag on canvas to create a new text box")
        self.btn_add_box.setStyleSheet(
            "background-color: #0369a1; color: white; font-weight: bold; border-radius: 4px; padding: 2px 8px;"
        )
        self.btn_add_box.clicked.connect(self.add_box_clicked.emit)
        hdr_row.addWidget(self.btn_add_box)

        self.lbl_count = QLabel("0 blocks")
        self.lbl_count.setStyleSheet(
            "font-size: 11px; color: #94a3b8; background: #1e293b;"
            " border-radius: 8px; padding: 2px 8px;"
        )
        hdr_row.addWidget(self.lbl_count)
        layout.addLayout(hdr_row)

        # ── Search bar ───────────────────────────────────────────────────────
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("🔍 Filter blocks…")
        self.search_bar.setStyleSheet(
            "background: #18181b; color: #f4f4f5; border: 1px solid #334155;"
            " border-radius: 6px; padding: 4px 8px;"
        )
        self.search_bar.textChanged.connect(self._apply_filter)
        layout.addWidget(self.search_bar)

        # ── OCR & Translator controls ────────────────────────────────────────
        ctrl_box = QFrame()
        ctrl_box.setStyleSheet(
            "background-color: #1e293b; border-radius: 6px; border: 1px solid #334155;"
        )
        ctrl_layout = QVBoxLayout(ctrl_box)
        ctrl_layout.setContentsMargins(8, 8, 8, 8)
        ctrl_layout.setSpacing(6)

        # OCR Controls Row
        ocr_row = QHBoxLayout()
        lbl_ocr = QLabel("OCR:")
        lbl_ocr.setStyleSheet("color: #2dd4bf; font-size: 12px; font-weight: bold;")
        self.combo_ocr_engine = QComboBox()
        if OCR_ENGINE_LIST:
            for engine in OCR_ENGINE_LIST:
                self.combo_ocr_engine.addItem(engine)
        else:
            self.combo_ocr_engine.addItem("⚠ OCR not available")
            self.combo_ocr_engine.setEnabled(False)
        ocr_row.addWidget(lbl_ocr)
        ocr_row.addWidget(self.combo_ocr_engine, stretch=1)

        self.btn_ocr_sel = QPushButton("🔍 OCR Selected")
        self.btn_ocr_sel.setStyleSheet(
            "background-color: #0f766e; color: white; font-weight: bold; border-radius: 4px; padding: 3px 6px;"
        )
        self.btn_ocr_sel.clicked.connect(self._on_ocr_selected)
        ocr_row.addWidget(self.btn_ocr_sel)

        self.btn_ocr_page = QPushButton("🔍 OCR Page")
        self.btn_ocr_page.setStyleSheet(
            "background-color: #115e59; color: white; font-weight: bold; border-radius: 4px; padding: 3px 6px;"
        )
        self.btn_ocr_page.clicked.connect(self._on_ocr_page)
        ocr_row.addWidget(self.btn_ocr_page)

        ctrl_layout.addLayout(ocr_row)

        # Separator line
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #334155; max-height: 1px;")
        ctrl_layout.addWidget(sep)

        # Translator Engine selector
        t_row = QHBoxLayout()
        lbl_engine = QLabel("Translate:")
        lbl_engine.setStyleSheet("color: #38bdf8; font-size: 12px; font-weight: bold;")
        self.combo_engine = QComboBox()
        if TRANSLATOR_LIST:
            for engine in TRANSLATOR_LIST:
                self.combo_engine.addItem(engine)
        else:
            self.combo_engine.addItem("⚠ Modules not available")
            self.combo_engine.setEnabled(False)
        t_row.addWidget(lbl_engine)
        t_row.addWidget(self.combo_engine, stretch=1)
        ctrl_layout.addLayout(t_row)

        # Language selectors
        lang_row = QHBoxLayout()
        lbl_src = QLabel("From:")
        lbl_src.setStyleSheet("color: #94a3b8; font-size: 12px;")
        self.combo_src = QComboBox()
        self.combo_src.addItems(["日本語", "Auto", "English", "简体中文", "한국어"])

        lbl_tgt = QLabel("To:")
        lbl_tgt.setStyleSheet("color: #94a3b8; font-size: 12px;")
        self.combo_tgt = QComboBox()
        self.combo_tgt.addItems(["English", "Bahasa Indonesia", "简体中文", "繁體中文", "日本語", "한국어"])

        lang_row.addWidget(lbl_src)
        lang_row.addWidget(self.combo_src)
        lang_row.addWidget(lbl_tgt)
        lang_row.addWidget(self.combo_tgt)
        ctrl_layout.addLayout(lang_row)

        # Translation Action buttons
        btn_row = QHBoxLayout()
        self.btn_trans_sel = QPushButton("⚡ Translate Selected")
        self.btn_trans_sel.setStyleSheet(
            "background-color: #0284c7; color: white; font-weight: bold;"
            " border-radius: 4px; padding: 4px 8px;"
        )
        self.btn_trans_sel.clicked.connect(self._on_translate_selected)
        btn_row.addWidget(self.btn_trans_sel)

        self.btn_trans_page = QPushButton("⚡ Translate Page")
        self.btn_trans_page.setStyleSheet(
            "background-color: #2563eb; color: white; font-weight: bold;"
            " border-radius: 4px; padding: 4px 8px;"
        )
        self.btn_trans_page.clicked.connect(self._on_translate_page)
        btn_row.addWidget(self.btn_trans_page)

        ctrl_layout.addLayout(btn_row)
        layout.addWidget(ctrl_box)

        # ── Scroll area for block cards ───────────────────────────────────────
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet(
            "QScrollArea { border: 1px solid #334155; border-radius: 6px; background: #090d16; }"
        )

        self.container_widget = QWidget()
        self.container_layout = QVBoxLayout(self.container_widget)
        self.container_layout.setContentsMargins(6, 6, 6, 6)
        self.container_layout.setSpacing(8)
        self.container_layout.addStretch()

        self.scroll_area.setWidget(self.container_widget)
        layout.addWidget(self.scroll_area, stretch=1)

    # ── Page loading (in-place diff) ─────────────────────────────────────────

    def load_page_blocks(self, page: MangaPage) -> None:
        """Populate block cards using an in-place diff to avoid full widget recreation."""
        self.current_page = page
        self.selected_block_idx = -1
        self.search_bar.blockSignals(True)
        self.search_bar.clear()
        self.search_bar.blockSignals(False)

        blocks = page.blocks if (page and page.blocks) else []
        self.lbl_count.setText(f"{len(blocks)} block{'s' if len(blocks) != 1 else ''}")

        self.setUpdatesEnabled(False)
        try:
            self._sync_empty_label(len(blocks) == 0)
            if not blocks:
                return

            new_count = len(blocks)
            old_count = len(self.cards)

            # Reuse existing cards (update in-place)
            for i in range(min(old_count, new_count)):
                self.cards[i].replace_block(i, blocks[i])

            # Add new cards for extra blocks
            for i in range(old_count, new_count):
                card = BlockRowCard(block_idx=i, block=blocks[i])
                card.selected.connect(self._on_card_selected)
                card.text_modified.connect(self.text_modified.emit)
                card.text_committed.connect(self.text_committed.emit)
                card.translate_requested.connect(self._on_single_block_translate)
                card.ocr_requested.connect(self._on_single_block_ocr)
                card.delete_requested.connect(self.delete_block_requested.emit)
                card.style_requested.connect(self.style_block_requested.emit)
                self.cards.append(card)
                # Insert before the trailing stretch (last item)
                self.container_layout.insertWidget(i, card)

            # Remove excess cards when new page has fewer blocks
            while len(self.cards) > new_count:
                card = self.cards.pop()
                self.container_layout.removeWidget(card)
                card.deleteLater()
        finally:
            self.setUpdatesEnabled(True)

    def _sync_empty_label(self, show: bool) -> None:
        """Show or hide the 'no blocks' placeholder label."""
        if show:
            if self._empty_label is None:
                self._empty_label = QLabel("No dialogue text blocks on this page.\nClick '+ Add Box' to create one.")
                self._empty_label.setStyleSheet("color: #64748b; font-style: italic; padding: 16px;")
                self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.container_layout.insertWidget(0, self._empty_label)
            self._empty_label.show()
            for card in self.cards:
                card.hide()
        else:
            if self._empty_label is not None:
                self._empty_label.hide()
            for card in self.cards:
                card.show()

    # ── Block selection ───────────────────────────────────────────────────────

    def select_block(self, idx: int) -> None:
        """Highlight specified block and scroll it into view."""
        self.selected_block_idx = idx
        target_card: Optional[BlockRowCard] = None
        for card in self.cards:
            is_sel = card.block_idx == idx
            card.set_selected(is_sel)
            if is_sel:
                target_card = card
        if target_card:
            self.scroll_area.ensureWidgetVisible(target_card)

    def _on_card_selected(self, idx: int) -> None:
        self.select_block(idx)
        self.block_selected.emit(idx)

    # ── Filter ────────────────────────────────────────────────────────────────

    def _apply_filter(self, query: str) -> None:
        """Show/hide cards based on the search query."""
        for card in self.cards:
            card.setVisible(card.matches_filter(query) if query else True)

    # ── OCR actions ──────────────────────────────────────────────────────────

    def _on_ocr_page(self) -> None:
        self.ocr_page_requested.emit(self.combo_ocr_engine.currentText())

    def _on_ocr_selected(self) -> None:
        if self.selected_block_idx >= 0:
            self._on_single_block_ocr(self.selected_block_idx)

    def _on_single_block_ocr(self, idx: int) -> None:
        self.ocr_block_requested.emit(idx, self.combo_ocr_engine.currentText())

    # ── Translation actions ───────────────────────────────────────────────────

    def _on_translate_page(self) -> None:
        self.translate_page_requested.emit(
            self.combo_engine.currentText(),
            self.combo_src.currentText(),
            self.combo_tgt.currentText(),
        )

    def _on_translate_selected(self) -> None:
        if self.selected_block_idx >= 0:
            self._on_single_block_translate(self.selected_block_idx)

    def _on_single_block_translate(self, idx: int) -> None:
        self.translate_block_requested.emit(
            idx,
            self.combo_engine.currentText(),
            self.combo_src.currentText(),
            self.combo_tgt.currentText(),
        )
