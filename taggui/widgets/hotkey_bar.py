"""A strip in the status bar that shows the keyboard shortcuts for the part
of the window you are working in (ported from TagBench's hotkey footer)."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QWidget

HOTKEYS = {
    'start': ('Start', [('Ctrl+L', 'load a folder')]),
    'filter': ('Filter', [('Alt+F', 'focus'), ('Enter', 'add tag bubble'),
                          ('-tag', 'hide tag'), ('click bubble', 'flip')]),
    'list': ('Images', [('\u2191 \u2193', 'move'), ('Ctrl click', 'more'),
                        ('Shift click', 'range'), ('Ctrl+K', 'complete'),
                        ('Ctrl+J', 'next untagged')]),
    'add': ('Add tag', [('Alt+A', 'focus'), ('Enter', 'add'),
                        ('Ctrl+Enter', 'first suggestion')]),
    'tags': ('Image tags', [('click', 'select'), ('Ctrl click', 'more'),
                            ('Del', 'remove'), ('double click', 'rename'),
                            ('right click', 'filter / color')]),
    'nl': ('Natural language', [('type', 'under the tags'),
                                ('click away', 'saves it')]),
    'search': ('Search tags', [('Alt+S', 'focus'), ('type', 'to search')]),
    'all': ('All tags', [('click', 'filter'), ('right click',
                                               'and / not / or, color'),
                         ('Del', 'delete everywhere'),
                         ('double click', 'rename')]),
    'auto': ('Auto-Captioner', [('Alt+C', 'focus start'),
                                ('Load Prompt Preset', 'Tag2Caption')]),
    'view': ('Picture', [('C', 'crop'), ('J', 'remove brush'),
                         ('Ctrl+Z', 'undo'), ('Ctrl+Y', 'redo'),
                         ('Ctrl+\u2191 \u2193', 'previous / next')]),
    'crop': ('Crop', [('drag', 'the edges'), ('Enter', 'apply'),
                      ('Esc', 'cancel')]),
    'remove': ('Remove', [('paint', 'what goes'), ('right drag', 'erase'),
                          ('[ ]', 'brush size'), ('Enter', 'apply'),
                          ('Esc', 'cancel')]),
}


class HotkeyBar(QWidget):
    def __init__(self):
        super().__init__()
        self.zone = None
        # Never make the window wider; extra hints are simply cut off.
        self.setSizePolicy(QSizePolicy.Policy.Ignored,
                           QSizePolicy.Policy.Preferred)
        self.layout_ = QHBoxLayout(self)
        self.layout_.setContentsMargins(4, 0, 4, 0)
        self.layout_.setSpacing(10)
        font = self.font()
        font.setPointSizeF(max(8.0, font.pointSizeF() * 0.8))
        self.setFont(font)
        self.set_zone('start')

    def set_zone(self, zone: str):
        if zone == self.zone or zone not in HOTKEYS:
            return
        self.zone = zone
        while self.layout_.count():
            item = self.layout_.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        title, keys = HOTKEYS[zone]
        title_label = QLabel(f'<b>{title}</b>')
        title_label.setFont(self.font())
        self.layout_.addWidget(title_label)
        for key, action in keys:
            label = QLabel(
                f'<span style="border: 1px solid palette(mid); '
                f'border-radius: 3px; padding: 0 3px;">'
                f'<code>&nbsp;{key}&nbsp;</code></span> {action}')
            label.setTextFormat(Qt.TextFormat.RichText)
            label.setFont(self.font())
            self.layout_.addWidget(label)
        self.layout_.addStretch()
