import os
import os.path as osp
import subprocess
import sys
from typing import List, Optional, Set

from qtpy.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QScrollArea,
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QComboBox,
    QMenu,
    QAction,
    QApplication,
)
from qtpy.QtCore import Qt, Signal, QSize
from qtpy.QtGui import QPixmap, QImage, QCursor, QFont

from READER.core.scanner import MangaItem, scan_translated_directory
from READER.core.favorites import FAVORITES
from READER.ui.loading_overlay import LoadingOverlay


class MangaCardWidget(QFrame):
    """Grid card widget representing a single manga volume/chapter."""

    card_clicked = Signal(MangaItem)
    open_translator_requested = Signal(MangaItem)
    favorite_toggled = Signal()

    def __init__(self, item: MangaItem, parent=None):
        super().__init__(parent)
        self.item = item
        self.setObjectName("MangaCard")
        self.setFixedSize(184, 285)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # Top Bar inside Card (Favorite Star & Thumbnail)
        thumb_container = QFrame()
        thumb_container.setFixedSize(168, 175)
        thumb_layout = QVBoxLayout(thumb_container)
        thumb_layout.setContentsMargins(0, 0, 0, 0)

        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(168, 175)
        self.thumb_label.setStyleSheet("border-radius: 6px; background-color: #12141c;")
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Star Button overlay
        self.btn_star = QPushButton(self.thumb_label)
        self.btn_star.setFixedSize(28, 28)
        self.btn_star.move(134, 6)
        self.btn_star.setStyleSheet(
            "background-color: rgba(30, 34, 48, 0.85); border: none; border-radius: 14px; font-size: 14px;"
        )
        self._update_star_icon()
        self.btn_star.clicked.connect(self._on_toggle_favorite)

        layout.addWidget(self.thumb_label)

        # Title Label
        self.title_label = QLabel(item.title)
        self.title_label.setObjectName("CardTitle")
        self.title_label.setWordWrap(True)
        self.title_label.setMaximumHeight(32)
        self.title_label.setToolTip(item.title)
        layout.addWidget(self.title_label)

        # Author Label
        self.author_label = QLabel(f"👤 {item.author}")
        self.author_label.setObjectName("CardMeta")
        self.author_label.setMaximumHeight(16)
        layout.addWidget(self.author_label)

        # Meta & Badges Layout
        meta_layout = QHBoxLayout()
        meta_layout.setContentsMargins(0, 2, 0, 0)
        meta_layout.setSpacing(4)

        pages_badge = QLabel(f"{item.page_count}p")
        pages_badge.setObjectName("Badge")
        meta_layout.addWidget(pages_badge)

        # Verification Status Badge
        status_badge = QLabel()
        status_badge.setObjectName("Badge")
        if item.verification_status == "verified":
            status_badge.setText("✓ Verified")
            status_badge.setStyleSheet("background-color: #065f46; color: #6ee7b7;")
        elif item.verification_status == "needs_fix":
            status_badge.setText("⚠ Needs Fix")
            status_badge.setStyleSheet("background-color: #991b1b; color: #fca5a5;")
        else:
            status_badge.setText("Unverified")
            status_badge.setStyleSheet("background-color: #374151; color: #d1d5db;")
        meta_layout.addWidget(status_badge)

        meta_layout.addStretch()
        layout.addLayout(meta_layout)

        self._load_thumbnail()

    def _update_star_icon(self) -> None:
        is_fav = FAVORITES.is_favorite(self.item.relative_path)
        self.btn_star.setText("⭐" if is_fav else "☆")

    def _on_toggle_favorite(self) -> None:
        FAVORITES.toggle_favorite(self.item.relative_path)
        self._update_star_icon()
        self.favorite_toggled.emit()

    def _load_thumbnail(self) -> None:
        if self.item.cover_image_path and osp.exists(self.item.cover_image_path):
            pixmap = QPixmap(self.item.cover_image_path)
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    168,
                    175,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
                cropped = scaled.copy(
                    (scaled.width() - 168) // 2,
                    (scaled.height() - 175) // 2,
                    168,
                    175,
                )
                self.thumb_label.setPixmap(cropped)
                return

        self.thumb_label.setText(self.item.title[:12])

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.card_clicked.emit(self.item)
        elif event.button() == Qt.MouseButton.RightButton:
            self._show_context_menu(event.globalPos() if hasattr(event, 'globalPos') else QCursor.pos())
        super().mousePressEvent(event)

    def _show_context_menu(self, pos) -> None:
        menu = QMenu(self)
        action_read = menu.addAction("Read Manga")
        action_fav = menu.addAction("Unfavorite" if FAVORITES.is_favorite(self.item.relative_path) else "Favorite ⭐")
        action_folder = menu.addAction("Open Folder")
        action_trans = menu.addAction("Open in BalloonsTranslator")

        selected = menu.exec_(pos)
        if selected == action_read:
            self.card_clicked.emit(self.item)
        elif selected == action_fav:
            self._on_toggle_favorite()
        elif selected == action_folder:
            if sys.platform == 'win32':
                os.startfile(self.item.path)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', self.item.path])
            else:
                subprocess.Popen(['xdg-open', self.item.path])
        elif selected == action_trans:
            self.open_translator_requested.emit(self.item)


class LibraryView(QWidget):
    """Main Manga Library browsing panel."""

    manga_selected = Signal(MangaItem)
    open_translator = Signal(str)

    def __init__(self, root_dir: str, parent=None):
        super().__init__(parent)
        self.root_dir = osp.abspath(root_dir)
        self.items: List[MangaItem] = []
        self.cards: List[MangaCardWidget] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Toolbar & Filter Row 1 (Search & Actions)
        toolbar1 = QHBoxLayout()
        toolbar1.setSpacing(10)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍 Search manga title, author, or tags...")
        self.search_edit.textChanged.connect(self._filter_cards)
        toolbar1.addWidget(self.search_edit, stretch=2)

        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["Recently Added", "Title A-Z", "Page Count"])
        self.sort_combo.currentIndexChanged.connect(self._sort_and_refresh)
        toolbar1.addWidget(self.sort_combo, stretch=1)

        self.refresh_btn = QPushButton("🔄 Refresh")
        self.refresh_btn.clicked.connect(self.scan_library)
        toolbar1.addWidget(self.refresh_btn)

        layout.addLayout(toolbar1)

        # Toolbar Row 2 (Author Filter & Category Filter)
        toolbar2 = QHBoxLayout()
        toolbar2.setSpacing(10)

        self.author_combo = QComboBox()
        self.author_combo.addItem("All Authors")
        self.author_combo.currentIndexChanged.connect(self._filter_cards)
        toolbar2.addWidget(self.author_combo, stretch=1)

        self.category_combo = QComboBox()
        self.category_combo.addItems([
            "All Manga",
            "⭐ Favorites Only",
            "✓ Verified Only",
            "⚠ Needs Fix / Retranslate",
            "Unverified Only",
        ])
        self.category_combo.currentIndexChanged.connect(self._filter_cards)
        toolbar2.addWidget(self.category_combo, stretch=1)

        layout.addLayout(toolbar2)

        # Status & Location Bar
        self.status_label = QLabel(f"Library Location: {self.root_dir}")
        self.status_label.setObjectName("HeaderSubtitle")
        layout.addWidget(self.status_label)

        # Scrollable Grid Area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        
        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setContentsMargins(8, 8, 8, 8)
        self.grid_layout.setSpacing(16)
        self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        self.scroll_area.setWidget(self.grid_container)
        layout.addWidget(self.scroll_area)

        # Loading Overlay
        self.loading_overlay = LoadingOverlay(self)

        # Initial scan
        self.scan_library()

    def scan_library(self) -> None:
        """Scan TRANSLATED directory and populate cards."""
        self.loading_overlay.start_loading("Scanning Manga Library", "Discovering translated manga volumes...")
        QApplication.processEvents()

        try:
            self.items = scan_translated_directory(self.root_dir)
            
            # Populate Author dropdown dynamically
            authors = sorted(list({item.author for item in self.items if item.author and item.author != "Unknown"}))
            self.author_combo.blockSignals(True)
            self.author_combo.clear()
            self.author_combo.addItem("All Authors")
            for auth in authors:
                self.author_combo.addItem(f"👤 {auth}")
            self.author_combo.blockSignals(False)

            self._sort_and_refresh()
        finally:
            self.loading_overlay.stop_loading()

    def set_root_dir(self, root_dir: str) -> None:
        self.root_dir = osp.abspath(root_dir)
        self.status_label.setText(f"Library Location: {self.root_dir}")
        self.scan_library()

    def _sort_and_refresh(self) -> None:
        sort_mode = self.sort_combo.currentText()
        if sort_mode == "Title A-Z":
            self.items.sort(key=lambda x: x.title.lower())
        elif sort_mode == "Page Count":
            self.items.sort(key=lambda x: x.page_count, reverse=True)
        else: # Recently Added
            self.items.sort(key=lambda x: x.mtime, reverse=True)

        self._rebuild_grid()

    def _rebuild_grid(self) -> None:
        # Clear existing widgets
        for card in self.cards:
            card.deleteLater()
        self.cards.clear()

        filter_text = self.search_edit.text().strip().lower()
        selected_author = self.author_combo.currentText().replace("👤 ", "")
        selected_category = self.category_combo.currentText()

        visible_count = 0
        cols = max(1, (self.width() - 40) // 200)

        for item in self.items:
            # 1. Author Filter
            if selected_author != "All Authors" and item.author != selected_author:
                continue

            # 2. Category / Verification Filter
            if selected_category == "⭐ Favorites Only":
                if not FAVORITES.is_favorite(item.relative_path):
                    continue
            elif selected_category == "✓ Verified Only":
                if item.verification_status != "verified":
                    continue
            elif selected_category == "⚠ Needs Fix / Retranslate":
                if item.verification_status != "needs_fix":
                    continue
            elif selected_category == "Unverified Only":
                if item.verification_status != "unverified":
                    continue

            # 3. Search Text Filter
            if filter_text:
                match_title = filter_text in item.title.lower()
                match_author = filter_text in item.author.lower()
                match_rel = filter_text in item.relative_path.lower()
                match_tag = any(filter_text in t.lower() for t in item.tags)
                match_art = any(filter_text in a.lower() for a in item.artists)
                if not (match_title or match_author or match_rel or match_tag or match_art):
                    continue

            card = MangaCardWidget(item)
            card.card_clicked.connect(self.manga_selected.emit)
            card.open_translator_requested.connect(lambda item: self.open_translator.emit(item.path))
            card.favorite_toggled.connect(self._rebuild_grid)

            row = visible_count // cols
            col = visible_count % cols
            self.grid_layout.addWidget(card, row, col)
            self.cards.append(card)
            visible_count += 1

        self.status_label.setText(f"Displaying {visible_count} of {len(self.items)} manga volume(s)")

    def _filter_cards(self) -> None:
        self._rebuild_grid()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._rebuild_grid()
