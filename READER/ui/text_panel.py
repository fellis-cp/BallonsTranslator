import logging
from typing import List, Optional, Dict, Any

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
    QSplitter,
    QStyle,
    QApplication,
)
from qtpy.QtCore import Qt, Signal

from READER.core.loader import MangaPage

LOGGER = logging.getLogger('READER.text_panel')

HAS_TRANSLATORS = False
TRANSLATOR_LIST = ["Gemini Playwright", "google", "Copy Source", "LLMTranslator"]
try:
    import ballontranslator.modules.translators.trans_playwrigt as _tp
    from ballontranslator.modules.translators.base import TRANSLATORS
    HAS_TRANSLATORS = True
    available_keys = list(TRANSLATORS.module_dict.keys())
    if available_keys:
        TRANSLATOR_LIST = available_keys
        # Ensure Gemini Playwright is first if present
        if "Gemini Playwright" in TRANSLATOR_LIST:
            TRANSLATOR_LIST.remove("Gemini Playwright")
            TRANSLATOR_LIST.insert(0, "Gemini Playwright")
except ImportError:
    pass


class BlockRowCard(QFrame):
    """Side-by-side text block row showing original and translated text side-by-side."""

    selected = Signal(int)
    text_modified = Signal(int)
    translate_requested = Signal(int)

    def __init__(self, block_idx: int, block: Any, parent=None):
        super().__init__(parent)
        self.block_idx = block_idx
        self.block = block
        self._is_selected = False
        self._updating_ui = False

        self.setObjectName("BlockRowCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)

        # Header Row: Block Number, Info, Single-Block Translate
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)

        self.lbl_idx = QLabel(f"Block #{block_idx + 1}")
        self.lbl_idx.setStyleSheet("font-weight: bold; color: #38bdf8; font-size: 13px;")
        header_layout.addWidget(self.lbl_idx)

        rect_str = ""
        if hasattr(block, 'xyxy') and block.xyxy:
            x1, y1, x2, y2 = block.xyxy
            rect_str = f"({int(x1)}, {int(y1)}) {int(x2-x1)}x{int(y2-y1)}px"
        elif isinstance(block, dict):
            rect = block.get('_bounding_rect') or block.get('xyxy') or []
            if len(rect) == 4:
                rect_str = f"({int(rect[0])}, {int(rect[1])})"

        self.lbl_info = QLabel(rect_str)
        self.lbl_info.setStyleSheet("color: #94a3b8; font-size: 11px;")
        header_layout.addWidget(self.lbl_info, stretch=1)

        self.btn_trans_single = QPushButton("⚡ Translate Block")
        self.btn_trans_single.setStyleSheet(
            "padding: 2px 8px; font-size: 11px; background: #0284c7; color: white; border-radius: 4px;"
        )
        self.btn_trans_single.clicked.connect(lambda: self.translate_requested.emit(self.block_idx))
        header_layout.addWidget(self.btn_trans_single)

        layout.addLayout(header_layout)

        # Side-by-side Editors Layout
        editors_layout = QHBoxLayout()
        editors_layout.setSpacing(10)

        # Original Text Column
        orig_col = QVBoxLayout()
        orig_col.setSpacing(2)
        lbl_orig = QLabel("Original Text")
        lbl_orig.setStyleSheet("color: #a1a1aa; font-size: 11px; font-weight: bold;")
        orig_col.addWidget(lbl_orig)

        self.txt_original = QPlainTextEdit()
        self.txt_original.setPlaceholderText("Original text...")
        self.txt_original.setMaximumHeight(85)
        self.txt_original.setStyleSheet(
            "background-color: #18181b; color: #f4f4f5; border: 1px solid #3f3f46; border-radius: 4px; padding: 4px;"
        )
        orig_col.addWidget(self.txt_original)
        editors_layout.addLayout(orig_col, stretch=1)

        # Translated Text Column
        trans_col = QVBoxLayout()
        trans_col.setSpacing(2)
        lbl_trans = QLabel("Translated Text")
        lbl_trans.setStyleSheet("color: #a1a1aa; font-size: 11px; font-weight: bold;")
        trans_col.addWidget(lbl_trans)

        self.txt_translated = QPlainTextEdit()
        self.txt_translated.setPlaceholderText("Translated text...")
        self.txt_translated.setMaximumHeight(85)
        self.txt_translated.setStyleSheet(
            "background-color: #18181b; color: #38bdf8; border: 1px solid #0284c7; border-radius: 4px; padding: 4px;"
        )
        trans_col.addWidget(self.txt_translated)
        editors_layout.addLayout(trans_col, stretch=1)

        layout.addLayout(editors_layout)

        # Connect text changes
        self.txt_original.textChanged.connect(self._on_original_changed)
        self.txt_translated.textChanged.connect(self._on_translated_changed)

        # Populate content
        self.update_content()
        self._apply_style()

    def update_content(self) -> None:
        """Update editor boxes from block object without triggering recursive signals."""
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
        finally:
            self._updating_ui = False

    def _on_original_changed(self) -> None:
        if self._updating_ui:
            return
        text_val = self.txt_original.toPlainText()
        lines = text_val.split('\n')
        if hasattr(self.block, 'text'):
            self.block.text = lines
        elif isinstance(self.block, dict):
            self.block['text'] = lines
        self.text_modified.emit(self.block_idx)

    def _on_translated_changed(self) -> None:
        if self._updating_ui:
            return
        trans_val = self.txt_translated.toPlainText()
        if hasattr(self.block, 'translation'):
            self.block.translation = trans_val
            # Clear rich_text so edited plain text takes precedence
            if hasattr(self.block, 'rich_text'):
                self.block.rich_text = ""
        elif isinstance(self.block, dict):
            self.block['translation'] = trans_val
            self.block['rich_text'] = ""
        self.text_modified.emit(self.block_idx)

    def set_selected(self, val: bool) -> None:
        if self._is_selected != val:
            self._is_selected = val
            self._apply_style()

    def _apply_style(self) -> None:
        if self._is_selected:
            self.setStyleSheet(
                "QFrame#BlockRowCard { background-color: #1e293b; border: 2px solid #0284c7; border-radius: 6px; }"
            )
        else:
            self.setStyleSheet(
                "QFrame#BlockRowCard { background-color: #0f172a; border: 1px solid #334155; border-radius: 6px; }"
            )

    def mousePressEvent(self, event) -> None:
        self.selected.emit(self.block_idx)
        super().mousePressEvent(event)


class SideTextPanel(QWidget):
    """Side panel displaying side-by-side text list and translation controls."""

    block_selected = Signal(int)
    text_modified = Signal(int)
    translate_page_requested = Signal(str, str, str)  # (translator_key, src_lang, tgt_lang)
    translate_block_requested = Signal(int, str, str, str)  # (block_idx, translator_key, src_lang, tgt_lang)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_page: Optional[MangaPage] = None
        self.cards: List[BlockRowCard] = []
        self.selected_block_idx: int = -1

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        # Header Title
        lbl_header = QLabel("📋 Dialogue Text Blocks")
        lbl_header.setStyleSheet("font-size: 14px; font-weight: bold; color: #f8fafc;")
        layout.addWidget(lbl_header)

        # Control Panel Box (Translator Engine & Language Selectors)
        ctrl_box = QFrame()
        ctrl_box.setStyleSheet("background-color: #1e293b; border-radius: 6px; border: 1px solid #334155;")
        ctrl_layout = QVBoxLayout(ctrl_box)
        ctrl_layout.setContentsMargins(8, 8, 8, 8)
        ctrl_layout.setSpacing(6)

        # Translator Selection Row
        t_row = QHBoxLayout()
        lbl_trans = QLabel("Engine:")
        lbl_trans.setStyleSheet("color: #94a3b8; font-size: 12px;")
        self.combo_engine = QComboBox()
        for engine in TRANSLATOR_LIST:
            self.combo_engine.addItem(engine)
        t_row.addWidget(lbl_trans)
        t_row.addWidget(self.combo_engine, stretch=1)
        ctrl_layout.addLayout(t_row)

        # Language Selectors Row
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

        # Page-Level Action Buttons Row
        btn_row = QHBoxLayout()
        self.btn_trans_sel = QPushButton("⚡ Translate Selected")
        self.btn_trans_sel.setStyleSheet(
            "background-color: #0284c7; color: white; font-weight: bold; border-radius: 4px; padding: 4px 8px;"
        )
        self.btn_trans_sel.clicked.connect(self._on_translate_selected)
        btn_row.addWidget(self.btn_trans_sel)

        self.btn_trans_page = QPushButton("⚡ Translate Page")
        self.btn_trans_page.setStyleSheet(
            "background-color: #2563eb; color: white; font-weight: bold; border-radius: 4px; padding: 4px 8px;"
        )
        self.btn_trans_page.clicked.connect(self._on_translate_page)
        btn_row.addWidget(self.btn_trans_page)

        ctrl_layout.addLayout(btn_row)
        layout.addWidget(ctrl_box)

        # Scroll Area for Block Cards
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

    def load_page_blocks(self, page: MangaPage) -> None:
        """Populate the side panel with cards for all textblocks on page."""
        self.setUpdatesEnabled(False)
        try:
            self.current_page = page
            self.selected_block_idx = -1

            # Clear existing card widgets
            for card in self.cards:
                if isinstance(card, QWidget):
                    self.container_layout.removeWidget(card)
                    card.deleteLater()
            self.cards.clear()

            if not page or not page.blocks:
                lbl_empty = QLabel("No dialogue text blocks on this page.")
                lbl_empty.setObjectName("EmptyLabel")
                lbl_empty.setStyleSheet("color: #64748b; font-style: italic; padding: 16px;")
                lbl_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.cards.append(lbl_empty)
                self.container_layout.insertWidget(0, lbl_empty)
                return

            for idx, block in enumerate(page.blocks):
                card = BlockRowCard(block_idx=idx, block=block)
                card.selected.connect(self._on_card_selected)
                card.text_modified.connect(self.text_modified.emit)
                card.translate_requested.connect(self._on_single_block_translate)
                self.cards.append(card)
                self.container_layout.insertWidget(idx, card)
        finally:
            self.setUpdatesEnabled(True)

    def select_block(self, idx: int) -> None:
        """Highlight specified block index and scroll into view."""
        self.selected_block_idx = idx
        selected_card = None
        for card in self.cards:
            if isinstance(card, BlockRowCard):
                is_sel = (card.block_idx == idx)
                card.set_selected(is_sel)
                if is_sel:
                    selected_card = card

        if selected_card:
            self.scroll_area.ensureWidgetVisible(selected_card)

    def _on_card_selected(self, idx: int) -> None:
        self.select_block(idx)
        self.block_selected.emit(idx)

    def _on_translate_page(self) -> None:
        engine = self.combo_engine.currentText()
        src = self.combo_src.currentText()
        tgt = self.combo_tgt.currentText()
        self.translate_page_requested.emit(engine, src, tgt)

    def _on_translate_selected(self) -> None:
        if self.selected_block_idx >= 0:
            self._on_single_block_translate(self.selected_block_idx)

    def _on_single_block_translate(self, idx: int) -> None:
        engine = self.combo_engine.currentText()
        src = self.combo_src.currentText()
        tgt = self.combo_tgt.currentText()
        self.translate_block_requested.emit(idx, engine, src, tgt)
