"""Tag color categories: right-click a tag to give it a color. Every tag is
also tinted with the color of its group from the Constellation view
(TagBench's groupColors), shown as a bar and as the text color in the Image
Tags and All Tags lists. Chosen colors are saved in the settings and apply in
every folder; a chosen color wins over the group color."""
import json

from PySide6.QtCore import QObject, QRect, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QColorDialog, QMenu, QWidget

from utils.settings import get_settings

SETTINGS_KEY = 'tag_colors'
SWATCHES = ['#c026ff', '#ff4d6d', '#ff8a1e', '#ffe14a', '#2ee6c7',
            '#3aa0ff', '#39e35a']



class TagColors(QObject):
    changed = Signal()

    def __init__(self, settings=None):
        super().__init__()
        self.settings = settings or get_settings()
        self.colors: dict[str, str] = {}
        self._icons: dict[str, QIcon] = {}
        # Group colors of the loaded folder, by lowercase tag.
        self.group_tints: dict[str, str] = {}
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

    def tint_for(self, tag: str) -> str | None:
        if not tag:
            return None
        return self.color_for(tag) or self.group_tints.get(tag.lower())

    def set_group_tints(self, tints: dict[str, str]):
        if tints != self.group_tints:
            self.group_tints = tints
            self.changed.emit()

    def text_color_for(self, tag: str, is_dark_background: bool
                       ) -> QColor | None:
        """The tint as a text color, darkened on light backgrounds so it
        stays readable."""
        tint = self.tint_for(tag)
        if not tint:
            return None
        color = QColor(tint)
        if not is_dark_background:
            hue, saturation, lightness, _ = color.getHslF()
            color = QColor.fromHslF(max(hue, 0), saturation,
                                    min(lightness, 0.36))
        return color

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
        color = self.tint_for(tag)
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


def is_dark_background() -> bool:
    app = QApplication.instance()
    if app is None:
        return False
    return app.palette().base().color().lightness() < 128


def swatch_icon(color: str, size: int = 14) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(color))
    return QIcon(pixmap)


def add_color_menu(menu: QMenu, parent: QWidget, tag_colors: 'TagColors',
                   tags: list[str]):
    """Add a "Category" color submenu for the tags to a context menu."""
    title = 'Category' if len(tags) == 1 else f'Category ({len(tags)} Tags)'
    color_menu = menu.addMenu(title)
    current = tag_colors.color_for(tags[0]) if tags else None
    color_menu.addAction('No color',
                         lambda: tag_colors.set_color(tags, None))
    color_menu.addSeparator()
    for color in tag_colors.used_colors():
        action = color_menu.addAction(swatch_icon(color), color,
                                      lambda c=color: tag_colors.set_color(
                                          tags, c))
        action.setCheckable(True)
        action.setChecked(bool(current) and current.lower() == color.lower())

    def pick_custom():
        color = QColorDialog.getColor(QColor(current or SWATCHES[0]), parent,
                                      'Tag Color')
        if color.isValid():
            tag_colors.set_color(tags, color.name())

    color_menu.addAction('Custom color...', pick_custom)
    return color_menu


# One shared instance for the whole app.
_tag_colors: TagColors | None = None


def get_tag_colors() -> TagColors:
    global _tag_colors
    if _tag_colors is None:
        _tag_colors = TagColors()
    return _tag_colors
