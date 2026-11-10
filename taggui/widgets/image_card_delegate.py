"""Draws each image in the image list as a card: the thumbnail with the file
name under it. Completed (locked) images get a green check badge."""
from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from utils.image import Image

# Model role that says whether an image is marked complete.
COMPLETED_ROLE = Qt.ItemDataRole.UserRole + 1
CARD_MARGIN = 5
CARD_PADDING = 6
CARD_RADIUS = 8


class ImageCardDelegate(QStyledItemDelegate):
    def __init__(self, view, image_width: int):
        super().__init__(view)
        self.view = view
        self.image_width = image_width

    def available_width(self) -> int:
        viewport_width = self.view.viewport().width()
        return max(48, viewport_width - 2 * (CARD_MARGIN + CARD_PADDING))

    def thumbnail_size(self, image: Image) -> QSize:
        width = min(self.image_width, self.available_width())
        if image is None or not image.dimensions or not image.dimensions[0]:
            return QSize(width, width)
        image_width, image_height = image.dimensions
        height = int(width * image_height / image_width)
        # Very tall images are capped like the classic list (3x the width).
        if height > width * 3:
            height = width * 3
            width = int(height * image_width / image_height)
        return QSize(max(1, width), max(1, height))

    def name_height(self, option) -> int:
        return QFontMetrics(option.font).height() + 4

    def sizeHint(self, option, index) -> QSize:
        image = index.data(Qt.ItemDataRole.UserRole)
        thumbnail = self.thumbnail_size(image)
        height = (thumbnail.height() + self.name_height(option)
                  + 2 * (CARD_MARGIN + CARD_PADDING))
        return QSize(self.view.viewport().width(), height)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = option.palette
        image: Image = index.data(Qt.ItemDataRole.UserRole)
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        is_hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        is_completed = bool(index.data(COMPLETED_ROLE))
        card = QRectF(option.rect).adjusted(CARD_MARGIN, CARD_MARGIN,
                                            -CARD_MARGIN, -CARD_MARGIN)
        base = palette.color(palette.ColorRole.Base)
        is_dark = base.lightness() < 128
        background = QColor(base).lighter(135) if is_dark else QColor(
            base).darker(104)
        highlight = palette.color(palette.ColorRole.Highlight)
        if is_selected:
            background = QColor(highlight)
            background.setAlpha(70)
        elif is_hovered:
            background = background.lighter(115) if is_dark else (
                background.darker(106))
        path = QPainterPath()
        path.addRoundedRect(card, CARD_RADIUS, CARD_RADIUS)
        painter.fillPath(path, background)
        if is_selected:
            painter.setPen(QPen(highlight, 2))
            painter.drawPath(path)
        # Thumbnail.
        thumbnail_size = self.thumbnail_size(image)
        icon: QIcon = index.data(Qt.ItemDataRole.DecorationRole)
        top = int(card.top()) + CARD_PADDING
        left = int(card.left() + (card.width() - thumbnail_size.width()) / 2)
        thumbnail_rect = QRect(left, top, thumbnail_size.width(),
                               thumbnail_size.height())
        if icon is not None and not icon.isNull():
            pixmap = icon.pixmap(thumbnail_size)
            clip = QPainterPath()
            clip.addRoundedRect(QRectF(thumbnail_rect), 5, 5)
            painter.setClipPath(clip)
            painter.drawPixmap(thumbnail_rect, pixmap)
            painter.setClipping(False)
            if is_completed:
                painter.fillRect(thumbnail_rect, QColor(0, 0, 0, 70))
        # File name.
        name_rect = QRect(int(card.left()) + CARD_PADDING,
                          thumbnail_rect.bottom() + 3,
                          int(card.width()) - 2 * CARD_PADDING,
                          self.name_height(option))
        metrics = QFontMetrics(option.font)
        name = image.path.name if image is not None else ''
        painter.setPen(palette.color(palette.ColorRole.Text))
        painter.drawText(name_rect, Qt.AlignmentFlag.AlignHCenter
                         | Qt.AlignmentFlag.AlignVCenter,
                         metrics.elidedText(name, Qt.TextElideMode.ElideMiddle,
                                            name_rect.width()))
        if is_completed:
            radius = 11
            center_x = thumbnail_rect.right() - radius - 4
            center_y = thumbnail_rect.top() + radius + 4
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor('#2e7d32'))
            painter.drawEllipse(QRectF(center_x - radius, center_y - radius,
                                       2 * radius, 2 * radius))
            pen = QPen(QColor('white'), 2.4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(center_x - 5, center_y, center_x - 1,
                             center_y + 4)
            painter.drawLine(center_x - 1, center_y + 4, center_x + 6,
                             center_y - 4)
        painter.restore()
