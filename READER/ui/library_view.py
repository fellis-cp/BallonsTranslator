import os
import os.path as osp
import re
import subprocess
import sys
from typing import List, Optional, Dict, Tuple

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
    QApplication,
    QSizePolicy,
)
from qtpy.QtCore import Qt, Signal, QThread, QTimer, QObject
from qtpy.QtGui import QPixmap, QCursor

from READER.core.scanner import MangaItem, scan_translated_directory
from READER.core.favorites import FAVORITES
from READER.ui.loading_overlay import LoadingOverlay


def _natural_sort_key(text: str) -> list:
    """Sort strings containing numbers in human/natural order (e.g. 1, 2, ... 9, 10).

    >>> _natural_sort_key("Chapter 2") < _natural_sort_key("Chapter 10")
    True
    """
    return [int(token) if token.isdigit() else token.lower() for token in re.split(r"(\d+)", text)]


# ── Background thumbnail loader ───────────────────────────────────────────────

class _ThumbnailSignals(QObject):
    ready = Signal(str, QPixmap)   # (cover_image_path, scaled_pixmap)
    finished = Signal()


class ThumbnailLoaderThread(QThread):
    """Decode and scale cover images off the main thread.

    >>> t = ThumbnailLoaderThread([])
    >>> t.isRunning()
    False
    """

    def __init__(self, jobs: List[tuple], parent=None):
        super().__init__(parent)
        self._jobs = jobs          # [(path, w, h), ...]
        self.signals = _ThumbnailSignals()
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        for path, w, h in self._jobs:
            if self._cancelled:
                break
            if not path or not osp.exists(path):
                continue
            try:
                pixmap = QPixmap(path)
                if pixmap.isNull():
                    continue
                scaled = pixmap.scaled(
                    w, h,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                )
                cropped = scaled.copy(
                    (scaled.width() - w) // 2,
                    (scaled.height() - h) // 2,
                    w, h,
                )
                self.signals.ready.emit(path, cropped)
            except Exception:
                pass
        self.signals.finished.emit()


# ── Author card ───────────────────────────────────────────────────────────────

class AuthorCardWidget(QFrame):
    """Card representing one author in the author-browse level."""

    author_clicked = Signal(str)   # emits author name

    _THUMB_W = 168
    _THUMB_H = 175

    def __init__(self, author: str, manga_items: List[MangaItem], parent=None):
        super().__init__(parent)
        self.author = author
        self.cover_path: Optional[str] = None

        # Use cover image from the author's first manga that has one
        for item in manga_items:
            if item.cover_image_path and osp.exists(item.cover_image_path):
                self.cover_path = item.cover_image_path
                break

        self.setObjectName("MangaCard")
        self.setFixedSize(184, 295)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(3)

        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(self._THUMB_W, self._THUMB_H)
        self.thumb_label.setStyleSheet(
            "border-radius: 6px; background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            "stop:0 #1e293b, stop:1 #0f172a);"
        )
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setText("👤")
        self.thumb_label.setStyleSheet(
            self.thumb_label.styleSheet() + " font-size: 40px;"
        )
        layout.addWidget(self.thumb_label)

        # Author name
        self.name_label = QLabel(author)
        self.name_label.setObjectName("CardTitle")
        self.name_label.setWordWrap(True)
        self.name_label.setMaximumHeight(38)
        self.name_label.setToolTip(author)
        layout.addWidget(self.name_label)

        # Manga count badge
        n = len(manga_items)
        badge = QLabel(f"📚 {n} manga" if n != 1 else "📚 1 manga")
        badge.setObjectName("Badge")
        badge.setStyleSheet("background-color: #1e3a5f; color: #7dd3fc; padding: 2px 6px; border-radius: 8px;")
        layout.addWidget(badge)

        layout.addStretch()

    def set_thumbnail(self, pixmap: QPixmap) -> None:
        self.thumb_label.setPixmap(pixmap)
        self.thumb_label.setText("")

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.author_clicked.emit(self.author)
        super().mousePressEvent(event)


# ── Series / Folder card ──────────────────────────────────────────────────────

class FolderCardWidget(QFrame):
    """Card representing a series / subfolder within an author directory."""

    folder_clicked = Signal(list)   # emits target folder path list

    _THUMB_W = 168
    _THUMB_H = 175

    def __init__(self, folder_name: str, folder_path: List[str], manga_items: List[MangaItem], parent=None):
        super().__init__(parent)
        self.folder_name = folder_name
        self.folder_path = list(folder_path)
        self.manga_items = list(manga_items)
        self.cover_path: Optional[str] = None

        for item in manga_items:
            if item.cover_image_path and osp.exists(item.cover_image_path):
                self.cover_path = item.cover_image_path
                break

        self.setObjectName("MangaCard")
        self.setFixedSize(184, 295)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(3)

        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(self._THUMB_W, self._THUMB_H)
        self.thumb_label.setStyleSheet(
            "border-radius: 6px; background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            "stop:0 #1e3a5f, stop:1 #0c1e36);"
        )
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setText("📁")
        self.thumb_label.setStyleSheet(
            self.thumb_label.styleSheet() + " font-size: 44px;"
        )
        layout.addWidget(self.thumb_label)

        self.name_label = QLabel(f"📁 {folder_name}")
        self.name_label.setObjectName("CardTitle")
        self.name_label.setWordWrap(True)
        self.name_label.setMaximumHeight(38)
        self.name_label.setToolTip(folder_name)
        layout.addWidget(self.name_label)

        n = len(manga_items)
        badge = QLabel(f"📖 {n} chapter{'s' if n != 1 else ''}")
        badge.setObjectName("Badge")
        badge.setStyleSheet("background-color: #1e3a5f; color: #7dd3fc; padding: 2px 6px; border-radius: 8px;")
        layout.addWidget(badge)

        layout.addStretch()

    def set_thumbnail(self, pixmap: QPixmap) -> None:
        self.thumb_label.setPixmap(pixmap)
        self.thumb_label.setText("")

    def matches(self, filter_text: str, category: str) -> bool:
        name_match = (not filter_text) or (filter_text.lower() in self.folder_name.lower())
        if category == "⭐ Favorites Only":
            has_item = any(FAVORITES.is_favorite(it.relative_path) for it in self.manga_items)
        elif category == "✓ Verified Only":
            has_item = any(it.verification_status == "verified" for it in self.manga_items)
        elif category == "⚠ Needs Fix / Retranslate":
            has_item = any(it.verification_status == "needs_fix" for it in self.manga_items)
        elif category == "Unverified Only":
            has_item = any(it.verification_status == "unverified" for it in self.manga_items)
        else:
            has_item = True

        if filter_text and not name_match:
            q = filter_text.lower()
            has_item = has_item and any(
                q in it.title.lower() or q in it.relative_path.lower() or any(q in t.lower() for t in it.tags)
                for it in self.manga_items
            )

        return name_match and has_item

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.folder_clicked.emit(self.folder_path)
        super().mousePressEvent(event)


# ── Manga card ────────────────────────────────────────────────────────────────

class MangaCardWidget(QFrame):
    """Grid card for a single manga volume."""

    card_clicked = Signal(MangaItem)
    open_translator_requested = Signal(MangaItem)
    favorite_toggled = Signal()

    _THUMB_W = 168
    _THUMB_H = 175

    def __init__(self, item: MangaItem, parent=None):
        super().__init__(parent)
        self.item = item
        self.setObjectName("MangaCard")
        self.setFixedSize(184, 295)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(3)

        self.thumb_label = QLabel()
        self.thumb_label.setFixedSize(self._THUMB_W, self._THUMB_H)
        self.thumb_label.setStyleSheet("border-radius: 6px; background-color: #12141c;")
        self.thumb_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb_label.setText(item.title[:12])

        self.btn_star = QPushButton(self.thumb_label)
        self.btn_star.setFixedSize(28, 28)
        self.btn_star.move(134, 6)
        self.btn_star.setStyleSheet(
            "background-color: rgba(30,34,48,0.85); border:none; border-radius:14px; font-size:14px;"
        )
        self._update_star_icon()
        self.btn_star.clicked.connect(self._on_toggle_favorite)

        layout.addWidget(self.thumb_label)

        self.title_label = QLabel(item.title)
        self.title_label.setObjectName("CardTitle")
        self.title_label.setWordWrap(True)
        self.title_label.setMaximumHeight(38)
        self.title_label.setToolTip(item.title)
        layout.addWidget(self.title_label)

        self.author_label = QLabel(f"👤 {item.author}")
        self.author_label.setObjectName("CardMeta")
        self.author_label.setMaximumHeight(16)
        self.author_label.setToolTip(item.author)
        layout.addWidget(self.author_label)

        meta_layout = QHBoxLayout()
        meta_layout.setContentsMargins(0, 2, 0, 0)
        meta_layout.setSpacing(4)

        pages_badge = QLabel(f"{item.page_count}p")
        pages_badge.setObjectName("Badge")
        meta_layout.addWidget(pages_badge)

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

    def set_thumbnail(self, pixmap: QPixmap) -> None:
        self.thumb_label.setPixmap(pixmap)
        self.thumb_label.setText("")

    def _update_star_icon(self) -> None:
        self.btn_star.setText("⭐" if FAVORITES.is_favorite(self.item.relative_path) else "☆")

    def _on_toggle_favorite(self) -> None:
        FAVORITES.toggle_favorite(self.item.relative_path)
        self._update_star_icon()
        self.favorite_toggled.emit()

    def matches(self, filter_text: str, category: str) -> bool:
        if category == "⭐ Favorites Only" and not FAVORITES.is_favorite(self.item.relative_path):
            return False
        if category == "✓ Verified Only" and self.item.verification_status != "verified":
            return False
        if category == "⚠ Needs Fix / Retranslate" and self.item.verification_status != "needs_fix":
            return False
        if category == "Unverified Only" and self.item.verification_status != "unverified":
            return False
        if filter_text:
            q = filter_text.lower()
            if not (
                q in self.item.title.lower()
                or q in self.item.author.lower()
                or q in self.item.relative_path.lower()
                or any(q in t.lower() for t in self.item.tags)
                or any(q in a.lower() for a in self.item.artists)
            ):
                return False
        return True

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.card_clicked.emit(self.item)
        elif event.button() == Qt.MouseButton.RightButton:
            pos = event.globalPos() if hasattr(event, 'globalPos') else QCursor.pos()
            self._show_context_menu(pos)
        super().mousePressEvent(event)

    def _show_context_menu(self, pos) -> None:
        menu = QMenu(self)
        action_read = menu.addAction("Read Manga")
        action_fav = menu.addAction(
            "Unfavorite" if FAVORITES.is_favorite(self.item.relative_path) else "Favorite ⭐"
        )
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


# ── Library view ──────────────────────────────────────────────────────────────

class LibraryView(QWidget):
    """Hierarchical Manga Library View:
    Authors Grid → Series / Folder Grid → Manga Chapters Grid.

    Navigation
    ----------
    * Root shows author cards aggregated case-insensitively.
    * Clicking an author opens their series / subfolders and direct works.
    * Clicking a series folder drills down into chapters.
    * Interactive clickable breadcrumb bar allows 1-click jumps back to any parent level.
    * Scroll position is preserved at each folder level.
    """

    manga_selected = Signal(MangaItem)
    open_translator = Signal(str)

    def __init__(self, root_dir: str, parent=None):
        super().__init__(parent)
        self.root_dir = osp.abspath(root_dir)
        self.items: List[MangaItem] = []

        self._all_manga_cards: List[MangaCardWidget] = []
        self._author_cards: List[AuthorCardWidget] = []
        # Key: tuple of path segments -> FolderCardWidget
        self._folder_cards: Dict[Tuple[str, ...], FolderCardWidget] = {}
        # cover_path -> list of cards waiting for thumbnail
        self._cover_to_cards: Dict[str, list] = {}

        # Hierarchical navigation path: [] = Root (Authors)
        # ["Shigeatsu"] = Author Shigeatsu
        # ["Shigeatsu", "Life Support 2"] = Series folder
        self._nav_path: List[str] = []
        self._active_author: str = ""
        self._active_author_display: str = ""
        self._flat_filter_active: bool = False

        # Scroll position history keyed by path string
        self._scroll_pos_map: Dict[str, int] = {}

        self._thumb_loader: Optional[ThumbnailLoaderThread] = None

        # Debounce timers
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(150)
        self._resize_timer.timeout.connect(self._relayout)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(200)
        self._search_timer.timeout.connect(self._relayout)

        # ── UI ───────────────────────────────────────────────────────────────
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # Breadcrumb bar
        self.breadcrumb_bar = QFrame()
        self.breadcrumb_bar.setObjectName("ReaderControlBar")
        bc_main_layout = QHBoxLayout(self.breadcrumb_bar)
        bc_main_layout.setContentsMargins(8, 6, 8, 6)
        bc_main_layout.setSpacing(10)

        self.btn_back = QPushButton("← Back")
        self.btn_back.setStyleSheet(
            "QPushButton {"
            "  background-color: #1e3a5f;"
            "  color: #7dd3fc;"
            "  border: 1px solid #38bdf8;"
            "  border-radius: 6px;"
            "  padding: 4px 14px;"
            "  font-size: 13px;"
            "  font-weight: bold;"
            "}"
            "QPushButton:hover { background-color: #164e83; }"
        )
        self.btn_back.clicked.connect(self._navigate_back)
        bc_main_layout.addWidget(self.btn_back)

        self.crumbs_container = QWidget()
        self.crumbs_layout = QHBoxLayout(self.crumbs_container)
        self.crumbs_layout.setContentsMargins(0, 0, 0, 0)
        self.crumbs_layout.setSpacing(6)
        bc_main_layout.addWidget(self.crumbs_container, stretch=1)

        self.breadcrumb_bar.hide()
        layout.addWidget(self.breadcrumb_bar)

        # Toolbar row 1
        toolbar1 = QHBoxLayout()
        toolbar1.setSpacing(10)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍 Search title, author, or tags...")
        self.search_edit.textChanged.connect(lambda: self._search_timer.start())
        toolbar1.addWidget(self.search_edit, stretch=2)

        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["Recently Added", "Title (1-9, A-Z)", "Page Count"])
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        toolbar1.addWidget(self.sort_combo, stretch=1)

        self.refresh_btn = QPushButton("🔄 Refresh")
        self.refresh_btn.clicked.connect(self.scan_library)
        toolbar1.addWidget(self.refresh_btn)

        layout.addLayout(toolbar1)

        # Toolbar row 2 (only meaningful when drilled into author or series)
        self.toolbar2 = QFrame()
        t2_layout = QHBoxLayout(self.toolbar2)
        t2_layout.setContentsMargins(0, 0, 0, 0)
        t2_layout.setSpacing(10)

        self.category_combo = QComboBox()
        self.category_combo.addItems([
            "All Manga",
            "⭐ Favorites Only",
            "✓ Verified Only",
            "⚠ Needs Fix / Retranslate",
            "Unverified Only",
        ])
        self.category_combo.currentIndexChanged.connect(self._relayout)
        t2_layout.addWidget(self.category_combo, stretch=1)

        layout.addWidget(self.toolbar2)
        self.toolbar2.hide()

        self.status_label = QLabel(f"Library: {self.root_dir}")
        self.status_label.setObjectName("HeaderSubtitle")
        layout.addWidget(self.status_label)

        # ── Status summary bar ───────────────────────────────────────────────
        self.status_bar = QFrame()
        sb_layout = QHBoxLayout(self.status_bar)
        sb_layout.setContentsMargins(0, 2, 0, 2)
        sb_layout.setSpacing(8)

        _pill_base = (
            "QPushButton {"
            "  border-radius: 10px;"
            "  padding: 3px 12px;"
            "  font-size: 12px;"
            "  font-weight: bold;"
            "  border: none;"
            "}"
        )
        self.pill_verified = QPushButton("✓ Verified  0")
        self.pill_verified.setStyleSheet(
            _pill_base
            + "QPushButton { background: #065f46; color: #6ee7b7; }"
            + "QPushButton:hover { background: #047857; }"
            + "QPushButton:checked { border: 2px solid #34d399; }"
        )
        self.pill_verified.setCheckable(True)
        self.pill_verified.clicked.connect(lambda: self._on_pill_clicked("verified"))
        sb_layout.addWidget(self.pill_verified)

        self.pill_needs_fix = QPushButton("\u26a0 Needs Fix  0")
        self.pill_needs_fix.setStyleSheet(
            _pill_base
            + "QPushButton { background: #7f1d1d; color: #fca5a5; }"
            + "QPushButton:hover { background: #991b1b; }"
            + "QPushButton:checked { border: 2px solid #f87171; }"
        )
        self.pill_needs_fix.setCheckable(True)
        self.pill_needs_fix.clicked.connect(lambda: self._on_pill_clicked("needs_fix"))
        sb_layout.addWidget(self.pill_needs_fix)

        self.pill_unverified = QPushButton("\u25cb Unverified  0")
        self.pill_unverified.setStyleSheet(
            _pill_base
            + "QPushButton { background: #374151; color: #d1d5db; }"
            + "QPushButton:hover { background: #4b5563; }"
            + "QPushButton:checked { border: 2px solid #9ca3af; }"
        )
        self.pill_unverified.setCheckable(True)
        self.pill_unverified.clicked.connect(lambda: self._on_pill_clicked("unverified"))
        sb_layout.addWidget(self.pill_unverified)

        sb_layout.addStretch()
        layout.addWidget(self.status_bar)

        # Grid scroll area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)

        self.grid_container = QWidget()
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setContentsMargins(8, 8, 8, 8)
        self.grid_layout.setSpacing(16)
        self.grid_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        self.scroll_area.setWidget(self.grid_container)
        layout.addWidget(self.scroll_area)

        self.loading_overlay = LoadingOverlay(self)

        self.scan_library()

    # ── Scan (creates cards once) ─────────────────────────────────────────────

    def scan_library(self) -> None:
        self._cancel_thumb_loader()
        self.loading_overlay.start_loading("Scanning Library", "Discovering manga volumes...")
        QApplication.processEvents()

        try:
            self.items = scan_translated_directory(self.root_dir)
            self._destroy_all_cards()
            self._cover_to_cards.clear()
            self._scroll_pos_map.clear()

            # 1. Build manga cards
            for item in self.items:
                card = MangaCardWidget(item)
                card.card_clicked.connect(self.manga_selected.emit)
                card.open_translator_requested.connect(
                    lambda it: self.open_translator.emit(it.path)
                )
                card.favorite_toggled.connect(self._relayout)
                self._all_manga_cards.append(card)
                if item.cover_image_path:
                    self._cover_to_cards.setdefault(item.cover_image_path, []).append(card)

            # 2. Build Author cards
            author_groups_ci: Dict[str, List[MangaItem]] = {}   # lowercase key -> items
            author_variants: Dict[str, Dict[str, int]] = {}      # lowercase key -> {display_variant: count}
            for item in self.items:
                key = item.author.lower()
                author_groups_ci.setdefault(key, []).append(item)
                author_variants.setdefault(key, {})
                author_variants[key][item.author] = author_variants[key].get(item.author, 0) + 1

            for key, manga_list in sorted(
                author_groups_ci.items(),
                key=lambda kv: _natural_sort_key(kv[0]),
            ):
                display_name = max(
                    author_variants[key],
                    key=lambda v: (author_variants[key][v], v),
                )
                ac = AuthorCardWidget(display_name, manga_list)
                ac.author_clicked.connect(self._show_author_view_by_name)
                self._author_cards.append(ac)
                if ac.cover_path:
                    self._cover_to_cards.setdefault(ac.cover_path, []).append(ac)

            # 3. Build Folder cards for all subdirectories under each author
            folder_groups: Dict[Tuple[str, ...], List[MangaItem]] = {}
            for item in self.items:
                norm_rel = osp.normpath(item.relative_path)
                parts = norm_rel.split(os.sep)
                # If there are subfolders between author and the leaf item (e.g. [Author, Series, Ch1])
                if len(parts) > 2:
                    for depth in range(1, len(parts) - 1):
                        folder_path_tuple = tuple(parts[:depth + 1])
                        folder_groups.setdefault(folder_path_tuple, []).append(item)

            for folder_path_tuple, manga_list in folder_groups.items():
                folder_name = folder_path_tuple[-1]
                fc = FolderCardWidget(folder_name, list(folder_path_tuple), manga_list)
                fc.folder_clicked.connect(self._navigate_to)
                self._folder_cards[folder_path_tuple] = fc
                if fc.cover_path:
                    self._cover_to_cards.setdefault(fc.cover_path, []).append(fc)

            # Reset to root
            self._nav_path = []
            self._active_author = ""
            self._active_author_display = ""
            self._flat_filter_active = False
            self._update_breadcrumbs()
            self._apply_sort()
            self._relayout()
            self._start_thumb_loader()

        finally:
            self.loading_overlay.stop_loading()

    def set_root_dir(self, root_dir: str) -> None:
        self.root_dir = osp.abspath(root_dir)
        self.status_label.setText(f"Library: {self.root_dir}")
        self.scan_library()

    # ── Hierarchical Navigation ───────────────────────────────────────────────

    def _show_author_view_by_name(self, author_name: str) -> None:
        # Find the matching folder path for this author
        # Usually it's the top-level folder name matching author
        target_folder = author_name
        for item in self.items:
            if item.author.lower() == author_name.lower():
                parts = osp.normpath(item.relative_path).split(os.sep)
                if parts:
                    target_folder = parts[0]
                    break
        self._navigate_to([target_folder])

    def _navigate_to(self, target_path: List[str]) -> None:
        """Navigate to any level in the folder hierarchy with scroll preservation."""
        current_key = "/".join(self._nav_path)
        self._scroll_pos_map[current_key] = self.scroll_area.verticalScrollBar().value()

        self._nav_path = list(target_path)
        self._flat_filter_active = False

        if self._nav_path:
            self._active_author = self._nav_path[0].lower()
            self._active_author_display = self._nav_path[0]
            self.toolbar2.show()
        else:
            self._active_author = ""
            self._active_author_display = ""
            self.toolbar2.hide()
            self.search_edit.clear()

        self._update_breadcrumbs()
        self._relayout()

        target_key = "/".join(self._nav_path)
        pos = self._scroll_pos_map.get(target_key, 0)
        self.scroll_area.verticalScrollBar().setValue(pos)
        QTimer.singleShot(0, lambda: self.scroll_area.verticalScrollBar().setValue(pos))

    def _navigate_back(self) -> None:
        if self._flat_filter_active:
            self._flat_filter_active = False
            self.category_combo.blockSignals(True)
            self.category_combo.setCurrentText("All Manga")
            self.category_combo.blockSignals(False)
            self.pill_verified.setChecked(False)
            self.pill_needs_fix.setChecked(False)
            self.pill_unverified.setChecked(False)
            self._navigate_to([])
        elif self._nav_path:
            self._navigate_to(self._nav_path[:-1])

    def return_to_author(self) -> None:
        """Restore the current folder view when returning from reader."""
        self._update_breadcrumbs()
        if self._nav_path:
            self.toolbar2.show()
        else:
            self.toolbar2.hide()
        self._relayout()
        key = "/".join(self._nav_path)
        pos = self._scroll_pos_map.get(key, 0)
        self.scroll_area.verticalScrollBar().setValue(pos)
        QTimer.singleShot(0, lambda: self.scroll_area.verticalScrollBar().setValue(pos))

    def _update_breadcrumbs(self) -> None:
        while self.crumbs_layout.count():
            item = self.crumbs_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._nav_path and not self._flat_filter_active:
            self.breadcrumb_bar.hide()
            return

        self.breadcrumb_bar.show()

        if self._flat_filter_active:
            btn_home = QPushButton("🏠 Library")
            btn_home.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_home.setStyleSheet(
                "QPushButton { background: transparent; border: none; color: #94a3b8; font-weight: bold; font-size: 13px; padding: 2px 4px; }"
                "QPushButton:hover { color: #38bdf8; text-decoration: underline; }"
            )
            btn_home.clicked.connect(lambda: self._navigate_to([]))
            self.crumbs_layout.addWidget(btn_home)

            sep = QLabel("›")
            sep.setStyleSheet("color: #64748b; font-weight: bold; font-size: 13px;")
            self.crumbs_layout.addWidget(sep)

            lbl = QLabel("🔍 All Manga (Filtered)")
            lbl.setStyleSheet("color: #38bdf8; font-weight: bold; font-size: 13px;")
            self.crumbs_layout.addWidget(lbl)
            self.crumbs_layout.addStretch()
            return

        # Home crumb
        btn_home = QPushButton("🏠 Library")
        btn_home.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_home.setStyleSheet(
            "QPushButton { background: transparent; border: none; color: #94a3b8; font-weight: bold; font-size: 13px; padding: 2px 4px; }"
            "QPushButton:hover { color: #38bdf8; text-decoration: underline; }"
        )
        btn_home.clicked.connect(lambda: self._navigate_to([]))
        self.crumbs_layout.addWidget(btn_home)

        for i, segment in enumerate(self._nav_path):
            sep = QLabel("›")
            sep.setStyleSheet("color: #64748b; font-weight: bold; font-size: 13px;")
            self.crumbs_layout.addWidget(sep)

            is_last = (i == len(self._nav_path) - 1)
            icon = "👤" if i == 0 else "📁"
            btn = QPushButton(f"{icon} {segment}")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            if is_last:
                btn.setStyleSheet(
                    "QPushButton { background: transparent; border: none; color: #38bdf8; font-weight: bold; font-size: 13px; padding: 2px 4px; }"
                )
            else:
                btn.setStyleSheet(
                    "QPushButton { background: transparent; border: none; color: #cbd5e1; font-weight: bold; font-size: 13px; padding: 2px 4px; }"
                    "QPushButton:hover { color: #38bdf8; text-decoration: underline; }"
                )
                target = list(self._nav_path[:i + 1])
                btn.clicked.connect(lambda checked, t=target: self._navigate_to(t))
            self.crumbs_layout.addWidget(btn)

        self.crumbs_layout.addStretch()

    # ── Sort ──────────────────────────────────────────────────────────────────

    def _on_sort_changed(self) -> None:
        self._apply_sort()
        self._relayout()

    def _apply_sort(self) -> None:
        sort_mode = self.sort_combo.currentText()
        if "Title" in sort_mode:
            self._all_manga_cards.sort(key=lambda c: _natural_sort_key(c.item.title))
        elif sort_mode == "Page Count":
            self._all_manga_cards.sort(key=lambda c: c.item.page_count, reverse=True)
        else:
            self._all_manga_cards.sort(key=lambda c: c.item.mtime, reverse=True)
        self._author_cards.sort(key=lambda c: _natural_sort_key(c.author))

    # ── Layout ────────────────────────────────────────────────────────────────

    def _relayout(self) -> None:
        cols = max(1, (self.scroll_area.viewport().width() - 24) // 200)

        # Clear grid without destroying widgets
        while self.grid_layout.count():
            self.grid_layout.takeAt(0)

        if not self._nav_path and not self._flat_filter_active:
            self._relayout_authors(cols)
        else:
            self._relayout_hierarchical(cols)

    def _relayout_authors(self, cols: int) -> None:
        for card in self._all_manga_cards:
            card.setVisible(False)
        for fc in self._folder_cards.values():
            fc.setVisible(False)

        filter_text = self.search_edit.text().strip().lower()
        visible: List[AuthorCardWidget] = []
        for ac in self._author_cards:
            show = (not filter_text) or (filter_text in ac.author.lower())
            ac.setVisible(show)
            if show:
                visible.append(ac)

        for i, ac in enumerate(visible):
            self.grid_layout.addWidget(ac, i // cols, i % cols)

        self.status_label.setText(
            f"Showing {len(visible)} author(s) — {len(self.items)} total manga volumes"
        )
        self._update_status_bar(self.items)

    def _relayout_hierarchical(self, cols: int) -> None:
        # Hide author cards
        for ac in self._author_cards:
            ac.setVisible(False)

        filter_text = self.search_edit.text().strip()
        category = self.category_combo.currentText()
        grid_items: list = []

        if self._flat_filter_active or (not self._nav_path and filter_text):
            # Flat search / status filter across everything
            for fc in self._folder_cards.values():
                fc.setVisible(False)
            visible_manga = []
            for card in self._all_manga_cards:
                passes = card.matches(filter_text, category)
                card.setVisible(passes)
                if passes:
                    visible_manga.append(card)
            grid_items.extend(visible_manga)
            self.status_label.setText(f"Showing {len(visible_manga)} of {len(self.items)} manga volumes")
            self._update_status_bar(self.items)
        else:
            # Hierarchical view under self._nav_path
            current_tuple = tuple(self._nav_path)
            current_depth = len(self._nav_path)

            # 1. Show immediate subfolders
            visible_folders: List[FolderCardWidget] = []
            for path_tuple, fc in sorted(self._folder_cards.items(), key=lambda kv: _natural_sort_key(kv[0][-1])):
                # Must be an immediate child folder of self._nav_path
                if len(path_tuple) == current_depth + 1 and path_tuple[:current_depth] == current_tuple:
                    show = fc.matches(filter_text, category)
                    fc.setVisible(show)
                    if show:
                        visible_folders.append(fc)
                else:
                    fc.setVisible(False)

            # 2. Show direct manga items under this folder (never leak nested chapters outside)
            visible_manga: List[MangaCardWidget] = []
            scope_items: List[MangaItem] = []

            for card in self._all_manga_cards:
                norm_rel = osp.normpath(card.item.relative_path)
                parts = tuple(norm_rel.split(os.sep))
                # Check if item is inside this folder hierarchy
                if len(parts) > current_depth and parts[:current_depth] == current_tuple:
                    scope_items.append(card.item)
                    # ONLY show as direct card if it is directly inside this folder (not inside a deeper subfolder)
                    is_direct = (len(parts) == current_depth + 1)
                    passes = is_direct and card.matches(filter_text, category)
                    card.setVisible(passes)
                    if passes:
                        visible_manga.append(card)
                else:
                    card.setVisible(False)

            grid_items.extend(visible_folders)
            grid_items.extend(visible_manga)

            path_display = " › ".join(self._nav_path)
            self.status_label.setText(
                f"Location: {path_display} — {len(visible_folders)} folder(s), {len(visible_manga)} volume(s)"
            )
            self._update_status_bar(scope_items if scope_items else self.items)

        # Place items on grid
        for i, widget in enumerate(grid_items):
            self.grid_layout.addWidget(widget, i // cols, i % cols)

    # ── Status bar helpers ────────────────────────────────────────────────────

    def _update_status_bar(self, items: List[MangaItem]) -> None:
        verified = sum(1 for it in items if it.verification_status == "verified")
        needs_fix = sum(1 for it in items if it.verification_status == "needs_fix")
        unverified = sum(1 for it in items if it.verification_status == "unverified")
        self.pill_verified.setText(f"\u2713 Verified  {verified}")
        self.pill_needs_fix.setText(f"\u26a0 Needs Fix  {needs_fix}")
        self.pill_unverified.setText(f"\u25cb Unverified  {unverified}")

    def _on_pill_clicked(self, status: str) -> None:
        mapping = {
            "verified": "\u2713 Verified Only",
            "needs_fix": "\u26a0 Needs Fix / Retranslate",
            "unverified": "Unverified Only",
        }
        pills = {
            "verified": self.pill_verified,
            "needs_fix": self.pill_needs_fix,
            "unverified": self.pill_unverified,
        }
        target_text = mapping[status]
        current_text = self.category_combo.currentText()

        if current_text == target_text:
            # Clear filter
            self.category_combo.blockSignals(True)
            self.category_combo.setCurrentText("All Manga")
            self.category_combo.blockSignals(False)
            for p in pills.values():
                p.setChecked(False)
            if self._flat_filter_active:
                self._flat_filter_active = False
                self._navigate_to([])
            else:
                self._relayout()
        else:
            # Activate filter
            self.category_combo.blockSignals(True)
            self.category_combo.setCurrentText(target_text)
            self.category_combo.blockSignals(False)
            for key, p in pills.items():
                p.setChecked(key == status)
            if not self._nav_path:
                self._flat_filter_active = True
                self._update_breadcrumbs()
                self.toolbar2.show()
            self._relayout()

    # ── Async thumbnail loading ────────────────────────────────────────────────

    def _start_thumb_loader(self) -> None:
        jobs = [
            (path, MangaCardWidget._THUMB_W, MangaCardWidget._THUMB_H)
            for path in self._cover_to_cards
            if path and osp.exists(path)
        ]
        if not jobs:
            return
        self._thumb_loader = ThumbnailLoaderThread(jobs, parent=self)
        self._thumb_loader.signals.ready.connect(self._on_thumbnail_ready)
        self._thumb_loader.start()

    def _on_thumbnail_ready(self, path: str, pixmap: QPixmap) -> None:
        for card in self._cover_to_cards.get(path, []):
            card.set_thumbnail(pixmap)

    def _cancel_thumb_loader(self) -> None:
        if self._thumb_loader and self._thumb_loader.isRunning():
            self._thumb_loader.cancel()
            self._thumb_loader.wait()
        self._thumb_loader = None

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def _destroy_all_cards(self) -> None:
        self._cancel_thumb_loader()
        while self.grid_layout.count():
            self.grid_layout.takeAt(0)
        for card in self._all_manga_cards:
            card.deleteLater()
        self._all_manga_cards.clear()
        for ac in self._author_cards:
            ac.deleteLater()
        self._author_cards.clear()
        for fc in self._folder_cards.values():
            fc.deleteLater()
        self._folder_cards.clear()

    # ── Resize debounce ───────────────────────────────────────────────────────

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._resize_timer.start()
