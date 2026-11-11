"""Draws each image in the image list as a picture card like TagBench's image
list (src/App.tsx `.tb-row`, src/index.css): a square thumbnail, the file
name as a tooltip, a purple tint on selected images, a bar on the current
one, and a green border with a check mark on images marked complete."""
from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

# Model role that says whether an image is marked complete.
COMPLETED_ROLE = Qt.ItemDataRole.UserRole + 1
CARD_MARGIN = 2
CARD_PADDING = 3
CARD_RADIUS = 8


class ImageCardDelegate(QStyledItemDelegate):
    def __init__(self, view, image_width: int):
        super().__init__(view)
        self.view = view
        self.image_width = image_width

    def side(self) -> int:
        viewport_width = self.view.viewport().width()
        return max(48, min(self.image_width, viewport_width
                           - 2 * (CARD_MARGIN + CARD_PADDING)))

    def sizeHint(self, option, index) -> QSize:
        return QSize(self.view.viewport().width(),
                     self.side() + 2 * (CARD_MARGIN + CARD_PADDING))

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        is_current = self.view.currentIndex() == index
        is_completed = bool(index.data(COMPLETED_ROLE))
        side = self.side()
        card_width = side + 2 * CARD_PADDING
        left = option.rect.left() + (option.rect.width() - card_width) / 2
        card = QRectF(left, option.rect.top() + CARD_MARGIN, card_width,
                      side + 2 * CARD_PADDING)
        path = QPainterPath()
        path.addRoundedRect(card, CARD_RADIUS, CARD_RADIUS)
        if is_selected:
            painter.fillPath(path, QColor(140, 110, 220, 71))
        # Square thumbnail, cropped to fill like `object-fit: cover`.
        thumbnail_rect = QRectF(card.left() + CARD_PADDING,
                                card.top() + CARD_PADDING, side, side)
        clip = QPainterPath()
        clip.addRoundedRect(thumbnail_rect, 6, 6)
        painter.fillPath(clip, QColor('#111111'))
        icon: QIcon = index.data(Qt.ItemDataRole.DecorationRole)
        if icon is not None and not icon.isNull():
            sizes = icon.availableSizes()
            source = icon.pixmap(sizes[0] if sizes else QSize(side, side))
            if not source.isNull():
                scale = max(side / source.width(), side / source.height())
                width = source.width() * scale
                height = source.height() * scale
                target = QRectF(thumbnail_rect.center().x() - width / 2,
                                thumbnail_rect.center().y() - height / 2,
                                width, height)
                painter.setClipPath(clip)
                painter.drawPixmap(target, source, QRectF(source.rect()))
                painter.setClipping(False)
        if is_completed:
            painter.setPen(QPen(QColor('#3dcb78'), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        if is_current:
            # `box-shadow: inset 3px 0 0`: a bar on the left edge.
            painter.save()
            painter.setClipPath(path)
            painter.fillRect(QRectF(card.left(), card.top(), 3,
                                    card.height()), QColor('#c9a4f2'))
            painter.restore()
        if is_completed:
            badge = QRectF(card.right() - 8 - 18, card.top() + 8, 18, 18)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(12, 12, 16, 184))
            painter.drawEllipse(badge)
            font = QFont(option.font)
            font.setPixelSize(12)
            painter.setFont(font)
            painter.setPen(QColor('#9ad29a'))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, '\u2713')
        painter.restore()
