"""Filter bubbles at the top of the image list.

Green bubbles keep images that have the tag, red bubbles hide them. Click a
bubble to flip it between include and exclude; click its x to remove it.
Type a tag into the "+ tag" box (start it with - to exclude). The bubbles
read and write the image list filter text, which is still available behind
the "Text" button for advanced filters.
"""
from PySide6.QtCore import QStringListModel, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (QCompleter, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QSizePolicy, QToolButton,
                               QVBoxLayout, QWidget)

from utils.filter_chips import (EXCLUDE, INCLUDE, UNTAGGED_CLAUSE, Chip,
                                add_chip, clause_to_chip, parse_chip_input,
                                remove_chip, text_to_chips, toggle_chip)
from utils.flow_layout import FlowLayout

CHIP_COLORS = {
    INCLUDE: ('#2e7d32', '#ffffff', '#43a047'),
    EXCLUDE: ('#c62828', '#ffffff', '#e53935'),
    'other': ('#455a64', '#ffffff', '#607d8b'),
}
# Bubbles show the whole tag; only very long text is shortened (the full
# text is in the tooltip).
MAX_CHIP_TEXT_WIDTH = 360


class FilterChip(QFrame):
    toggled = Signal()
    removed = Signal()

    def __init__(self, chip: Chip):
        super().__init__()
        self.chip = chip
        background, foreground, hover = CHIP_COLORS.get(
            chip.kind, CHIP_COLORS['other'])
        self.setObjectName('filterChip')
        self.setStyleSheet(
            f'#filterChip {{ background: {background}; border-radius: 11px; }}'
            f'#filterChip:hover {{ background: {hover}; }}'
            f'QLabel {{ color: {foreground}; background: transparent; }}'
            f'QToolButton {{ color: {foreground}; border: none; '
            f'background: transparent; font-weight: bold; padding: 0 2px; }}'
            f'QToolButton:hover {{ background: rgba(0, 0, 0, 60); '
            f'border-radius: 9px; }}')
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 3, 4, 3)
        layout.setSpacing(4)
        prefix = {INCLUDE: '+ ', EXCLUDE: '\u2212 '}.get(chip.kind, '')
        text = prefix + chip.label
        self.label = QLabel()
        font = self.label.font()
        font.setPointSizeF(max(8.0, font.pointSizeF() * 0.85))
        self.label.setFont(font)
        metrics = QFontMetrics(font)
        shown = metrics.elidedText(text, Qt.TextElideMode.ElideRight,
                                   MAX_CHIP_TEXT_WIDTH)
        self.label.setText(shown)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.label)
        close_button = QToolButton()
        close_button.setText('\u00d7')
        close_button.setFont(font)
        close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        close_button.setToolTip('Remove this filter')
        close_button.clicked.connect(self.removed.emit)
        layout.addWidget(close_button)
        if chip.kind in (INCLUDE, EXCLUDE):
            what = ('Showing images with' if chip.kind == INCLUDE
                    else 'Hiding images with')
            self.setToolTip(f'{what} "{chip.label}".\nClick to switch '
                            f'between include and exclude.')
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        else:
            self.setToolTip(chip.clause)

    def mouseReleaseEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton
                and self.chip.kind in (INCLUDE, EXCLUDE)
                and self.rect().contains(event.position().toPoint())):
            self.toggled.emit()
        super().mouseReleaseEvent(event)


class FilterChipBar(QWidget):
    """Shows the filter as bubbles and edits the filter line edit."""
    # Emitted with the new filter text.
    filter_text_changed = Signal(str)

    def __init__(self, filter_line_edit: QLineEdit):
        super().__init__()
        self.filter_line_edit = filter_line_edit
        self.chips_container = QWidget()
        self.flow = FlowLayout(self.chips_container, spacing=6)
        self.tag_input = QLineEdit()
        self.tag_input.setPlaceholderText('+ tag  (-tag hides)')
        self.tag_input.setToolTip(
            'Type a tag and press Enter to show only images with it.\n'
            'Start with - to hide images with the tag.\n'
            'Filter expressions such as name:cat or tags:<5 also work.')
        self.tag_input.setMinimumWidth(150)
        self.tag_input.setSizePolicy(QSizePolicy.Policy.Expanding,
                                     QSizePolicy.Policy.Fixed)
        self.tag_input.setStyleSheet('padding: 4px 6px;')
        self.completer_model = QStringListModel()
        self.completer = QCompleter(self.completer_model, self)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchFlag.MatchContains)
        # The completer is driven by hand so that a leading - or + is not
        # part of what it matches.
        self.completer.setWidget(self.tag_input)
        self.completer.activated.connect(self.add_from_completer)
        self.tag_input.textEdited.connect(self.update_completer)
        self.tag_input.returnPressed.connect(self.add_from_input)

        self.untagged_button = QToolButton()
        self.untagged_button.setText('Untagged')
        self.untagged_button.setCheckable(True)
        self.untagged_button.setToolTip('Show only images without tags')
        self.untagged_button.toggled.connect(self.set_untagged_only)
        self.clear_button = QToolButton()
        self.clear_button.setText('Clear')
        self.clear_button.setToolTip('Remove every filter')
        self.clear_button.clicked.connect(self.filter_line_edit.clear)
        self.text_button = QToolButton()
        self.text_button.setText('Text')
        self.text_button.setCheckable(True)
        self.text_button.setToolTip(
            'Show the filter as text, for AND / OR / NOT and other '
            'advanced filters')
        self.text_button.toggled.connect(self.filter_line_edit.setVisible)

        for button in (self.untagged_button, self.clear_button,
                       self.text_button):
            button.setAutoRaise(True)
            font = button.font()
            font.setPointSizeF(max(8.0, font.pointSizeF() * 0.85))
            button.setFont(font)
        buttons_layout = QHBoxLayout()
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(2)
        buttons_layout.addWidget(self.untagged_button)
        buttons_layout.addWidget(self.clear_button)
        buttons_layout.addStretch()
        buttons_layout.addWidget(self.text_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        # The bubbles and the "+ tag" box share one wrapping row; the box
        # fills whatever room is left.
        layout.addWidget(self.chips_container)
        layout.addLayout(buttons_layout)

        self.filter_line_edit.setVisible(False)
        self.filter_line_edit.textChanged.connect(self.rebuild)
        self.rebuild()

    def set_tags(self, tags: list[str]):
        """Tags offered by the "+ tag" box's autocomplete."""
        self.completer_model.setStringList(tags)

    def text(self) -> str:
        return self.filter_line_edit.text()

    def set_text(self, text: str):
        if text != self.filter_line_edit.text():
            self.filter_line_edit.setText(text)

    @Slot()
    def rebuild(self):
        while self.flow.count():
            item = self.flow.takeAt(0)
            widget = item.widget()
            if widget is not None and widget is not self.tag_input:
                widget.hide()
                widget.deleteLater()
        chips = text_to_chips(self.text())
        for index, chip in enumerate(chips):
            chip_widget = FilterChip(chip)
            chip_widget.removed.connect(
                lambda index_=index: self.set_text(
                    remove_chip(self.text(), index_)))
            chip_widget.toggled.connect(
                lambda index_=index: self.set_text(
                    toggle_chip(self.text(), index_)))
            self.flow.addWidget(chip_widget)
        self.flow.addWidget(self.tag_input)
        has_untagged = any(chip.clause == UNTAGGED_CLAUSE for chip in chips)
        self.untagged_button.blockSignals(True)
        self.untagged_button.setChecked(has_untagged)
        self.untagged_button.blockSignals(False)
        self.clear_button.setEnabled(bool(chips))
        self.chips_container.updateGeometry()
        self.updateGeometry()

    @Slot(str)
    def update_completer(self, text: str):
        prefix = text.strip().lstrip('+-').strip()
        if not prefix or ':' in prefix:
            self.completer.popup().hide()
            return
        self.completer.setCompletionPrefix(prefix)
        self.completer.complete()

    @Slot()
    def add_from_input(self):
        # The completer's popup handles Enter itself when it is open.
        if self.completer.popup().isVisible():
            return
        self.add_text(self.tag_input.text())

    @Slot(str)
    def add_from_completer(self, text: str):
        prefix = '-' if self.tag_input.text().lstrip().startswith('-') else ''
        self.add_text(prefix + text)

    def add_text(self, text: str):
        chip = parse_chip_input(text)
        QTimer.singleShot(0, self.tag_input.clear)
        if chip is None:
            return
        self.set_text(add_chip(self.text(), chip))

    @Slot(bool)
    def set_untagged_only(self, is_checked: bool):
        chips = text_to_chips(self.text())
        if is_checked:
            self.set_text(add_chip(self.text(),
                                   clause_to_chip(UNTAGGED_CLAUSE)))
        else:
            index = next((i for i, chip in enumerate(chips)
                          if chip.clause == UNTAGGED_CLAUSE), None)
            if index is not None:
                self.set_text(remove_chip(self.text(), index))
