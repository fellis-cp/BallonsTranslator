import enum
import logging
from typing import List, Optional, Any

from qtpy.QtWidgets import (
    QGraphicsView,
    QGraphicsScene,
    QGraphicsPixmapItem,
    QGraphicsTextItem,
    QGraphicsRectItem,
    QGraphicsItem,
    QMenu,
    QAction,
    QApplication,
)
from qtpy.QtCore import Qt, QRectF, QPointF, Signal, QPoint
from qtpy.QtGui import (
    QPixmap,
    QImage,
    QColor,
    QFont,
    QPainter,
    QPen,
    QBrush,
    QTransform,
    QWheelEvent,
    QMouseEvent,
    QContextMenuEvent,
    QKeyEvent,
)

from READER.core.loader import MangaPage
from READER.core.style_utils import (
    get_reference_fontformat,
    apply_fontformat_to_block,
    generate_block_rich_text,
)

LOGGER = logging.getLogger('READER.manga_canvas')

# Attempt importing TextBlkItem from ballontranslator
HAS_TEXT_ENGINE = False
try:
    from ballontranslator.ui.text_engine.item import TextBlkItem
    from ballontranslator.utils.textblock import TextBlock
    HAS_TEXT_ENGINE = True
except ImportError:
    TextBlkItem = None
    TextBlock = None


class OverlayMode(enum.Enum):
    TRANSLATED = 'translated'
    ORIGINAL = 'original'
    RAW_ONLY = 'raw_only'


class FitMode(enum.Enum):
    FIT_SCREEN = 'fit_screen'
    FIT_WIDTH = 'fit_width'
    FREE_ZOOM = 'free_zoom'


class MangaCanvas(QGraphicsView):
    """Interactive graphics canvas matching BalloonsTranslator text box manipulation, selection, and direct editing."""

    zoom_changed = Signal(float)
    page_clicked = Signal()
    block_clicked = Signal(int)
    block_added = Signal(int)
    block_deleted = Signal(int)
    block_modified = Signal(int)
    add_box_mode_changed = Signal(bool)
    ocr_requested = Signal(int)
    translate_requested = Signal(int)
    ocr_page_requested = Signal()
    translate_page_requested = Signal()
    delete_block_requested = Signal(int)
    block_geometry_committed = Signal(int, list, list)  # (block_idx, old_rect, new_rect)
    block_text_committed = Signal(int, str, object, object)  # (block_idx, field, old_val, new_val)
    apply_style_requested = Signal(int)
    apply_style_page_requested = Signal()
    undo_requested = Signal()
    redo_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        self._pixmap_item: Optional[QGraphicsPixmapItem] = None
        self._highlight_item: Optional[QGraphicsRectItem] = None
        self._temp_rect_item: Optional[QGraphicsRectItem] = None
        self._text_items: List[Any] = []
        self._current_page: Optional[MangaPage] = None
        self._project_data: Optional[Any] = None
        self._block_start_geom: dict = {}
        self._block_start_text: dict = {}

        self._selected_block_idx: int = -1
        self._add_box_mode: bool = False
        self._drag_start_pos: Optional[QPointF] = None
        self._is_panning: bool = False
        self._pan_start_pos: Optional[QPoint] = None
        self._space_pressed: bool = False

        self._overlay_mode: OverlayMode = OverlayMode.TRANSLATED
        self._fit_mode: FitMode = FitMode.FIT_SCREEN
        self._use_inpainted_bg: bool = True
        self._zoom_factor: float = 1.0

        # Viewport setup
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
            | QPainter.RenderHint.TextAntialiasing
        )
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setStyleSheet("background-color: #0d0f17; border: none;")

    @property
    def zoom_factor(self) -> float:
        return self._zoom_factor

    @property
    def overlay_mode(self) -> OverlayMode:
        return self._overlay_mode

    def set_overlay_mode(self, mode: OverlayMode) -> None:
        if self._overlay_mode != mode:
            self._overlay_mode = mode
            self.reload_current_page()

    def set_fit_mode(self, mode: FitMode) -> None:
        self._fit_mode = mode
        self.apply_fit_mode()

    def set_use_inpainted_bg(self, use_inp: bool) -> None:
        if self._use_inpainted_bg != use_inp:
            self._use_inpainted_bg = use_inp
            self.reload_current_page()

    def set_project_data(self, project_data: Optional[Any]) -> None:
        """Store reference to parent project data for cross-page style discovery."""
        self._project_data = project_data

    def load_page(self, page: MangaPage) -> None:
        """Load and display a MangaPage on the scene."""
        self._current_page = page
        self._selected_block_idx = -1
        self._block_start_geom.clear()
        self._block_start_text.clear()
        self.reload_current_page()

    def reload_current_page(self) -> None:
        """Refresh background image and text block overlays for current page."""
        self.viewport().setUpdatesEnabled(False)
        try:
            self._scene.clear()
            self._text_items.clear()
            self._pixmap_item = None
            self._highlight_item = None

            if not self._current_page:
                return

            page = self._current_page

            # Choose background image
            bg_path = page.image_path
            if self._use_inpainted_bg and page.has_inpainted and page.inpainted_image_path:
                bg_path = page.inpainted_image_path

            pixmap = QPixmap(bg_path)
            if pixmap.isNull():
                pixmap = QPixmap(page.image_path)

            if pixmap.isNull():
                pixmap = QPixmap(800, 1200)
                pixmap.fill(QColor(30, 34, 48))
                painter = QPainter(pixmap)
                painter.setPen(QColor(241, 245, 249))
                painter.setFont(QFont("sans-serif", 16))
                painter.drawText(
                    pixmap.rect(),
                    Qt.AlignmentFlag.AlignCenter,
                    f"Missing Image:\n{page.page_name}",
                )
                painter.end()

            self._pixmap_item = self._scene.addPixmap(pixmap)
            self._scene.setSceneRect(QRectF(pixmap.rect()))

            # Render text block overlays unless RAW_ONLY
            if self._overlay_mode != OverlayMode.RAW_ONLY and page.blocks:
                self._render_text_blocks(page.blocks)

            if self._selected_block_idx >= 0 and page.blocks and self._selected_block_idx < len(page.blocks):
                self.highlight_block(self._selected_block_idx)

            self.apply_fit_mode()
        finally:
            self.viewport().setUpdatesEnabled(True)

    def _render_text_blocks(self, blocks: List[Any]) -> None:
        """Render dialogue text blocks using native BalloonsTranslator TextBlkItem when available."""
        for idx, blk in enumerate(blocks):
            if HAS_TEXT_ENGINE and TextBlkItem and isinstance(blk, TextBlock):
                try:
                    item = TextBlkItem(blk=blk, idx=idx, show_rect=True)
                    item.setData(0, idx)
                    item.set_order_badge_visible(True)

                    if self._overlay_mode == OverlayMode.ORIGINAL:
                        # Show source text; re-apply format for color/weight/stroke.
                        item.setPlainText("\n".join(blk.text) if blk.text else "")
                        item.set_fontformat(blk.fontformat, set_char_format=True, set_stroke_width=True)
                    elif self._overlay_mode == OverlayMode.TRANSLATED:
                        if blk.rich_text:
                            # rich_text carries its own inline styling — nothing extra needed.
                            pass
                        elif blk.translation:
                            # initTextBlock called setPlainText() internally which resets Qt's
                            # character format (foreground color, weight, italic, letter-spacing,
                            # stroke). Only document().defaultFont() (family + size) survives.
                            # Re-apply fontformat here to restore all char-level properties.
                            item.set_fontformat(blk.fontformat, set_char_format=True, set_stroke_width=True)
                            generate_block_rich_text(blk)

                    # Connect interactive item signals
                    item.leftbutton_pressed.connect(self._on_item_pressed)
                    item.moving.connect(self._on_item_geometry_changed)
                    item.reshaped.connect(self._on_item_geometry_changed)
                    if hasattr(item, 'move_interaction_finished'):
                        item.move_interaction_finished.connect(self._on_item_move_finished)
                    if hasattr(item, 'begin_edit'):
                        item.begin_edit.connect(self._on_item_begin_edit)
                    item.end_edit.connect(self._on_item_text_edited)

                    self._scene.addItem(item)
                    self._text_items.append(item)
                    continue
                except Exception as e:
                    LOGGER.debug(f"TextBlkItem failed for block #{idx}, falling back: {e}")

            # Fallback custom text block renderer
            self._render_fallback_block(blk, idx)

    def _render_fallback_block(self, blk: Any, block_idx: int = -1) -> None:
        """Fallback block renderer using Qt standard QGraphicsTextItem."""
        rect = [0, 0, 100, 50]
        text_str = ""
        rich_text = ""
        font_family = "Microsoft YaHei UI"
        font_size = 15
        frgb = (0, 0, 0)
        srgb = (255, 255, 255)
        angle = 0
        italic = False
        bold = False

        if isinstance(blk, dict):
            rect = blk.get('_bounding_rect') or blk.get('xyxy') or rect
            if len(rect) == 4 and rect[2] > rect[0] and rect[3] > rect[1]:  # xyxy format
                rect = [rect[0], rect[1], rect[2] - rect[0], rect[3] - rect[1]]
            text_str = blk.get('translation') if self._overlay_mode == OverlayMode.TRANSLATED else "\n".join(blk.get('text', []))
            if self._overlay_mode == OverlayMode.TRANSLATED:
                rich_text = blk.get('rich_text', '')
            angle = blk.get('angle', 0)
            fmt = blk.get('fontformat', {})
            if isinstance(fmt, dict):
                font_family = fmt.get('font_family', font_family)
                font_size = fmt.get('font_size', font_size)
                frgb = fmt.get('frgb', frgb)
                srgb = fmt.get('srgb', srgb)
                italic = fmt.get('italic', italic)
                fw = fmt.get('font_weight', 400)
                bold = fw >= 600 if isinstance(fw, (int, float)) else False
        elif hasattr(blk, 'translation'):
            if blk._bounding_rect and len(blk._bounding_rect) == 4:
                rect = blk._bounding_rect
            elif blk.xyxy and len(blk.xyxy) == 4:
                rect = [blk.xyxy[0], blk.xyxy[1], blk.xyxy[2] - blk.xyxy[0], blk.xyxy[3] - blk.xyxy[1]]
            text_str = blk.translation if self._overlay_mode == OverlayMode.TRANSLATED else "\n".join(blk.text or [])
            if self._overlay_mode == OverlayMode.TRANSLATED:
                rich_text = getattr(blk, 'rich_text', '')
            angle = getattr(blk, 'angle', 0)
            fmt = getattr(blk, 'fontformat', None)
            if fmt:
                font_family = getattr(fmt, 'font_family', font_family)
                font_size = getattr(fmt, 'font_size', font_size)
                frgb = getattr(fmt, 'frgb', frgb)
                srgb = getattr(fmt, 'srgb', srgb)
                italic = getattr(fmt, 'italic', italic)
                fw = getattr(fmt, 'font_weight', 400)
                bold = fw >= 600 if isinstance(fw, (int, float)) else False

        x, y, w, h = rect[0], rect[1], rect[2], rect[3]
        if w <= 0 or h <= 0:
            return

        item = QGraphicsTextItem()
        item.setData(0, block_idx)
        item.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
        )
        if rich_text:
            item.setHtml(rich_text)
        else:
            item.setPlainText(text_str)
            font = QFont(font_family, int(font_size))
            font.setItalic(italic)
            font.setBold(bold)
            item.setFont(font)
            item.setDefaultTextColor(QColor(*frgb))

        item.setTextWidth(w)
        item.setPos(x, y)
        if angle != 0:
            item.setTransformOriginPoint(w / 2, h / 2)
            item.setRotation(angle)

        self._scene.addItem(item)
        self._text_items.append(item)

    # ── Interactive Item Event Handlers ──────────────────────────────────────

    def _on_item_pressed(self, idx: int) -> None:
        self.select_and_focus_block(idx)
        if self._current_page and self._current_page.blocks and 0 <= idx < len(self._current_page.blocks):
            blk = self._current_page.blocks[idx]
            rect = getattr(blk, '_bounding_rect', None)
            if not rect and hasattr(blk, 'xyxy') and len(blk.xyxy) == 4:
                rect = [blk.xyxy[0], blk.xyxy[1], blk.xyxy[2] - blk.xyxy[0], blk.xyxy[3] - blk.xyxy[1]]
            elif isinstance(blk, dict):
                rect = blk.get('_bounding_rect') or blk.get('xyxy')
            if rect and len(rect) == 4:
                self._block_start_geom[idx] = list(rect)

    def _on_item_move_finished(self) -> None:
        idx = self._selected_block_idx
        if idx in self._block_start_geom and self._current_page and self._current_page.blocks:
            old_rect = self._block_start_geom.pop(idx)
            if 0 <= idx < len(self._current_page.blocks):
                blk = self._current_page.blocks[idx]
                new_rect = getattr(blk, '_bounding_rect', None)
                if not new_rect and hasattr(blk, 'xyxy') and len(blk.xyxy) == 4:
                    new_rect = [blk.xyxy[0], blk.xyxy[1], blk.xyxy[2] - blk.xyxy[0], blk.xyxy[3] - blk.xyxy[1]]
                elif isinstance(blk, dict):
                    new_rect = blk.get('_bounding_rect')
                if new_rect and list(new_rect) != old_rect:
                    self.block_geometry_committed.emit(idx, old_rect, list(new_rect))

    def _on_item_begin_edit(self, idx: int) -> None:
        if self._current_page and self._current_page.blocks and 0 <= idx < len(self._current_page.blocks):
            blk = self._current_page.blocks[idx]
            orig = list(blk.text) if hasattr(blk, 'text') and isinstance(blk.text, list) else []
            trans = getattr(blk, 'translation', '') if not isinstance(blk, dict) else blk.get('translation', '')
            self._block_start_text[idx] = (orig, trans)

    def _on_item_geometry_changed(self, item: Any) -> None:
        """Sync moved/resized item coordinates back to TextBlock."""
        if not self._current_page or not self._current_page.blocks:
            return
        idx = item.data(0) if hasattr(item, 'data') else getattr(item, 'idx', -1)
        if idx is not None and 0 <= idx < len(self._current_page.blocks):
            blk = self._current_page.blocks[idx]
            pos = item.pos()
            br = item.boundingRect()
            x1 = int(pos.x())
            y1 = int(pos.y())
            w = int(br.width())
            h = int(br.height())
            x2 = x1 + w
            y2 = y1 + h

            if hasattr(blk, 'xyxy'):
                blk.xyxy = [x1, y1, x2, y2]
            if hasattr(blk, '_bounding_rect'):
                blk._bounding_rect = [x1, y1, w, h]
            elif isinstance(blk, dict):
                blk['xyxy'] = [x1, y1, x2, y2]
                blk['_bounding_rect'] = [x1, y1, w, h]

            self.block_modified.emit(idx)

    def _on_item_text_edited(self, idx: int) -> None:
        """Sync direct canvas text edits back to TextBlock."""
        if not self._current_page or not self._current_page.blocks:
            return
        if 0 <= idx < len(self._current_page.blocks):
            blk = self._current_page.blocks[idx]
            old_orig, old_trans = self._block_start_text.pop(idx, (None, None))
            if idx < len(self._text_items):
                itm = self._text_items[idx]
                if hasattr(itm, 'toPlainText'):
                    new_text = itm.toPlainText()
                    if self._overlay_mode == OverlayMode.TRANSLATED:
                        if hasattr(blk, 'translation'):
                            blk.translation = new_text
                        elif isinstance(blk, dict):
                            blk['translation'] = new_text
                        generate_block_rich_text(blk)
                        if old_trans is not None and old_trans != new_text:
                            self.block_text_committed.emit(idx, 'translation', old_trans, new_text)
                    else:
                        lines = new_text.split('\n')
                        if hasattr(blk, 'text'):
                            blk.text = lines
                        elif isinstance(blk, dict):
                            blk['text'] = lines
                        if old_orig is not None and old_orig != lines:
                            self.block_text_committed.emit(idx, 'text', old_orig, lines)
            self.block_modified.emit(idx)

    @property
    def add_box_mode(self) -> bool:
        return self._add_box_mode

    def set_add_box_mode(self, enabled: bool) -> None:
        """Toggle text box drawing mode on canvas."""
        self._add_box_mode = enabled
        if enabled:
            self.viewport().setCursor(Qt.CursorShape.CrossCursor)
        else:
            self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
            if self._temp_rect_item:
                try:
                    self._scene.removeItem(self._temp_rect_item)
                except Exception:
                    pass
                self._temp_rect_item = None
            self._drag_start_pos = None
        self.add_box_mode_changed.emit(enabled)

    def select_and_focus_block(self, idx: int) -> None:
        """Select a block, highlight it, and emit block_clicked signal."""
        self._selected_block_idx = idx
        self.highlight_block(idx)
        self.block_clicked.emit(idx)

    def delete_selected_block(self) -> None:
        """Delete currently selected text block (emits request so undo/redo can handle)."""
        if not self._current_page or not self._current_page.blocks:
            return
        idx = self._selected_block_idx
        if 0 <= idx < len(self._current_page.blocks):
            self.delete_block_requested.emit(idx)

    def highlight_block(self, idx: int) -> None:
        """Highlight a text block bounding box on the scene with bright glowing indicator."""
        self._selected_block_idx = idx
        if self._highlight_item:
            try:
                self._scene.removeItem(self._highlight_item)
            except Exception:
                pass
            self._highlight_item = None

        if not self._current_page or not self._current_page.blocks or idx < 0 or idx >= len(self._current_page.blocks):
            return

        blk = self._current_page.blocks[idx]
        rect = [0, 0, 100, 50]
        if hasattr(blk, '_bounding_rect') and blk._bounding_rect:
            rect = blk._bounding_rect
        elif hasattr(blk, 'xyxy') and len(blk.xyxy) == 4:
            x1, y1, x2, y2 = blk.xyxy
            rect = [x1, y1, x2 - x1, y2 - y1]
        elif isinstance(blk, dict):
            r = blk.get('_bounding_rect') or blk.get('xyxy') or []
            if len(r) == 4:
                rect = [r[0], r[1], r[2] - r[0], r[3] - r[1]] if r[2] > r[0] else r

        x, y, w, h = rect[0], rect[1], rect[2], rect[3]
        if w > 0 and h > 0:
            qrect = QRectF(x, y, w, h)
            self._highlight_item = QGraphicsRectItem(qrect)
            pen = QPen(QColor(0, 229, 255), 3, Qt.PenStyle.SolidLine)
            brush = QBrush(QColor(0, 229, 255, 35))
            self._highlight_item.setPen(pen)
            self._highlight_item.setBrush(brush)
            self._highlight_item.setZValue(100)
            self._scene.addItem(self._highlight_item)
            self.ensureVisible(qrect, 50, 50)

    # ── Viewport Zoom & Fit Controls ─────────────────────────────────────────

    def apply_fit_mode(self) -> None:
        if not self._pixmap_item or self._scene.sceneRect().isEmpty():
            return

        self.resetTransform()
        scene_rect = self._scene.sceneRect()
        viewport_rect = self.viewport().rect()

        if viewport_rect.isEmpty() or scene_rect.isEmpty():
            return

        if self._fit_mode == FitMode.FIT_SCREEN:
            self.fitInView(scene_rect, Qt.AspectRatioMode.KeepAspectRatio)
            self._zoom_factor = self.transform().m11()
        elif self._fit_mode == FitMode.FIT_WIDTH:
            scale_w = viewport_rect.width() / scene_rect.width()
            self.scale(scale_w, scale_w)
            self._zoom_factor = scale_w
        elif self._fit_mode == FitMode.FREE_ZOOM:
            self.scale(self._zoom_factor, self._zoom_factor)

        self.zoom_changed.emit(self._zoom_factor)

    def set_zoom(self, factor: float) -> None:
        factor = max(0.1, min(5.0, factor))
        self._fit_mode = FitMode.FREE_ZOOM
        self._zoom_factor = factor
        self.resetTransform()
        self.scale(factor, factor)
        self.zoom_changed.emit(self._zoom_factor)

    def zoom_in(self) -> None:
        self.set_zoom(self._zoom_factor * 1.15)

    def zoom_out(self) -> None:
        self.set_zoom(self._zoom_factor / 1.15)

    def reset_zoom(self) -> None:
        self.set_zoom(1.0)

    # ── Mouse & Key Events ───────────────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_pressed = True
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
            event.accept()
            return
        elif event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self._selected_block_idx >= 0:
            self.delete_selected_block()
            event.accept()
            return
        elif event.key() == Qt.Key.Key_Escape and self._add_box_mode:
            self.set_add_box_mode(False)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._space_pressed = False
            if not self._add_box_mode:
                self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().keyReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta > 0:
                self.zoom_in()
            else:
                self.zoom_out()
            event.accept()
        else:
            super().wheelEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._fit_mode in (FitMode.FIT_SCREEN, FitMode.FIT_WIDTH):
            self.apply_fit_mode()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        # Middle click or Space+LeftClick initiates canvas panning
        if event.button() == Qt.MouseButton.MiddleButton or (event.button() == Qt.MouseButton.LeftButton and self._space_pressed):
            self._is_panning = True
            self._pan_start_pos = event.pos()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return

        if event.button() == Qt.MouseButton.LeftButton:
            if self._add_box_mode:
                self._drag_start_pos = self.mapToScene(event.pos())
                qrect = QRectF(self._drag_start_pos, self._drag_start_pos)
                self._temp_rect_item = QGraphicsRectItem(qrect)
                pen = QPen(QColor(0, 229, 255), 2, Qt.PenStyle.DashLine)
                brush = QBrush(QColor(0, 229, 255, 30))
                self._temp_rect_item.setPen(pen)
                self._temp_rect_item.setBrush(brush)
                self._temp_rect_item.setZValue(200)
                self._scene.addItem(self._temp_rect_item)
                event.accept()
                return

            # Check if clicked on a text block
            scene_pos = self.mapToScene(event.pos())
            clicked_idx = -1
            for item in self._scene.items(scene_pos):
                if hasattr(item, 'idx') and item.idx is not None and isinstance(item.idx, int):
                    clicked_idx = item.idx
                    break
                data_val = item.data(0)
                if data_val is not None and isinstance(data_val, int) and data_val >= 0:
                    clicked_idx = data_val
                    break

            if clicked_idx >= 0:
                self.select_and_focus_block(clicked_idx)
            else:
                self.page_clicked.emit()

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._is_panning and self._pan_start_pos:
            delta = event.pos() - self._pan_start_pos
            self._pan_start_pos = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return

        if self._add_box_mode and self._drag_start_pos and self._temp_rect_item:
            current_pos = self.mapToScene(event.pos())
            x1 = min(self._drag_start_pos.x(), current_pos.x())
            y1 = min(self._drag_start_pos.y(), current_pos.y())
            w = abs(current_pos.x() - self._drag_start_pos.x())
            h = abs(current_pos.y() - self._drag_start_pos.y())
            self._temp_rect_item.setRect(QRectF(x1, y1, w, h))
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._is_panning:
            self._is_panning = False
            self._pan_start_pos = None
            if self._space_pressed:
                self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
            elif self._add_box_mode:
                self.viewport().setCursor(Qt.CursorShape.CrossCursor)
            else:
                self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
            event.accept()
            return

        if self._add_box_mode and self._drag_start_pos and event.button() == Qt.MouseButton.LeftButton:
            end_pos = self.mapToScene(event.pos())
            if self._temp_rect_item:
                try:
                    self._scene.removeItem(self._temp_rect_item)
                except Exception:
                    pass
                self._temp_rect_item = None

            x1 = int(min(self._drag_start_pos.x(), end_pos.x()))
            y1 = int(min(self._drag_start_pos.y(), end_pos.y()))
            x2 = int(max(self._drag_start_pos.x(), end_pos.x()))
            y2 = int(max(self._drag_start_pos.y(), end_pos.y()))
            w = x2 - x1
            h = y2 - y1

            self._drag_start_pos = None

            if w >= 10 and h >= 10 and self._current_page is not None:
                ref_fmt = get_reference_fontformat(
                    current_page=self._current_page,
                    project_data=self._project_data,
                )

                if TextBlock is not None:
                    new_blk = TextBlock(xyxy=[x1, y1, x2, y2])
                    new_blk._bounding_rect = [x1, y1, w, h]
                    if hasattr(new_blk, 'set_lines_by_xywh'):
                        new_blk.set_lines_by_xywh([x1, y1, w, h])
                    new_blk.text = []
                    new_blk.translation = ""
                    if ref_fmt is not None:
                        apply_fontformat_to_block(new_blk, ref_fmt, generate_rich_text=False, preserve_size=False)
                else:
                    new_blk = {
                        'xyxy': [x1, y1, x2, y2],
                        '_bounding_rect': [x1, y1, w, h],
                        'text': [],
                        'translation': '',
                    }
                    if ref_fmt is not None:
                        apply_fontformat_to_block(new_blk, ref_fmt, generate_rich_text=False, preserve_size=False)

                if self._current_page.blocks is None:
                    self._current_page.blocks = []
                self._current_page.blocks.append(new_blk)
                new_idx = len(self._current_page.blocks) - 1

                self.set_add_box_mode(False)
                self.reload_current_page()
                self.select_and_focus_block(new_idx)
                self.block_added.emit(new_idx)
                event.accept()
                return

            self.set_add_box_mode(False)
            event.accept()
            return

        super().mouseReleaseEvent(event)

    # ── Context Menu (Right Click) ───────────────────────────────────────────

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        scene_pos = self.mapToScene(event.pos())
        clicked_idx = -1
        for item in self._scene.items(scene_pos):
            if hasattr(item, 'idx') and item.idx is not None and isinstance(item.idx, int):
                clicked_idx = item.idx
                break
            data_val = item.data(0)
            if data_val is not None and isinstance(data_val, int) and data_val >= 0:
                clicked_idx = data_val
                break

        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #1e293b;
                color: #f8fafc;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #0284c7;
                color: white;
            }
            QMenu::separator {
                height: 1px;
                background-color: #334155;
                margin: 4px 0px;
            }
        """)

        # Add Undo / Redo actions at top of context menu
        act_undo = menu.addAction("↶ Undo")
        act_undo.triggered.connect(self.undo_requested.emit)
        act_redo = menu.addAction("↷ Redo")
        act_redo.triggered.connect(self.redo_requested.emit)
        menu.addSeparator()

        if clicked_idx >= 0:
            self.select_and_focus_block(clicked_idx)
            blk = self._current_page.blocks[clicked_idx] if self._current_page and self._current_page.blocks else None

            act_ocr = menu.addAction(f"🔍 OCR Block #{clicked_idx + 1}")
            act_ocr.triggered.connect(lambda: self.ocr_requested.emit(clicked_idx))

            act_trans = menu.addAction(f"⚡ Translate Block #{clicked_idx + 1}")
            act_trans.triggered.connect(lambda: self.translate_requested.emit(clicked_idx))

            act_style = menu.addAction(f"🎨 Apply Page Style to Block #{clicked_idx + 1}")
            act_style.triggered.connect(lambda: self.apply_style_requested.emit(clicked_idx))

            menu.addSeparator()

            act_copy_orig = menu.addAction("📋 Copy Original Text")
            act_copy_orig.triggered.connect(lambda: self._copy_block_text(blk, 'text'))

            act_copy_trans = menu.addAction("📋 Copy Translation")
            act_copy_trans.triggered.connect(lambda: self._copy_block_text(blk, 'translation'))

            menu.addSeparator()

            act_del = menu.addAction(f"🗑 Delete Block #{clicked_idx + 1}")
            act_del.triggered.connect(self.delete_selected_block)
        else:
            act_add = menu.addAction("➕ Add Text Box Here")
            act_add.triggered.connect(lambda: self.set_add_box_mode(True))

            act_style_page = menu.addAction("🎨 Apply Style to All Blocks on Page")
            act_style_page.triggered.connect(self.apply_style_page_requested.emit)

            menu.addSeparator()

            act_ocr_page = menu.addAction("🔍 OCR Entire Page")
            act_ocr_page.triggered.connect(self.ocr_page_requested.emit)

            act_trans_page = menu.addAction("⚡ Translate Entire Page")
            act_trans_page.triggered.connect(self.translate_page_requested.emit)

        menu.exec_(event.globalPos())

    def _copy_block_text(self, blk: Any, field: str) -> None:
        if not blk:
            return
        val = ""
        if field == 'text':
            if hasattr(blk, 'text'):
                val = "\n".join(blk.text) if isinstance(blk.text, list) else str(blk.text or '')
            elif isinstance(blk, dict):
                val = "\n".join(blk.get('text', []))
        elif field == 'translation':
            if hasattr(blk, 'translation'):
                val = str(blk.translation or '')
            elif isinstance(blk, dict):
                val = str(blk.get('translation', ''))

        if val:
            QApplication.clipboard().setText(val)
