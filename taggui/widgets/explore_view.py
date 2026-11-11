"""TagBench's Explore views (src/Explore.tsx): Waterfall, a wall of every
picture, and Constellation, a map of how the dataset's tags go together.
Both run locally on the tags and pictures already loaded."""
import html
import math
import time
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QFont, QImageReader, QMouseEvent,
                           QPainter, QPainterPath, QPen, QPixmap, QPolygonF)
from PySide6.QtWidgets import (QAbstractScrollArea, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QToolButton,
                               QToolTip, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from utils.image import Image
from utils.tag_graph import ClusterModel, Node, link_radius

VIEWS = [('tags', 'Tags', 'Ctrl 1'), ('waterfall', 'Waterfall', 'Ctrl 2'),
         ('constellation', 'Constellation', 'Ctrl 3')]


class ViewRail(QFrame):
    """The Tags / Waterfall / Constellation switch. The mouse wheel over it
    steps through the views."""
    view_requested = Signal(str)

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName('viewRail')
        self.setStyleSheet(
            '#viewRail { background: rgba(13, 15, 18, 240); border: 1px solid '
            'rgba(255, 255, 255, 36); border-radius: 10px; }'
            '#viewRail QPushButton { border-radius: 8px; background: '
            'transparent; border: 1px solid transparent; min-width: 124px; '
            'min-height: 38px; }'
            '#viewRail QPushButton:checked { border-color: #8fe0dc; '
            'background: rgba(143, 224, 220, 30); }'
            '#viewRail QLabel { background: transparent; }')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        self.buttons: dict[str, QPushButton] = {}
        for view, label, hint in VIEWS:
            button = QPushButton()
            button.setCheckable(True)
            inner = QVBoxLayout(button)
            inner.setContentsMargins(10, 4, 10, 4)
            inner.setSpacing(1)
            name_label = QLabel(label)
            name_label.setObjectName('name')
            hint_label = QLabel(hint)
            hint_label.setStyleSheet(
                'color: #7fd9ff; font: 10px "monospace";')
            name_label.setStyleSheet('color: #c8ccd2; font-size: 13px;')
            inner.addWidget(name_label)
            inner.addWidget(hint_label)
            button.toggled.connect(
                lambda checked, name=name_label: name.setStyleSheet(
                    'color: #ffffff; font-size: 13px;' if checked
                    else 'color: #c8ccd2; font-size: 13px;'))
            button.clicked.connect(
                lambda _=False, v=view: self.view_requested.emit(v))
            layout.addWidget(button)
            self.buttons[view] = button
        self.view = 'tags'
        self.wheel_lock = 0.0
        self.set_view('tags')

    def set_view(self, view: str):
        self.view = view
        for name, button in self.buttons.items():
            button.setChecked(name == view)

    def wheelEvent(self, event):
        event.accept()
        delta = event.angleDelta()
        step = delta.y() if abs(delta.y()) >= abs(delta.x()) else delta.x()
        if not step:
            return
        now = time.monotonic()
        if now - self.wheel_lock < 0.38:
            return
        self.wheel_lock = now
        order = [view for view, _, _ in VIEWS]
        index = order.index(self.view) + (1 if step < 0 else -1)
        if 0 <= index < len(order):
            self.view_requested.emit(order[index])


class WaterfallView(QAbstractScrollArea):
    """Every picture in columns at least 220 px wide."""
    image_clicked = Signal(object, bool)
    image_menu_requested = Signal(object, QPoint)

    COLUMN_WIDTH = 220
    GAP = 8

    def __init__(self):
        super().__init__()
        self.images: list[Image] = []
        self.active: Image | None = None
        self.selected: set[int] = set()
        self.rects: list[QRectF] = []
        self.pixmaps: dict[tuple[Path, int], QPixmap] = {}
        self.pending: list[int] = []
        self.loader = QTimer(self)
        self.loader.setInterval(0)
        self.loader.timeout.connect(self.load_some)
        self.content_height = 0
        self.column_width = self.COLUMN_WIDTH
        self.viewport().setStyleSheet('background: #000000;')
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.verticalScrollBar().valueChanged.connect(self.viewport().update)

    def set_images(self, images: list[Image]):
        self.images = images
        self.relayout()

    def set_selection(self, active: Image | None, selected: list[Image]):
        self.active = active
        self.selected = {id(image) for image in selected}
        self.viewport().update()

    def relayout(self):
        width = self.viewport().width() - 2 * self.GAP
        columns = max(1, (width + self.GAP)
                      // (self.COLUMN_WIDTH + self.GAP))
        column_width = max(40, (width - self.GAP * (columns - 1)) / columns)
        self.column_width = int(column_width)
        heights = [float(self.GAP)] * columns
        self.rects = []
        for image in self.images:
            if image.dimensions and image.dimensions[0]:
                image_width, image_height = image.dimensions
                height = column_width * image_height / image_width
            else:
                height = column_width
            column = heights.index(min(heights))
            x = self.GAP + column * (column_width + self.GAP)
            self.rects.append(QRectF(x, heights[column], column_width,
                                     height))
            heights[column] += height + self.GAP
        self.content_height = int(max(heights)) if self.images else 0
        bar = self.verticalScrollBar()
        bar.setPageStep(self.viewport().height())
        bar.setSingleStep(60)
        bar.setRange(0, max(0, self.content_height
                            - self.viewport().height()))
        self.viewport().update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.relayout()

    def pixmap_for(self, index: int) -> QPixmap | None:
        image = self.images[index]
        return self.pixmaps.get((image.path, self.column_width))

    def load_some(self):
        started = time.monotonic()
        while self.pending and time.monotonic() - started < 0.03:
            index = self.pending.pop(0)
            if index >= len(self.images):
                continue
            image = self.images[index]
            key = (image.path, self.column_width)
            if key in self.pixmaps:
                continue
            reader = QImageReader(str(image.path))
            reader.setAutoTransform(True)
            rect = self.rects[index]
            reader.setScaledSize(QSize(int(rect.width()),
                                       max(1, int(rect.height()))))
            loaded = reader.read()
            self.pixmaps[key] = (QPixmap.fromImage(loaded)
                                 if not loaded.isNull() else QPixmap())
        if not self.pending:
            self.loader.stop()
        self.viewport().update()

    def paintEvent(self, event):
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        offset = self.verticalScrollBar().value()
        visible = QRectF(0, offset, self.viewport().width(),
                         self.viewport().height())
        missing = []
        for index, rect in enumerate(self.rects):
            if not rect.intersects(visible.adjusted(0, -400, 0, 400)):
                continue
            shown = rect.translated(0, -offset)
            pixmap = self.pixmap_for(index)
            if pixmap is None:
                missing.append(index)
                painter.fillRect(shown, QColor('#111111'))
            elif not pixmap.isNull():
                painter.drawPixmap(shown.toRect(), pixmap)
            image = self.images[index]
            if image is self.active or id(image) in self.selected:
                painter.setPen(QPen(QColor('#e6e26a'), 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRect(shown.adjusted(-3, -3, 3, 3))
        painter.end()
        if missing:
            self.pending = missing + [i for i in self.pending
                                      if i not in missing]
            if not self.loader.isActive():
                self.loader.start()

    def image_at(self, position: QPoint) -> Image | None:
        point = QPointF(position.x(),
                        position.y() + self.verticalScrollBar().value())
        for index, rect in enumerate(self.rects):
            if rect.contains(point):
                return self.images[index]
        return None

    def mousePressEvent(self, event: QMouseEvent):
        image = self.image_at(event.position().toPoint())
        if image is None:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            is_ctrl = bool(event.modifiers()
                           & Qt.KeyboardModifier.ControlModifier)
            self.image_clicked.emit(image, is_ctrl)

    def contextMenuEvent(self, event):
        image = self.image_at(event.pos())
        if image is not None:
            self.image_menu_requested.emit(image, event.globalPos())



class ConstellationCanvas(QWidget):
    """The tag map. Click a circle to see what goes with it, drag circles or
    the background, and zoom with the wheel."""
    tag_focused = Signal(str)
    picked_changed = Signal()

    VIEW_W = 1000
    VIEW_H = 700

    def __init__(self):
        super().__init__()
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.model = ClusterModel()
        self.nodes: list[Node] = []
        self.picked_tag: str | None = None
        self.zoom = 1.0
        self.pan = QPointF(0, 0)
        self.cursor_world: QPointF | None = None
        self.press = None
        self.drag = None
        self.pan_drag = None
        self.pop_tag: str | None = None
        self.pop_started = 0.0
        self.pop_timer = QTimer(self)
        self.pop_timer.setInterval(16)
        self.pop_timer.timeout.connect(self.update)

    # Geometry ------------------------------------------------------------

    def view_box(self) -> QRectF:
        width = self.VIEW_W / self.zoom
        height = self.VIEW_H / self.zoom
        return QRectF(500 - width / 2 + self.pan.x(),
                      350 - height / 2 + self.pan.y(), width, height)

    def scale_and_origin(self):
        box = self.view_box()
        scale = min(self.width() / box.width(), self.height() / box.height())
        origin_x = (self.width() - box.width() * scale) / 2
        origin_y = (self.height() - box.height() * scale) / 2
        return scale, box, origin_x, origin_y

    def to_device(self, x: float, y: float) -> QPointF:
        scale, box, origin_x, origin_y = self.scale_and_origin()
        return QPointF(origin_x + (x - box.x()) * scale,
                       origin_y + (y - box.y()) * scale)

    def to_world(self, point: QPointF) -> QPointF:
        scale, box, origin_x, origin_y = self.scale_and_origin()
        return QPointF(box.x() + (point.x() - origin_x) / scale,
                       box.y() + (point.y() - origin_y) / scale)

    # Model ---------------------------------------------------------------

    def set_model(self, model: ClusterModel):
        self.model = model
        self.nodes = [Node(**vars(node)) for node in model.nodes]
        if self.picked_tag and not self.find(self.picked_tag):
            self.picked_tag = None
        self.picked_changed.emit()
        self.update()

    def find(self, tag: str | None) -> Node | None:
        if not tag:
            return None
        lowered = tag.lower()
        return next((node for node in self.nodes
                     if node.tag.lower() == lowered), None)

    def picked(self) -> Node | None:
        return self.find(self.picked_tag)

    def shared_with(self) -> dict[str, float]:
        picked = self.picked()
        shared = {}
        if picked:
            for edge in self.model.pairs:
                other = (edge.b if edge.a == picked.tag
                         else edge.a if edge.b == picked.tag else None)
                if other and edge.w > 0:
                    shared[other] = edge.w
        return shared

    def is_kin(self, tag: str) -> bool:
        picked = self.picked()
        return bool(picked) and any(
            (edge.a == picked.tag and edge.b == tag)
            or (edge.b == picked.tag and edge.a == tag)
            for edge in self.model.alike)

    def companions(self) -> list[tuple[Node, float]]:
        if not self.picked():
            return []
        found = []
        for tag, shared in self.shared_with().items():
            node = next((item for item in self.nodes if item.tag == tag),
                        None)
            if node:
                found.append((node, shared))
        found.sort(key=lambda pair: (-int(self.is_kin(pair[0].tag)),
                                     -pair[1], pair[0].tag.casefold()))
        return found

    def focus_tag(self, tag: str):
        if self.picked_tag and self.picked_tag.lower() == tag.lower():
            self.picked_tag = None
        else:
            self.picked_tag = tag
            self.tag_focused.emit(tag)
        self.picked_changed.emit()
        self.update()

    def choose_tag(self, tag: str):
        """Pick a tag from the search box and pan to it."""
        node = self.find(tag)
        if node:
            self.pan = QPointF(node.x - 500, node.y - 350)
        if not (self.picked_tag and self.picked_tag.lower() == tag.lower()):
            self.focus_tag(tag)
        self.update()

    def change_zoom(self, direction: int):
        factor = 1.2 if direction > 0 else 1 / 1.2
        self.zoom = min(5.0, max(0.35, self.zoom * factor))
        self.update()

    # Drawing -------------------------------------------------------------

    def sizes(self):
        link_values = [node.links for node in self.nodes] or [0]
        return min(link_values), max(link_values)

    def drawn(self):
        min_links, max_links = self.sizes()
        picked = self.picked()
        shared = self.shared_with()
        closeness = 1 / self.zoom ** 0.22 if self.zoom > 1 else 1
        items = []
        for node in self.nodes:
            hot = picked is not None and picked.tag == node.tag
            tied = node.tag in shared
            in_group = picked is None or hot or tied
            if picked is None or node.tag == picked.tag:
                count = node.count
            else:
                count = shared.get(node.tag, node.count)
            radius = (link_radius(node.links, min_links, max_links)
                      * closeness / self.zoom)
            label_size = 12 * closeness / self.zoom
            if self.cursor_world is not None:
                dist = math.hypot(self.cursor_world.x() - node.x,
                                  self.cursor_world.y() - node.y)
            else:
                dist = math.inf
            reach = radius * 3.04
            near = 0 if dist >= reach else 1 - dist / reach
            items.append({'node': node, 'hot': hot, 'in_group': in_group,
                          'radius': radius, 'label_size': label_size,
                          'near': near, 'grow': 1 + near * 0.16,
                          'count': count})
        return items

    def pop_scale(self, tag: str) -> float:
        if tag != self.pop_tag:
            return 1
        t = (time.monotonic() - self.pop_started) / 0.32
        if t >= 1:
            self.pop_tag = None
            self.pop_timer.stop()
            return 1
        points = [(0, 1), (0.32, 0.84), (0.68, 1.18), (1, 1)]
        for (t0, s0), (t1, s1) in zip(points, points[1:]):
            if t <= t1:
                return s0 + (s1 - s0) * (t - t0) / (t1 - t0)
        return 1

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor('#000000'))
        if not self.nodes:
            painter.setPen(QColor('#9a9aa3'))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             'No tags yet.')
            return
        scale = self.scale_and_origin()[0]
        picked = self.picked()
        by_tag = {node.tag: node for node in self.nodes}
        # Strongest links inside each group.
        for edge in self.model.edges:
            a, b = by_tag.get(edge.a), by_tag.get(edge.b)
            if not a or not b:
                continue
            if picked and picked.tag in (a.tag, b.tag):
                continue
            color = QColor(a.color)
            color.setAlphaF(0.08 if picked else 0.28)
            painter.setPen(QPen(color, 0.7 * scale))
            painter.drawLine(self.to_device(a.x, a.y),
                             self.to_device(b.x, b.y))
        if picked:
            min_links, max_links = self.sizes()
            fit = 1 / self.zoom ** 0.22 if self.zoom > 1 else 1

            def radius_of(links):
                return (link_radius(links, min_links, max_links) * fit
                        / self.zoom)

            painter.setPen(Qt.PenStyle.NoPen)
            for node, shared in self.companions():
                closeness = shared / max(picked.count, 1)
                brightness = 1 - (1 - closeness) ** 2
                outer = 0.45 + closeness * 5.6
                inner = 0.22 + closeness * 0.4
                dx = node.x - picked.x
                dy = node.y - picked.y
                length = math.hypot(dx, dy) or 1
                ux, uy = dx / length, dy / length
                start = radius_of(picked.links) + 1.2 / self.zoom
                end = radius_of(node.links) + outer * 0.35 + 1.2 / self.zoom
                if length <= start + end + 1:
                    continue
                x1, y1 = picked.x + ux * start, picked.y + uy * start
                x2, y2 = node.x - ux * end, node.y - uy * end
                px, py = -uy, ux
                h1, h2 = inner / 2, outer / 2
                polygon = QPolygonF([
                    self.to_device(x1 + px * h1, y1 + py * h1),
                    self.to_device(x2 + px * h2, y2 + py * h2),
                    self.to_device(x2 - px * h2, y2 - py * h2),
                    self.to_device(x1 - px * h1, y1 - py * h1)])
                color = QColor(node.color)
                color.setAlphaF(min(1.0, 0.14 + brightness * 0.86))
                painter.setBrush(color)
                painter.drawPolygon(polygon)
        # Same word, different spelling: dashed white lines.
        dash_pen = QPen(QColor(255, 255, 255, 230), 1.3 * scale / self.zoom)
        dash_pen.setDashPattern([5 / 1.3, 3 / 1.3])
        painter.setPen(dash_pen)
        for edge in self.model.alike:
            a, b = by_tag.get(edge.a), by_tag.get(edge.b)
            if a and b:
                painter.drawLine(self.to_device(a.x, a.y),
                                 self.to_device(b.x, b.y))
        items = self.drawn()
        for item in items:
            if not item['in_group']:
                self.draw_label(painter, item, scale, faded=True)
        for item in items:
            self.draw_node(painter, item, scale)
        for item in items:
            if item['in_group']:
                self.draw_label(painter, item, scale, faded=False)
        painter.end()

    def draw_node(self, painter: QPainter, item, scale: float):
        node = item['node']
        center = self.to_device(node.x, node.y)
        radius = item['radius'] * item['grow'] * scale * self.pop_scale(
            node.tag)
        color = QColor(node.color)
        painter.setPen(Qt.PenStyle.NoPen)
        if item['near'] > 0.04 and item['in_group']:
            painter.setOpacity(0.22 * item['near'])
            painter.setBrush(color)
            painter.drawEllipse(center, radius * 1.55, radius * 1.55)
        painter.setOpacity(1)
        if item['hot']:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor('#ffffff'), 1.5 * scale / self.zoom))
            ring = radius + 6 * scale / self.zoom
            painter.drawEllipse(center, ring, ring)
            painter.setPen(Qt.PenStyle.NoPen)
        painter.setOpacity(1 if item['in_group'] else 0.12)
        painter.setBrush(color)
        painter.drawEllipse(center, radius, radius)
        count = item['count']
        factor = 0.48 if count >= 100 else 0.58 if count >= 10 else 0.7
        font = QFont(self.font())
        font.setBold(True)
        font.setPixelSize(max(1, round(radius * factor)))
        painter.setFont(font)
        painter.setOpacity(1 if item['in_group'] else 0.35)
        painter.setPen(QColor('#141416'))
        painter.drawText(QRectF(center.x() - radius, center.y() - radius,
                                2 * radius, 2 * radius),
                         Qt.AlignmentFlag.AlignCenter, f'{count:g}')
        painter.setOpacity(1)

    def draw_label(self, painter: QPainter, item, scale: float, faded: bool):
        node = item['node']
        size = item['label_size'] * scale
        if size < 1:
            return
        position = self.to_device(
            node.x + item['radius'] * item['grow'] + 6 / self.zoom,
            node.y + item['label_size'] * 0.3)
        font = QFont(self.font())
        font.setBold(True)
        font.setPixelSize(max(1, round(size)))
        path = QPainterPath()
        path.addText(position, font, node.tag)
        stroke = max(size * (0.16 if faded else 0.28),
                     (1.2 if faded else 2) * scale / self.zoom)
        painter.setOpacity(0.4 if faded else 1)
        painter.strokePath(path, QPen(QColor('#000000'), stroke,
                                      Qt.PenStyle.SolidLine,
                                      Qt.PenCapStyle.RoundCap,
                                      Qt.PenJoinStyle.RoundJoin))
        painter.fillPath(path, QColor(node.color))
        painter.setOpacity(1)

    # Mouse ---------------------------------------------------------------

    def node_at(self, point: QPointF) -> Node | None:
        world = self.to_world(point)
        for item in reversed(self.drawn()):
            node = item['node']
            radius = item['radius'] * item['grow']
            if item['near'] > 0.04 and item['in_group']:
                radius *= 1.55
            if math.hypot(world.x() - node.x, world.y() - node.y) <= radius:
                return node
        return None

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        point = event.position()
        node = self.node_at(point)
        world = self.to_world(point)
        if node:
            self.press = {'tag': node.tag, 'pos': point, 'moved': False}
            self.drag = (node.tag, world.x() - node.x, world.y() - node.y)
        else:
            self.pan_drag = (point, QPointF(self.pan))

    def mouseMoveEvent(self, event: QMouseEvent):
        point = event.position()
        world = self.to_world(point)
        if not (self.drag and self.press and self.press['moved']):
            self.cursor_world = world
        if self.drag and self.press:
            delta = point - self.press['pos']
            if (not self.press['moved']
                    and delta.x() ** 2 + delta.y() ** 2 < 16):
                return
            self.press['moved'] = True
            tag, offset_x, offset_y = self.drag
            for node in self.nodes:
                if node.tag == tag:
                    node.x = world.x() - offset_x
                    node.y = world.y() - offset_y
            self.update()
            return
        if self.pan_drag:
            start, start_pan = self.pan_drag
            scale = self.scale_and_origin()[0]
            self.pan = QPointF(start_pan.x() - (point.x() - start.x()) / scale,
                               start_pan.y() - (point.y() - start.y()) / scale)
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if self.press and not self.press['moved']:
            tag = self.press['tag']
            self.focus_tag(tag)
            self.pop_tag = tag
            self.pop_started = time.monotonic()
            self.pop_timer.start()
        self.press = None
        self.drag = None
        self.pan_drag = None

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if self.node_at(event.position()) is None:
            self.picked_tag = None
            self.picked_changed.emit()
            self.update()

    def leaveEvent(self, event):
        self.cursor_world = None
        self.press = None
        self.drag = None
        self.pan_drag = None
        self.update()

    def wheelEvent(self, event):
        event.accept()
        point = event.position()
        zoom_in = event.angleDelta().y() > 0
        value = self.zoom
        new_zoom = min(5.0, max(0.35, value * (1.12 if zoom_in
                                               else 1 / 1.12)))
        if new_zoom == value:
            return
        # Keep the point under the mouse where it is.
        before = self.to_world(point)
        self.zoom = new_zoom
        after = self.to_world(point)
        self.pan += before - after
        self.update()

    def event(self, event):
        if event.type() == event.Type.ToolTip:
            node = self.node_at(QPointF(event.pos()))
            if node:
                QToolTip.showText(event.globalPos(),
                                  f'{node.tag} \u00b7 {node.links} links',
                                  self)
            else:
                QToolTip.hideText()
            return True
        return super().event(event)


class ConstellationView(QWidget):
    """The canvas with its search box, zoom buttons and the list of tags
    that share pictures with the picked one."""
    tag_focused = Signal(str)

    def __init__(self):
        super().__init__()
        self.canvas = ConstellationCanvas()
        self.canvas.tag_focused.connect(self.tag_focused)
        self.canvas.picked_changed.connect(self.update_panel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)
        overlay_style = (
            'background: rgba(0, 0, 0, 210); color: #f4f4f6; '
            'border: 1px solid rgba(255, 255, 255, 70); border-radius: 8px; '
            'font-size: 15px;')
        # Search box, top left.
        self.search = QLineEdit(self.canvas)
        self.search.setPlaceholderText('Search Tags')
        self.search.setStyleSheet(overlay_style + 'padding: 6px 8px;')
        self.search.textEdited.connect(self.update_suggestions)
        self.search.returnPressed.connect(self.choose_first)
        self.suggestions = QListWidget(self.canvas)
        self.suggestions.setStyleSheet(
            'background: rgba(8, 8, 10, 245); border: 1px solid '
            'rgba(255, 255, 255, 70); border-radius: 8px;')
        self.suggestions.itemClicked.connect(
            lambda item: self.choose(item.text()))
        self.suggestions.hide()
        # Zoom buttons, top right.
        self.zoom_in_button = QToolButton(self.canvas)
        self.zoom_in_button.setText('+')
        self.zoom_out_button = QToolButton(self.canvas)
        self.zoom_out_button.setText('\u2212')
        for button, direction in ((self.zoom_in_button, 1),
                                  (self.zoom_out_button, -1)):
            button.setFixedSize(36, 36)
            font = button.font()
            font.setPointSize(16)
            button.setFont(font)
            button.clicked.connect(
                lambda _=False, d=direction: self.canvas.change_zoom(d))
        # What goes with the picked tag, bottom left.
        self.panel = QFrame(self.canvas)
        self.panel.setObjectName('clusterPanel')
        self.panel.setStyleSheet(
            '#clusterPanel { background: rgba(0, 0, 0, 210); border: 1px '
            'solid rgba(255, 255, 255, 56); border-radius: 10px; }'
            '#clusterPanel QLabel { color: #f4f4f6; font-size: 13px; }'
            '#clusterPanel QTreeWidget { background: transparent; '
            'border: 0; color: #f4f4f6; font-size: 13px; }')
        panel_layout = QVBoxLayout(self.panel)
        panel_layout.setContentsMargins(12, 10, 12, 10)
        title_layout = QHBoxLayout()
        self.panel_title = QLabel()
        self.panel_count = QLabel()
        self.panel_count.setStyleSheet('color: #9a9aa3;')
        title_layout.addWidget(self.panel_title, stretch=1)
        title_layout.addWidget(self.panel_count)
        panel_layout.addLayout(title_layout)
        self.panel_list = QTreeWidget()
        self.panel_list.setHeaderHidden(True)
        self.panel_list.setColumnCount(2)
        self.panel_list.setRootIsDecorated(False)
        self.panel_list.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.panel_list.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        header = self.panel_list.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, header.ResizeMode.Stretch)
        header.setSectionResizeMode(1, header.ResizeMode.ResizeToContents)
        self.panel_list.itemClicked.connect(
            lambda item: self.canvas.focus_tag(item.data(0,
                                               Qt.ItemDataRole.UserRole)))
        panel_layout.addWidget(self.panel_list)
        self.panel_alone = QLabel(
            'No other tag shares a picture with this one.')
        self.panel_alone.setStyleSheet('color: #9a9aa3;')
        self.panel_alone.setWordWrap(True)
        panel_layout.addWidget(self.panel_alone)
        self.panel.hide()

    def set_model(self, model: ClusterModel):
        self.canvas.set_model(model)
        self.update_suggestions()

    def matches(self) -> list[Node]:
        query = self.search.text().strip().lower()
        if not query:
            return []
        nodes = [node for node in self.canvas.nodes
                 if query in node.tag.lower()]
        nodes.sort(key=lambda node: (-int(node.tag.lower().startswith(query)),
                                     -node.links, node.tag.casefold()))
        return nodes[:8]

    def update_suggestions(self):
        self.suggestions.clear()
        picked = self.canvas.picked()
        query = self.search.text().strip().lower()
        matches = self.matches()
        if not matches or (picked and picked.tag.lower() == query):
            self.suggestions.hide()
            return
        for node in matches:
            item = QListWidgetItem(node.tag)
            item.setForeground(QColor(node.color))
            self.suggestions.addItem(item)
        row_height = self.suggestions.sizeHintForRow(0) + 2
        self.suggestions.setFixedHeight(row_height * len(matches) + 6)
        self.suggestions.show()
        self.suggestions.raise_()

    def choose(self, tag: str):
        self.search.setText(tag)
        self.canvas.choose_tag(tag)
        self.update_suggestions()

    def choose_first(self):
        matches = self.matches()
        if matches:
            self.choose(matches[0].tag)

    def update_panel(self):
        picked = self.canvas.picked()
        if not picked:
            self.panel.hide()
            return
        self.panel_title.setText(
            f'<b style="color: {picked.color}; font-size: 15px;">'
            f'{html.escape(picked.tag)}</b>')
        self.panel_count.setText(str(picked.count))
        self.panel_list.clear()
        companions = self.canvas.companions()
        for node, shared in companions:
            label = node.tag + (' \u00b7 same' if self.canvas.is_kin(node.tag)
                                else '')
            item = QTreeWidgetItem([label, f'{shared:g}'])
            item.setData(0, Qt.ItemDataRole.UserRole, node.tag)
            item.setForeground(0, QColor(node.color))
            font = QFont(self.panel_list.font())
            font.setBold(True)
            item.setFont(0, font)
            item.setForeground(1, QColor('#9a9aa3'))
            item.setTextAlignment(1, Qt.AlignmentFlag.AlignRight)
            self.panel_list.addTopLevelItem(item)
        self.panel_list.setVisible(bool(companions))
        self.panel_alone.setVisible(not companions)
        self.panel.show()
        self.place_overlays()
        self.panel.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.place_overlays()

    def place_overlays(self):
        width, height = self.width(), self.height()
        search_width = min(280, int(width * 0.46))
        self.search.setGeometry(12, 12, search_width, 34)
        self.suggestions.setGeometry(12, 50, search_width,
                                     self.suggestions.height())
        self.zoom_in_button.move(width - 12 - 36 - 6 - 36, 12)
        self.zoom_out_button.move(width - 12 - 36, 12)
        panel_width = min(260, int(width * 0.36))
        row_height = max(18, self.panel_list.sizeHintForRow(0))
        panel_height = min(int(height * 0.46), 56 + row_height * max(
            1, self.panel_list.topLevelItemCount()))
        self.panel.setGeometry(12, height - 12 - panel_height, panel_width,
                               panel_height)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self.canvas.picked_tag:
            self.canvas.picked_tag = None
            self.canvas.picked_changed.emit()
            self.canvas.update()
            return
        super().keyPressEvent(event)

