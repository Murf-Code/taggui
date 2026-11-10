"""A layout that places widgets left to right and wraps to a new row."""
from PySide6.QtCore import QMargins, QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QLayout, QLayoutItem, QSizePolicy


class FlowLayout(QLayout):
    def __init__(self, parent=None, spacing: int = 6):
        super().__init__(parent)
        self._items: list[QLayoutItem] = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item: QLayoutItem):
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        margins: QMargins = self.contentsMargins()
        size += QSize(margins.left() + margins.right(),
                      margins.top() + margins.bottom())
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        margins = self.contentsMargins()
        effective = rect.adjusted(margins.left(), margins.top(),
                                  -margins.right(), -margins.bottom())
        x = effective.x()
        y = effective.y()
        line_height = 0
        for item in self._items:
            if item.widget() is not None and item.widget().isHidden():
                continue
            hint = item.sizeHint().expandedTo(item.minimumSize())
            width = min(hint.width(), effective.width())
            stretch = (item.widget() is not None
                       and item.widget().sizePolicy().horizontalPolicy()
                       == QSizePolicy.Policy.Expanding)
            next_x = x + width + self._spacing
            if x > effective.x() and next_x - self._spacing > effective.right() + 1:
                x = effective.x()
                y += line_height + self._spacing
                next_x = x + width + self._spacing
                line_height = 0
            if stretch:
                # Fill the rest of the row (used by the "+ tag" input).
                width = max(width, effective.right() + 1 - x)
                next_x = x + width + self._spacing
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), QSize(width,
                                                           hint.height())))
            x = next_x
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y() + margins.bottom()
