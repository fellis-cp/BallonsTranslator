import enum
import logging
from typing import List, Optional, Any

from qtpy.QtWidgets import (
    QGraphicsView,
    QGraphicsScene,
    QGraphicsPixmapItem,
    QGraphicsTextItem,
    QGraphicsRectItem,
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
    QTextDocument,
)

from READER.core.loader import MangaPage

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
    """Interactive graphics canvas for viewing a manga page with speech bubble translations."""

    zoom_changed = Signal(float)
    page_clicked = Signal()
    block_clicked = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)

        self._pixmap_item: Optional[QGraphicsPixmapItem] = None
        self._highlight_item: Optional[QGraphicsRectItem] = None
        self._text_items: List[Any] = []
        self._current_page: Optional[MangaPage] = None

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
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
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

    def load_page(self, page: MangaPage) -> None:
        """Load and display a MangaPage on the scene."""
        self._current_page = page
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
                # Fallback if image path fails
                pixmap = QPixmap(page.image_path)

            if pixmap.isNull():
                # Create a placeholder pixmap if file missing
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

            self.apply_fit_mode()
        finally:
            self.viewport().setUpdatesEnabled(True)

    def _render_text_blocks(self, blocks: List[Any]) -> None:
        """Render dialogue text blocks over the page preserving native styling."""
        for idx, blk in enumerate(blocks):
            if HAS_TEXT_ENGINE and TextBlkItem and isinstance(blk, TextBlock):
                try:
                    # Construct TextBlkItem with block instance for rich text and effect stack setup
                    item = TextBlkItem(blk=blk)
                    item.setData(0, idx)

                    # Toggle translated vs original text based on overlay mode
                    if self._overlay_mode == OverlayMode.ORIGINAL:
                        item.setPlainText("\n".join(blk.text) if blk.text else "")
                    elif self._overlay_mode == OverlayMode.TRANSLATED:
                        if blk.rich_text:
                            item.load_rich_text_html(blk.rich_text)
                        elif blk.translation:
                            item.setPlainText(blk.translation)
                    
                    self._scene.addItem(item)
                    self._text_items.append(item)
                    continue
                except Exception as e:
                    LOGGER.debug(f"TextBlkItem failed for block, falling back: {e}")

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
            if len(rect) == 4 and rect[2] > rect[0] and rect[3] > rect[1]: # xyxy format
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

        if not rich_text and not text_str:
            return

        x, y, w, h = rect[0], rect[1], rect[2], rect[3]
        if w <= 0 or h <= 0:
            return

        item = QGraphicsTextItem()
        item.setData(0, block_idx)
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

    def highlight_block(self, idx: int) -> None:
        """Highlight a text block bounding box on the scene and ensure it is visible."""
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
            brush = QBrush(QColor(0, 229, 255, 40))
            self._highlight_item.setPen(pen)
            self._highlight_item.setBrush(brush)
            self._highlight_item.setZValue(100)
            self._scene.addItem(self._highlight_item)
            self.ensureVisible(qrect, 50, 50)

    # Viewport Zoom & Fit Controls
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

    # Mouse Events
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
        if event.button() == Qt.MouseButton.LeftButton:
            self.page_clicked.emit()
            scene_pos = self.mapToScene(event.pos())
            item = self._scene.itemAt(scene_pos, QTransform())
            if item:
                blk_idx = item.data(0)
                if blk_idx is not None and isinstance(blk_idx, int) and blk_idx >= 0:
                    self.block_clicked.emit(blk_idx)
                    self.highlight_block(blk_idx)
        super().mousePressEvent(event)
