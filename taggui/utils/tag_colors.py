"""Tag color categories: right-click a tag to give it a color, shown as a
bar next to the tag in the Image Tags and All Tags lists. Colors are saved
in the settings and apply in every folder."""
import json

from PySide6.QtCore import QObject, QRect, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QColorDialog, QMenu, QWidget

from utils.settings import get_settings

SETTINGS_KEY = 'tag_colors'
SWATCHES = ['#c026ff', '#ff4d6d', '#ff8a1e', '#ffe14a', '#2ee6c7',
            '#3aa0ff', '#39e35a']
SWATCH_NAMES = dict(zip(SWATCHES, ['Purple', 'Pink', 'Orange', 'Yellow',
                                   'Teal', 'Blue', 'Green']))


class TagColors(QObject):
    changed = Signal()

    def __init__(self, settings=None):
        super().__init__()
        self.settings = settings or get_settings()
        self.colors: dict[str, str] = {}
        self._icons: dict[str, QIcon] = {}
        self.load()

    def load(self):
        raw = self.settings.value(SETTINGS_KEY, '', type=str)
        try:
            data = json.loads(raw) if raw else {}
        except ValueError:
            data = {}
        self.colors = {str(tag).lower(): str(color)
                       for tag, color in data.items()
                       if QColor(str(color)).isValid()}

    def save(self):
        self.settings.setValue(SETTINGS_KEY, json.dumps(self.colors))

    def color_for(self, tag: str) -> str | None:
        if not tag:
            return None
        return self.colors.get(tag.lower())

    def set_color(self, tags: list[str], color: str | None):
        for tag in tags:
            if color:
                self.colors[tag.lower()] = QColor(color).name()
            else:
                self.colors.pop(tag.lower(), None)
        self.save()
        self.changed.emit()

    def rename(self, old_tags: list[str], new_tag: str):
        """Keep the color when a tag is renamed."""
        color = next((self.colors[tag.lower()] for tag in old_tags
                      if tag.lower() in self.colors), None)
        if color and new_tag.lower() not in self.colors:
            self.colors[new_tag.lower()] = color
            self.save()
            self.changed.emit()

    def used_colors(self) -> list[str]:
        extra = [color for color in dict.fromkeys(self.colors.values())
                 if color.lower() not in SWATCHES]
        return SWATCHES + extra

    def icon_for(self, tag: str, height: int = 16) -> QIcon | None:
        """A colored bar used as the item's decoration."""
        color = self.color_for(tag)
        if not color:
            return None
        key = f'{color}-{height}'
        if key not in self._icons:
            pixmap = QPixmap(6, height)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(QRect(0, 0, 5, height), 2, 2)
            painter.end()
            self._icons[key] = QIcon(pixmap)
        return self._icons[key]


def swatch_icon(color: str, size: int = 14) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(color))
    return QIcon(pixmap)


def add_color_menu(menu: QMenu, parent: QWidget, tag_colors: 'TagColors',
                   tags: list[str]):
    """Add a "Category Color" submenu for the tags to a context menu."""
    title = 'Category Color' if len(tags) == 1 else (
        f'Category Color ({len(tags)} Tags)')
    color_menu = menu.addMenu(title)
    current = tag_colors.color_for(tags[0]) if tags else None
    color_menu.addAction('No Color',
                         lambda: tag_colors.set_color(tags, None))
    color_menu.addSeparator()
    for color in tag_colors.used_colors():
        action = color_menu.addAction(swatch_icon(color),
                                      SWATCH_NAMES.get(color, color),
                                      lambda c=color: tag_colors.set_color(
                                          tags, c))
        action.setCheckable(True)
        action.setChecked(bool(current) and current.lower() == color.lower())

    def pick_custom():
        color = QColorDialog.getColor(QColor(current or SWATCHES[0]), parent,
                                      'Tag Color')
        if color.isValid():
            tag_colors.set_color(tags, color.name())

    color_menu.addAction('Custom Color...', pick_custom)
    return color_menu


# One shared instance for the whole app.
_tag_colors: TagColors | None = None


def get_tag_colors() -> TagColors:
    global _tag_colors
    if _tag_colors is None:
        _tag_colors = TagColors()
    return _tag_colors
