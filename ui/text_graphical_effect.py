from typing import Union, Tuple, Callable

import cv2
import numpy as np
from qtpy.QtCore import Signal, Qt, QPoint, QPointF
from qtpy.QtGui import QColor, QShowEvent, QPixmap, QImage, QPainter, QFontMetricsF, QLinearGradient, QPainterPath
from qtpy.QtWidgets import QHBoxLayout, QVBoxLayout, QGridLayout, QScrollArea, QGroupBox, QPushButton, QLabel, QDialog

from utils import shared as C
from .misc import pixmap2ndarray, ndarray2pixmap
from utils.fontformat import FontFormat, pt2px
from .custom_widget import Widget, ColorPickerLabel, PaintQSlider
import math

def apply_shadow_effect(img: Union[QPixmap, QImage, np.ndarray], color: QColor, strength=1.0, radius=21) -> Tuple[
    QPixmap, np.ndarray, np.ndarray]:
    if isinstance(color, QColor):
        color = [color.red(), color.green(), color.blue()]

    if not isinstance(img, np.ndarray):
        img = pixmap2ndarray(img, keep_alpha=True)

    mask = img[..., -1].copy()
    ksize = radius * 2 + 1
    mask = cv2.GaussianBlur(mask, (ksize, ksize), ksize / 6)
    if strength != 1:
        mask = np.clip(mask.astype(np.float32) * strength, 0, 255).astype(np.uint8)
    bg_img = np.zeros((img.shape[0], img.shape[1], 4), dtype=np.uint8)
    bg_img[..., :3] = np.array(color, np.uint8)[::-1]
    bg_img[..., 3] = mask

    result = ndarray2pixmap(bg_img)
    return result, img


def effect_require_repaint(fontfmt: FontFormat) -> bool:
    return fontfmt.stroke_width > 0 or fontfmt.shadow_radius > 0


def text_effect_preview_pipe(target: QPixmap, font_size: float, fontfmt: FontFormat, inplace=False) -> QPixmap:
    if not inplace:
        target = target.copy()

    if effect_require_repaint(fontfmt):
        painter = QPainter(target)

        # shadow
        if fontfmt.shadow_radius != 0 and fontfmt.shadow_strength > 0:
            r = int(round(fontfmt.shadow_radius * font_size))
            shadow_map, _ = apply_shadow_effect(target, fontfmt.shadow_color, fontfmt.shadow_strength, r)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOver)
            xoffset = int(fontfmt.shadow_offset[0] * font_size)
            yoffset = int(fontfmt.shadow_offset[1] * font_size)
            painter.drawPixmap(xoffset, yoffset, shadow_map)

        painter.end()
    # opacity
    if fontfmt.opacity != 1:
        final = target.copy()
        final.fill(Qt.GlobalColor.transparent)
        painter = QPainter(final)
        painter.setOpacity(fontfmt.opacity)
        painter.drawPixmap(0, 0, target)
        painter.end()
        target = final

    return target


class TextEffectPanelDeprecated(QDialog):
    apply = Signal()

    def __init__(self, update_text_style_label: Callable, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        self.setModal(True)

        self.update_text_style_label = update_text_style_label
        self.fontfmt: FontFormat = None
        self.fontfmt = FontFormat()
        self.active_fontfmt = FontFormat()

        self.preview_label = QLabel(self)
        self.preview_label.setContentsMargins(0, 0, 0, 0)

        font = self.preview_label.font()
        font.setPointSizeF(24)
        self.preview_label.setFont(font)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_text = self.tr("Effect")
        fm = QFontMetricsF(font)
        br = fm.boundingRect(self.preview_text)
        br_w, br_h = br.width(), br.height()
        self.preview_pixmap = QPixmap(int(br_w + br_h * 2), int(br_h * 3))
        self.preview_origin = QPoint(int(br_h), int(1.75 * br_h))
        self.preview_label.setFixedHeight(int(br_h * 2))

        # opacity
        opacity_label = QLabel(self.tr('Opacity'))
        self.opacity_slider = PaintQSlider(self.tr('Opacity'))
        self.opacity_slider.setRange(0, 100)
        self.opacity_slider.valueChanged.connect(self.on_opacity_changed)

        # shadow
        shadow_label = QLabel(self.tr('Shadow'))
        self.shadow_color_picker = ColorPickerLabel(self)
        self.shadow_color_picker.colorChanged.connect(self.on_shadow_color_changed)
        self.shadow_color_picker.setToolTip(self.tr('Change shadow color'))
        self.shadow_radius_slider = PaintQSlider(self.tr('radius'))
        self.shadow_radius_slider.setRange(0, 200)
        self.shadow_radius_slider.valueChanged.connect(self.on_shadow_radius_changed)
        self.shadow_strength_slider = PaintQSlider(self.tr('strength'))
        self.shadow_strength_slider.setRange(0, 300)
        self.shadow_strength_slider.valueChanged.connect(self.on_shadow_strength_changed)
        self.shadow_xoffset_slider = PaintQSlider(self.tr('x offset'))
        self.shadow_xoffset_slider.setRange(-100, 100)
        self.shadow_xoffset_slider.valueChanged.connect(self.on_shadow_xoffset_changed)
        self.shadow_yoffset_slider = PaintQSlider(self.tr('y offset'))
        self.shadow_yoffset_slider.setRange(-100, 100)
        self.shadow_yoffset_slider.valueChanged.connect(self.on_shadow_yoffset_changed)

        self.apply_btn = QPushButton(self.tr('Apply'))
        self.apply_btn.clicked.connect(self.on_apply_clicked)
        self.cancel_btn = QPushButton(self.tr('Cancel'))
        self.cancel_btn.clicked.connect(self.on_cancel_clicked)
        self.scroll_area = QScrollArea(self)
        self.scroll_content = QGroupBox()
        self.scroll_area.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.scroll_content)
        self.scroll_area.setMinimumHeight(200)
        self.setMaximumHeight(C.TEXTEFFECT_MAXHEIGHT)

        shadow_layout = QGridLayout()
        shadow_layout.addWidget(shadow_label, 0, 0)
        shadow_layout.addWidget(self.shadow_radius_slider, 0, 1)
        shadow_layout.addWidget(self.shadow_strength_slider, 0, 2)
        shadow_layout.addWidget(self.shadow_color_picker, 1, 0, Qt.AlignmentFlag.AlignCenter)
        shadow_layout.addWidget(self.shadow_xoffset_slider, 1, 1)
        shadow_layout.addWidget(self.shadow_yoffset_slider, 1, 2)

        opacity_layout = QHBoxLayout()
        opacity_layout.addWidget(opacity_label)
        opacity_layout.addWidget(self.opacity_slider)

        content_layout = QVBoxLayout()
        self.scroll_content.setLayout(content_layout)
        content_layout.addLayout(shadow_layout)
        content_layout.addLayout(opacity_layout)

        dec_layout = QHBoxLayout()
        dec_layout.addWidget(self.apply_btn)
        dec_layout.addWidget(self.cancel_btn)

        vlayout = QVBoxLayout(self)
        vlayout.addWidget(self.preview_label)
        vlayout.addWidget(self.scroll_area)
        vlayout.addLayout(dec_layout)

        self.updatePreviewPixmap()

    def updatePreviewPixmap(self):
        if not self.isVisible():
            return

        self.preview_pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(self.preview_pixmap)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setFont(self.preview_label.font())
        painter.drawText(self.preview_origin, self.preview_text)
        painter.end()

        self.shadow_color_picker.setPickerColor(self.fontfmt.shadow_color)

        if self.fontfmt is not None:
            font_size = pt2px(self.preview_label.font().pointSizeF())
            self.preview_pixmap = text_effect_preview_pipe(self.preview_pixmap, font_size, self.fontfmt, inplace=True)

        self.preview_label.setPixmap(self.preview_pixmap)

    def on_apply_clicked(self):
        self.hide()
        self.active_fontfmt.opacity = self.fontfmt.opacity
        self.active_fontfmt.shadow_color = self.fontfmt.shadow_color
        self.active_fontfmt.shadow_radius = self.fontfmt.shadow_radius
        self.active_fontfmt.shadow_strength = self.fontfmt.shadow_strength
        self.active_fontfmt.shadow_offset = self.fontfmt.shadow_offset
        self.update_text_style_label()
        self.apply.emit()

    def on_cancel_clicked(self):
        self.hide()

    def on_opacity_changed(self):
        self.fontfmt.opacity = self.opacity_slider.value() / 100
        self.updatePreviewPixmap()

    def on_shadow_color_changed(self, is_valid: bool):
        if not is_valid:
            return
        self.fontfmt.shadow_color = self.shadow_color_picker.rgb()
        self.updatePreviewPixmap()

    def on_shadow_radius_changed(self):
        self.fontfmt.shadow_radius = self.shadow_radius_slider.value() / 100
        self.updatePreviewPixmap()

    def on_shadow_strength_changed(self):
        self.fontfmt.shadow_strength = self.shadow_strength_slider.value() / 100
        self.updatePreviewPixmap()

    def on_shadow_xoffset_changed(self):
        self.fontfmt.shadow_offset[0] = self.shadow_xoffset_slider.value() / 100
        self.updatePreviewPixmap()

    def on_shadow_yoffset_changed(self):
        self.fontfmt.shadow_offset[1] = self.shadow_yoffset_slider.value() / 100
        self.updatePreviewPixmap()

    def showEvent(self, e: QShowEvent) -> None:
        self.updatePreviewPixmap()
        return super().showEvent(e)

    def updatePanels(self):
        self.opacity_slider.setValue(int(self.fontfmt.opacity * 100))
        self.shadow_color_picker.setPickerColor(self.fontfmt.shadow_color)
        self.shadow_radius_slider.setValue(int(self.fontfmt.shadow_radius * 100))
        self.shadow_strength_slider.setValue(int(self.fontfmt.shadow_strength * 100))


class GradientPreviewPanel(QDialog):
    apply = Signal()
    gradient_changed = Signal()
    
    def __init__(self, update_text_style_label: Callable, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        self.setModal(True)
        self.update_text_style_label = update_text_style_label
        self.fontfmt: FontFormat = None
        self.fontfmt = FontFormat()
        self.active_fontfmt = FontFormat()

        # Preview label setup
        self.preview_label = QLabel(self)
        self.preview_label.setContentsMargins(0, 0, 0, 0)
        font = self.preview_label.font()
        font.setPointSizeF(24)
        self.preview_label.setFont(font)
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_text = self.tr("Gradient")
        fm = QFontMetricsF(font)
        br = fm.boundingRect(self.preview_text)
        br_w, br_h = br.width(), br.height()
        self.preview_pixmap = QPixmap(int(br_w + br_h * 2), int(br_h * 3))
        self.preview_origin = QPointF(int(br_h), int(1.75 * br_h))

        self.preview_label.setFixedHeight(int(br_h * 2))

        # Enable gradient checkbox
        self.gradient_enable = QGroupBox(self.tr("Enable Gradient"))
        self.gradient_enable.setCheckable(True)
        self.gradient_enable.toggled.connect(self.on_gradient_enabled_changed)

        # Color pickers
        start_color_layout = QHBoxLayout()
        start_color_layout.addWidget(QLabel(self.tr("Start Color:")))
        self.gradient_start_picker = ColorPickerLabel(self)
        self.gradient_start_picker.colorChanged.connect(self.on_gradient_start_color_changed)
        start_color_layout.addWidget(self.gradient_start_picker)

        end_color_layout = QHBoxLayout()
        end_color_layout.addWidget(QLabel(self.tr("End Color:")))
        self.gradient_end_picker = ColorPickerLabel(self)
        self.gradient_end_picker.colorChanged.connect(self.on_gradient_end_color_changed)
        end_color_layout.addWidget(self.gradient_end_picker)

        # Angle slider
        self.angle_slider = PaintQSlider(self.tr("Angle"))
        self.angle_slider.setRange(0, 359)
        self.angle_slider.valueChanged.connect(self.on_gradient_angle_changed)

        # Size slider
        self.size_slider = PaintQSlider(self.tr("Size"))
        self.size_slider.setRange(50, 200)
        self.size_slider.valueChanged.connect(self.on_gradient_size_changed)

        # Buttons
        self.apply_btn = QPushButton(self.tr('Apply'))
        self.apply_btn.clicked.connect(self.on_apply_clicked)
        self.cancel_btn = QPushButton(self.tr('Cancel'))
        self.cancel_btn.clicked.connect(self.on_cancel_clicked)

        # Layout
        gradient_layout = QVBoxLayout()
        gradient_layout.addLayout(start_color_layout)
        gradient_layout.addLayout(end_color_layout)
        gradient_layout.addWidget(self.angle_slider)
        gradient_layout.addWidget(self.size_slider)
        self.gradient_enable.setLayout(gradient_layout)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.apply_btn)
        button_layout.addWidget(self.cancel_btn)

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(self.preview_label)
        main_layout.addWidget(self.gradient_enable)
        main_layout.addLayout(button_layout)

        self.setMaximumHeight(C.TEXTEFFECT_MAXHEIGHT)
        self.updatePreviewPixmap()

    def on_gradient_enabled_changed(self, enabled):
        self.fontfmt.gradient_enabled = enabled
        self.updatePreviewPixmap()

    def on_gradient_start_color_changed(self, is_valid):
        if is_valid:
            color = self.gradient_start_picker.color
            self.fontfmt.gradient_start_color = list(color.getRgb()[:3])  # Convert to list and take only RGB
            self.updatePreviewPixmap()

    def on_gradient_end_color_changed(self, is_valid):
        if is_valid:
            color = self.gradient_end_picker.color
            self.fontfmt.gradient_end_color = list(color.getRgb()[:3])  # Convert to list and take only RGB
            self.updatePreviewPixmap()

    def on_gradient_angle_changed(self, value):
        self.fontfmt.gradient_angle = float(value)
        self.updatePreviewPixmap()

    def on_gradient_size_changed(self, value):
        self.fontfmt.gradient_size = value / 100
        self.updatePreviewPixmap()

    def updatePreviewPixmap(self):
        if not self.isVisible():
            return

        self.preview_pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(self.preview_pixmap)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setFont(self.preview_label.font())

        if self.fontfmt.gradient_enabled:
            # Create gradient
            gradient = QLinearGradient()
            angle = self.fontfmt.gradient_angle
            rad = math.radians(angle)
            dx = math.cos(rad)
            dy = math.sin(rad)
            
            rect = self.preview_pixmap.rect()
            center = rect.center()
            radius = max(rect.width(), rect.height()) * self.fontfmt.gradient_size
            gradient.setStart(center.x() - dx * radius, center.y() - dy * radius)
            gradient.setFinalStop(center.x() + dx * radius, center.y() + dy * radius)
            
            start_color = QColor(*self.fontfmt.gradient_start_color)
            end_color = QColor(*self.fontfmt.gradient_end_color)
            gradient.setColorAt(0, start_color)
            gradient.setColorAt(1, end_color)
            
            painter.setBrush(gradient)
            painter.setPen(Qt.PenStyle.NoPen)
            
            # Draw text with gradient
            path = QPainterPath()
            path.addText(self.preview_origin, self.preview_label.font(), self.preview_text)
            painter.drawPath(path)
        else:
            painter.drawText(self.preview_origin, self.preview_text)
        
        painter.end()
        self.preview_label.setPixmap(self.preview_pixmap)

    def on_apply_clicked(self):
        self.active_fontfmt.gradient_enabled = self.fontfmt.gradient_enabled
        self.active_fontfmt.gradient_start_color = self.fontfmt.gradient_start_color
        self.active_fontfmt.gradient_end_color = self.fontfmt.gradient_end_color
        self.active_fontfmt.gradient_angle = self.fontfmt.gradient_angle
        self.active_fontfmt.gradient_size = self.fontfmt.gradient_size
        
        self.gradient_changed.emit()
        self.update_text_style_label()
        self.apply.emit()
        self.hide()

    def on_cancel_clicked(self):
        self.hide()

    def showEvent(self, e: QShowEvent) -> None:
        self.updatePreviewPixmap()
        return super().showEvent(e)

    def updatePanels(self):
        self.gradient_enable.setChecked(self.fontfmt.gradient_enabled)
        self.gradient_start_picker.setPickerColor(self.fontfmt.gradient_start_color)
        self.gradient_end_picker.setPickerColor(self.fontfmt.gradient_end_color)
        self.angle_slider.setValue(int(self.fontfmt.gradient_angle))
        self.size_slider.setValue(int(self.fontfmt.gradient_size * 100))
