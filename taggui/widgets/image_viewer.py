from pathlib import Path

import numpy as np
from PySide6.QtCore import (QEvent, QModelIndex, QPointF, QRectF, QSize, Qt,
                            Signal, Slot)
from PySide6.QtGui import (QColor, QImage, QImageReader, QKeySequence,
                           QPainter, QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel,
                               QMessageBox, QPushButton, QSizePolicy,
                               QSpinBox, QVBoxLayout, QWidget)

from models.proxy_image_list_model import ProxyImageListModel
from utils import edit_history, image_editing
from utils.image import Image

MODE_VIEW, MODE_CROP, MODE_REMOVE = 'view', 'crop', 'remove'
HANDLE_DISTANCE = 10
MAX_UNDO_STEPS = 30


class ImageLabel(QWidget):
    """Shows the image; in crop or remove mode, edits it."""
    edit_state_changed = Signal()
    apply_requested = Signal()
    cancel_requested = Signal()
    undo_requested = Signal()
    mode_shortcut_pressed = Signal(str)

    def __init__(self):
        super().__init__()
        self.image_path = None
        self.image = QImage()
        self.scaled_pixmap = None
        self.mode = MODE_VIEW
        self.crop_rect = QRectF()
        self.drag_handle = None
        self.drag_start = None
        self.drag_start_rect = None
        self.mask = None
        self.last_brush_point = None
        self.brush_size = 40
        self.cursor_pos = None
        self.can_undo = lambda: False
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        self.setMinimumSize(QSize(1, 1))
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    # Loading and geometry.
    def load_image(self, image_path: Path):
        self.image_path = image_path
        reader = QImageReader(str(image_path))
        reader.setAutoTransform(True)
        self.image = reader.read()
        self.scaled_pixmap = None
        self.reset_edit()
        self.update()

    def reset_edit(self):
        self.crop_rect = QRectF(0, 0, self.image.width(), self.image.height())
        self.mask = None
        self.last_brush_point = None
        self.edit_state_changed.emit()

    def has_pending_edit(self) -> bool:
        if self.mode == MODE_CROP:
            return self.crop_rect.toRect() != self.image.rect()
        if self.mode == MODE_REMOVE:
            return self.mask is not None
        return False

    def image_target_rect(self) -> QRectF:
        if self.image.isNull():
            return QRectF()
        size = QSize(self.image.size()).scaled(
            self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        x = (self.width() - size.width()) / 2
        y = (self.height() - size.height()) / 2
        return QRectF(x, y, size.width(), size.height())

    def scale(self) -> float:
        target = self.image_target_rect()
        if target.width() == 0:
            return 1.0
        return target.width() / self.image.width()

    def to_image(self, point: QPointF) -> QPointF:
        target = self.image_target_rect()
        s = self.scale()
        return QPointF((point.x() - target.x()) / s,
                       (point.y() - target.y()) / s)

    def to_widget_rect(self, rect: QRectF) -> QRectF:
        target = self.image_target_rect()
        s = self.scale()
        return QRectF(target.x() + rect.x() * s, target.y() + rect.y() * s,
                      rect.width() * s, rect.height() * s)

    def resizeEvent(self, event):
        self.scaled_pixmap = None
        super().resizeEvent(event)

    # Painting.
    def paintEvent(self, event):
        if self.image.isNull():
            return
        painter = QPainter(self)
        target = self.image_target_rect()
        ratio = self.devicePixelRatioF()
        if (self.scaled_pixmap is None or self.scaled_pixmap.size()
                != (target.size() * ratio).toSize()):
            pixmap = QPixmap.fromImage(self.image.scaled(
                (target.size() * ratio).toSize(),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
            pixmap.setDevicePixelRatio(ratio)
            self.scaled_pixmap = pixmap
        painter.drawPixmap(target.topLeft(), self.scaled_pixmap)
        if self.mode == MODE_CROP:
            crop = self.to_widget_rect(self.crop_rect)
            outside = QPainterPath()
            outside.addRect(target)
            inside = QPainterPath()
            inside.addRect(crop)
            painter.fillPath(outside.subtracted(inside), QColor(0, 0, 0, 150))
            painter.setPen(QPen(QColor(255, 255, 255), 1))
            painter.drawRect(crop)
            # Rule of thirds.
            painter.setPen(QPen(QColor(255, 255, 255, 90), 1))
            for i in (1, 2):
                x = crop.left() + crop.width() * i / 3
                y = crop.top() + crop.height() * i / 3
                painter.drawLine(QPointF(x, crop.top()),
                                 QPointF(x, crop.bottom()))
                painter.drawLine(QPointF(crop.left(), y),
                                 QPointF(crop.right(), y))
            painter.setPen(QPen(QColor(255, 255, 255), 3))
            for corner in (crop.topLeft(), crop.topRight(),
                           crop.bottomLeft(), crop.bottomRight()):
                painter.drawRect(QRectF(corner.x() - 4, corner.y() - 4, 8, 8))
            painter.setPen(QColor(255, 255, 255))
            painter.drawText(crop.adjusted(4, 4, 0, 0),
                             Qt.AlignmentFlag.AlignLeft,
                             f'{int(self.crop_rect.width())} x '
                             f'{int(self.crop_rect.height())}')
        elif self.mode == MODE_REMOVE:
            if self.mask is not None:
                painter.setOpacity(0.5)
                painter.drawImage(target, self.mask)
                painter.setOpacity(1)
            if self.cursor_pos is not None:
                radius = self.brush_size * self.scale() / 2
                painter.setPen(QPen(QColor(255, 255, 255), 1))
                painter.drawEllipse(self.cursor_pos, radius, radius)
                painter.setPen(QPen(QColor(0, 0, 0), 1))
                painter.drawEllipse(self.cursor_pos, radius + 1, radius + 1)

    # Crop interaction.
    def crop_handle_at(self, pos: QPointF):
        crop = self.to_widget_rect(self.crop_rect)
        d = HANDLE_DISTANCE
        near_left = abs(pos.x() - crop.left()) <= d
        near_right = abs(pos.x() - crop.right()) <= d
        near_top = abs(pos.y() - crop.top()) <= d
        near_bottom = abs(pos.y() - crop.bottom()) <= d
        in_x = crop.left() - d <= pos.x() <= crop.right() + d
        in_y = crop.top() - d <= pos.y() <= crop.bottom() + d
        handle = ''
        if near_top and in_x:
            handle += 't'
        elif near_bottom and in_x:
            handle += 'b'
        if near_left and in_y:
            handle += 'l'
        elif near_right and in_y:
            handle += 'r'
        if handle:
            return handle
        if crop.contains(pos):
            return 'move'
        return None

    def update_crop_cursor(self, pos):
        handle = self.crop_handle_at(pos)
        cursors = {'t': Qt.CursorShape.SizeVerCursor,
                   'b': Qt.CursorShape.SizeVerCursor,
                   'l': Qt.CursorShape.SizeHorCursor,
                   'r': Qt.CursorShape.SizeHorCursor,
                   'tl': Qt.CursorShape.SizeFDiagCursor,
                   'br': Qt.CursorShape.SizeFDiagCursor,
                   'tr': Qt.CursorShape.SizeBDiagCursor,
                   'bl': Qt.CursorShape.SizeBDiagCursor,
                   'move': Qt.CursorShape.SizeAllCursor}
        self.setCursor(cursors.get(handle, Qt.CursorShape.ArrowCursor))

    def drag_crop(self, pos: QPointF):
        start = self.drag_start_rect
        delta = self.to_image(pos) - self.to_image(self.drag_start)
        width, height = self.image.width(), self.image.height()
        left, top = start.left(), start.top()
        right, bottom = start.right(), start.bottom()
        if self.drag_handle == 'move':
            dx = min(max(delta.x(), -left), width - right)
            dy = min(max(delta.y(), -top), height - bottom)
            left, right, top, bottom = (left + dx, right + dx, top + dy,
                                        bottom + dy)
        else:
            minimum = 8
            if 'l' in self.drag_handle:
                left = min(max(0, left + delta.x()), right - minimum)
            if 'r' in self.drag_handle:
                right = max(min(width, right + delta.x()), left + minimum)
            if 't' in self.drag_handle:
                top = min(max(0, top + delta.y()), bottom - minimum)
            if 'b' in self.drag_handle:
                bottom = max(min(height, bottom + delta.y()), top + minimum)
        self.crop_rect = QRectF(round(left), round(top), round(right - left),
                                round(bottom - top))
        self.edit_state_changed.emit()

    # Brush interaction.
    def paint_brush(self, pos: QPointF, erase: bool = False):
        if self.mask is None:
            if erase:
                return
            self.mask = QImage(self.image.size(),
                               QImage.Format.Format_ARGB32_Premultiplied)
            self.mask.fill(Qt.GlobalColor.transparent)
            self.edit_state_changed.emit()
        point = self.to_image(pos)
        painter = QPainter(self.mask)
        if erase:
            # Right button: erase the painted mask under the brush (no
            # antialiasing, so no faint leftovers count as mask).
            painter.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_Clear)
        else:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(255, 0, 0), self.brush_size + (2 if erase else 0),
                   Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                   Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        start = self.last_brush_point or point
        if start == point:
            # A single dab (a zero-length line draws nothing when erasing).
            radius = pen.widthF() / 2
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 0, 0))
            painter.drawEllipse(point, radius, radius)
        else:
            painter.drawLine(start, point)
        painter.end()
        self.last_brush_point = point

    def mask_array(self) -> np.ndarray:
        mask = self.mask.convertToFormat(QImage.Format.Format_ARGB32)
        width, height = mask.width(), mask.height()
        data = np.frombuffer(mask.constBits(), np.uint8,
                             count=mask.bytesPerLine() * height)
        data = data.reshape(height, mask.bytesPerLine())[:, :width * 4]
        alpha = data.reshape(height, width, 4)[:, :, 3]
        return (alpha > 0).astype(np.uint8) * 255

    # Events.
    def mousePressEvent(self, event):
        self.setFocus()
        pos = event.position()
        if (event.button() == Qt.MouseButton.RightButton
                and self.mode == MODE_REMOVE):
            self.last_brush_point = None
            self.paint_brush(pos, erase=True)
            self.update()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self.mode == MODE_CROP:
            self.drag_handle = self.crop_handle_at(pos)
            self.drag_start = pos
            self.drag_start_rect = QRectF(self.crop_rect)
        elif self.mode == MODE_REMOVE:
            self.last_brush_point = None
            self.paint_brush(pos)
            self.update()

    def contextMenuEvent(self, event):
        # No context menu while using the remove brush (right = eraser).
        event.accept()

    def is_mask_empty(self) -> bool:
        return self.mask is None or not self.mask_array().any()

    def mouseMoveEvent(self, event):
        pos = event.position()
        if self.mode == MODE_CROP:
            if self.drag_handle and event.buttons():
                self.drag_crop(pos)
                self.update()
            else:
                self.update_crop_cursor(pos)
        elif self.mode == MODE_REMOVE:
            self.cursor_pos = pos
            if event.buttons() & Qt.MouseButton.LeftButton:
                self.paint_brush(pos)
            elif event.buttons() & Qt.MouseButton.RightButton:
                self.paint_brush(pos, erase=True)
            self.update()

    def mouseReleaseEvent(self, event):
        self.drag_handle = None
        self.last_brush_point = None
        if (self.mode == MODE_REMOVE and self.mask is not None
                and event.button() == Qt.MouseButton.RightButton
                and self.is_mask_empty()):
            # Everything was erased: nothing left to apply.
            self.mask = None
            self.edit_state_changed.emit()
            self.update()

    def leaveEvent(self, event):
        self.cursor_pos = None
        self.update()

    def wheelEvent(self, event):
        # Ctrl+wheel (or plain wheel in remove mode) changes the brush size.
        if self.mode == MODE_REMOVE:
            step = 5 if event.angleDelta().y() > 0 else -5
            self.mode_shortcut_pressed.emit(f'brush:{step}')
            event.accept()
        else:
            super().wheelEvent(event)

    def event(self, event):
        # Take these keys before the window's shortcuts (Ctrl+Z is tag undo).
        if event.type() == QEvent.Type.ShortcutOverride:
            if (event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter,
                                Qt.Key.Key_Escape, Qt.Key.Key_C,
                                Qt.Key.Key_J, Qt.Key.Key_BracketLeft,
                                Qt.Key.Key_BracketRight)
                    and not event.modifiers()
                    & ~Qt.KeyboardModifier.KeypadModifier):
                event.accept()
                return True
        return super().event(event)

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.apply_requested.emit()
        elif key == Qt.Key.Key_Escape:
            self.cancel_requested.emit()
        elif key == Qt.Key.Key_C:
            self.mode_shortcut_pressed.emit(MODE_CROP)
        elif key == Qt.Key.Key_J:
            self.mode_shortcut_pressed.emit(MODE_REMOVE)
        elif key == Qt.Key.Key_BracketLeft:
            self.mode_shortcut_pressed.emit('brush:-5')
        elif key == Qt.Key.Key_BracketRight:
            self.mode_shortcut_pressed.emit('brush:5')
        else:
            super().keyPressEvent(event)


class ScrubSpinBox(QSpinBox):
    """A spin box that also works as a scrubby slider: press and drag left
    or right to change the value. A plain click still lets you type."""
    SCRUB_THRESHOLD = 3

    def __init__(self):
        super().__init__()
        self.scrub_start_x = None
        self.scrub_start_value = 0
        self.is_scrubbing = False
        self.lineEdit().installEventFilter(self)
        self.lineEdit().setCursor(Qt.CursorShape.SizeHorCursor)
        self.setToolTip('Drag left or right to change the size, or click '
                        'and type')

    def eventFilter(self, watched, event):
        event_type = event.type()
        if (event_type == QEvent.Type.MouseButtonPress
                and event.button() == Qt.MouseButton.LeftButton):
            self.scrub_start_x = event.globalPosition().x()
            self.scrub_start_value = self.value()
            self.is_scrubbing = False
        elif (event_type == QEvent.Type.MouseMove
              and self.scrub_start_x is not None
              and event.buttons() & Qt.MouseButton.LeftButton):
            dx = event.globalPosition().x() - self.scrub_start_x
            if not self.is_scrubbing and abs(dx) >= self.SCRUB_THRESHOLD:
                self.is_scrubbing = True
            if self.is_scrubbing:
                # Faster for big brushes.
                step = max(1, self.scrub_start_value // 50)
                self.setValue(int(self.scrub_start_value + dx * step))
                self.lineEdit().deselect()
                return True
        elif event_type == QEvent.Type.MouseButtonRelease:
            was_scrubbing = self.is_scrubbing
            self.scrub_start_x = None
            self.is_scrubbing = False
            if was_scrubbing:
                self.lineEdit().deselect()
                return True
        return super().eventFilter(watched, event)


class ImageViewer(QWidget):
    image_edited = Signal()
    history_changed = Signal()

    def __init__(self, proxy_image_list_model: ProxyImageListModel):
        super().__init__()
        self.proxy_image_list_model = proxy_image_list_model
        self.proxy_image_index = QModelIndex()
        # Each entry: (path, file bytes before the edit, description).
        self.edit_undo_stack: list[tuple[Path, bytes, str, int]] = []
        # Each entry: (path, file bytes after the edit, description, seq).
        self.edit_redo_stack: list[tuple[Path, bytes, str, int]] = []
        edit_history.on_new_edit(self.handle_new_edit)
        self.image_label = ImageLabel()
        self.image_label.can_undo = lambda: bool(self.edit_undo_stack)

        self.crop_button = QPushButton('Crop (C)')
        self.crop_button.setCheckable(True)
        self.remove_button = QPushButton('Remove Brush (J)')
        self.remove_button.setCheckable(True)
        self.brush_size_label = QLabel('Brush size')
        self.brush_size_spin_box = ScrubSpinBox()
        self.brush_size_spin_box.setRange(2, 1000)
        self.brush_size_spin_box.setValue(40)
        self.brush_size_spin_box.setSuffix(' px')
        self.brush_size_spin_box.setToolTip(
            'Drag left/right to change the size, click to type. [ and ] or '
            'the mouse wheel also work.')
        self.apply_button = QPushButton('Apply (Enter)')
        self.cancel_button = QPushButton('Cancel (Esc)')
        self.undo_button = QPushButton('Undo Edit')
        self.undo_button.setToolTip('Undo the last crop or removal (Ctrl+Z)')
        self.redo_button = QPushButton('Redo Edit')
        self.redo_button.setToolTip('Redo the last undone crop or removal '
                                    '(Ctrl+Y)')
        self.status_label = QLabel()
        # Long hints must not widen the window.
        self.status_label.setSizePolicy(QSizePolicy.Policy.Ignored,
                                        QSizePolicy.Policy.Preferred)
        toolbar = QHBoxLayout()
        for widget in (self.crop_button, self.remove_button,
                       self.brush_size_label, self.brush_size_spin_box,
                       self.apply_button, self.cancel_button,
                       self.undo_button, self.redo_button):
            toolbar.addWidget(widget)
        toolbar.addWidget(self.status_label, stretch=1)
        layout = QVBoxLayout(self)
        layout.addLayout(toolbar)
        layout.addWidget(self.image_label, stretch=1)

        self.crop_button.clicked.connect(
            lambda: self.toggle_mode(MODE_CROP))
        self.remove_button.clicked.connect(
            lambda: self.toggle_mode(MODE_REMOVE))
        self.brush_size_spin_box.valueChanged.connect(self.set_brush_size)
        self.apply_button.clicked.connect(self.apply_edit)
        self.cancel_button.clicked.connect(self.cancel_edit)
        self.undo_button.clicked.connect(self.undo_edit)
        self.redo_button.clicked.connect(self.redo_edit)
        self.image_label.apply_requested.connect(self.apply_edit)
        self.image_label.cancel_requested.connect(self.cancel_edit)
        self.image_label.undo_requested.connect(self.undo_edit)
        self.image_label.mode_shortcut_pressed.connect(self.handle_shortcut)
        self.image_label.edit_state_changed.connect(self.update_controls)
        self.update_controls()

    @Slot()
    def load_image(self, proxy_image_index: QModelIndex):
        image: Image = self.proxy_image_list_model.data(
            proxy_image_index, Qt.ItemDataRole.UserRole)
        self.proxy_image_index = proxy_image_index
        self.image_label.load_image(image.path)
        self.update_controls()

    def set_brush_size(self, size: int):
        self.image_label.brush_size = size
        self.image_label.update()

    def handle_shortcut(self, name: str):
        if name.startswith('brush:'):
            self.brush_size_spin_box.setValue(
                self.brush_size_spin_box.value() + int(name[6:]))
        else:
            self.toggle_mode(name)

    def toggle_mode(self, mode: str):
        label = self.image_label
        new_mode = MODE_VIEW if label.mode == mode else mode
        label.mode = new_mode
        label.reset_edit()
        label.setCursor(Qt.CursorShape.CrossCursor
                        if new_mode == MODE_REMOVE
                        else Qt.CursorShape.ArrowCursor)
        label.setFocus()
        label.update()
        self.update_controls()

    def update_controls(self):
        label = self.image_label
        self.crop_button.setChecked(label.mode == MODE_CROP)
        self.remove_button.setChecked(label.mode == MODE_REMOVE)
        is_remove = label.mode == MODE_REMOVE
        self.brush_size_label.setVisible(is_remove)
        self.brush_size_spin_box.setVisible(is_remove)
        pending = label.has_pending_edit()
        self.apply_button.setEnabled(pending)
        self.cancel_button.setEnabled(label.mode != MODE_VIEW)
        self.undo_button.setEnabled(bool(self.edit_undo_stack))
        self.redo_button.setEnabled(bool(self.edit_redo_stack))
        if label.mode == MODE_CROP:
            self.status_label.setText('Drag the edges or corners, then Enter '
                                      'to crop.')
        elif label.mode == MODE_REMOVE:
            self.status_label.setText('Paint over what to remove, then Enter.')
        else:
            self.status_label.setText('')

    def cancel_edit(self):
        if self.image_label.mode != MODE_VIEW:
            self.toggle_mode(self.image_label.mode)

    def apply_edit(self):
        label = self.image_label
        if not label.has_pending_edit() or label.image_path is None:
            return
        path = Path(label.image_path)
        before = path.read_bytes()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if label.mode == MODE_CROP:
                rect = label.crop_rect.toRect()
                image_editing.crop_image_file(
                    path, (rect.left(), rect.top(),
                           rect.left() + rect.width(),
                           rect.top() + rect.height()))
                description = 'Crop'
            else:
                self.status_label.setText('Removing...')
                QApplication.processEvents()
                image_editing.inpaint_image_file(path, label.mask_array())
                description = 'Remove'
        except Exception as exception:
            path.write_bytes(before)
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, 'Edit failed', str(exception))
            return
        QApplication.restoreOverrideCursor()
        self.edit_undo_stack.append((path, before, description,
                                     edit_history.next_seq()))
        del self.edit_undo_stack[:-MAX_UNDO_STEPS]
        self.edit_redo_stack.clear()
        edit_history.new_edit('image')
        self.history_changed.emit()
        mode = label.mode
        self.refresh_after_edit(path)
        # A crop ends crop mode; the remove brush stays on for the next
        # strokes (as in Photoshop).
        label.mode = MODE_REMOVE if mode == MODE_REMOVE else MODE_VIEW
        if label.mode == MODE_VIEW:
            label.setCursor(Qt.CursorShape.ArrowCursor)
        label.reset_edit()
        label.update()
        self.update_controls()
        if description == 'Remove' and image_editing.last_inpaint_method:
            self.status_label.setText(
                f'Removed with {image_editing.last_inpaint_method}.')

    def undo_edit(self):
        if not self.edit_undo_stack:
            return
        path, before, description, _ = self.edit_undo_stack.pop()
        after = path.read_bytes() if path.exists() else b''
        path.write_bytes(before)
        self.edit_redo_stack.append((path, after, description,
                                     edit_history.next_seq()))
        self.refresh_after_edit(path)
        self.update_controls()
        self.history_changed.emit()

    def redo_edit(self):
        if not self.edit_redo_stack:
            return
        path, after, description, _ = self.edit_redo_stack.pop()
        before = path.read_bytes() if path.exists() else b''
        path.write_bytes(after)
        self.edit_undo_stack.append((path, before, description,
                                     edit_history.next_seq()))
        self.refresh_after_edit(path)
        self.update_controls()
        self.history_changed.emit()

    def handle_new_edit(self, source: str):
        # A new tag edit makes image redo meaningless (and vice versa).
        if source != 'image' and self.edit_redo_stack:
            self.edit_redo_stack.clear()
            self.update_controls()
            self.history_changed.emit()

    def top_undo(self):
        """(seq, description) of the next image edit to undo, or None."""
        if not self.edit_undo_stack:
            return None
        return self.edit_undo_stack[-1][3], self.edit_undo_stack[-1][2]

    def top_redo(self):
        if not self.edit_redo_stack:
            return None
        return self.edit_redo_stack[-1][3], self.edit_redo_stack[-1][2]

    def refresh_after_edit(self, path: Path):
        """Reload the viewer and the thumbnail of the edited image."""
        source_model = self.proxy_image_list_model.sourceModel()
        for row, image in enumerate(source_model.images):
            if Path(image.path) == path:
                image.thumbnail = None
                reader = QImageReader(str(path))
                reader.setAutoTransform(True)
                size = reader.size()
                if size.isValid():
                    image.dimensions = (size.width(), size.height())
                index = source_model.index(row)
                source_model.dataChanged.emit(index, index)
                break
        if self.image_label.image_path and \
                Path(self.image_label.image_path) == path:
            mode = self.image_label.mode
            self.image_label.load_image(path)
            # Never come back into crop mode after an edit, undo or redo.
            self.image_label.mode = MODE_VIEW if mode == MODE_CROP else mode
            if self.image_label.mode == MODE_VIEW:
                self.image_label.setCursor(Qt.CursorShape.ArrowCursor)
            self.image_label.update()
        self.image_edited.emit()
