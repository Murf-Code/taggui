from PySide6.QtCore import (QItemSelectionModel, QModelIndex, QStringListModel,
                            QTimer, Qt, Signal, Slot)
from PySide6.QtGui import QKeyEvent, QPalette
from PySide6.QtWidgets import (QAbstractItemView, QCompleter, QDockWidget,
                               QHBoxLayout, QLabel, QLineEdit, QListView,
                               QMessageBox, QPlainTextEdit, QPushButton,
                               QVBoxLayout, QWidget)
from transformers import PreTrainedTokenizerBase

from models.proxy_image_list_model import ProxyImageListModel
from models.tag_counter_model import TagCounterModel
from utils.image import Image
from utils.filter_text import build_tag_filter_menu
from utils.caption_file import separator_uses_newline
from utils.settings import DEFAULT_SETTINGS, get_settings
from utils.tag_colors import add_color_menu, get_tag_colors
from utils.text_edit_item_delegate import TextEditItemDelegate
from utils.utils import get_confirmation_dialog_reply
from widgets.image_list import ImageList

MAX_TOKEN_COUNT = 75


class TagInputBox(QLineEdit):
    tags_addition_requested = Signal(list, list)

    def __init__(self, image_tag_list_model: QStringListModel,
                 tag_counter_model: TagCounterModel, image_list: ImageList,
                 tag_separator: str):
        super().__init__()
        self.image_tag_list_model = image_tag_list_model
        self.image_list = image_list
        self.tag_separator = tag_separator

        self.setPlaceholderText('Add Tag')
        self.setStyleSheet('padding: 8px;')
        settings = get_settings()
        autocomplete_tags = settings.value(
            'autocomplete_tags',
            defaultValue=DEFAULT_SETTINGS['autocomplete_tags'], type=bool)
        if autocomplete_tags:
            self.completer = QCompleter(tag_counter_model)
            self.setCompleter(self.completer)
            self.completer.activated.connect(lambda text: self.add_tag(text))
            # Clear the input box after the completer inserts the tag into it.
            self.completer.activated.connect(
                lambda: QTimer.singleShot(0, self.clear))
        else:
            self.completer = None

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() not in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            super().keyPressEvent(event)
            return
        # If Ctrl+Enter is pressed and the completer is visible, add the first
        # tag in the completer popup.
        if (event.modifiers() == Qt.KeyboardModifier.ControlModifier
                and self.completer is not None
                and self.completer.popup().isVisible()):
            first_tag = self.completer.popup().model().data(
                self.completer.model().index(0, 0), Qt.ItemDataRole.EditRole)
            self.add_tag(first_tag)
        # Otherwise, add the tag in the input box.
        else:
            self.add_tag(self.text())
        self.clear()
        if self.completer is not None:
            self.completer.popup().hide()

    def add_tag(self, tag: str):
        if not tag:
            return
        tags = tag.split(self.tag_separator)
        selected_image_indices = self.image_list.get_selected_image_indices()
        selected_image_count = len(selected_image_indices)
        if len(tags) == 1 and selected_image_count == 1:
            # Add an empty tag and set it to the new tag.
            self.image_tag_list_model.insertRow(
                self.image_tag_list_model.rowCount())
            new_tag_index = self.image_tag_list_model.index(
                self.image_tag_list_model.rowCount() - 1)
            self.image_tag_list_model.setData(new_tag_index, tag)
            return
        if selected_image_count > 1:
            if len(tags) > 1:
                question = (f'Add tags to {selected_image_count} selected '
                            f'images?')
            else:
                question = (f'Add tag "{tags[0]}" to {selected_image_count} '
                            f'selected images?')
            reply = get_confirmation_dialog_reply(title='Add Tag',
                                                  question=question)
            if reply != QMessageBox.StandardButton.Yes:
                return
        self.tags_addition_requested.emit(tags, selected_image_indices)


class ImageTagsList(QListView):
    # The tag and the mode (`and`, `not` or `or`).
    image_list_filter_extension_requested = Signal(str, str)
    # Tags to remove from every selected image (multi-image selection).
    multi_image_tags_removal_requested = Signal(list)

    def __init__(self, image_tag_list_model: QStringListModel):
        super().__init__()
        self.image_tag_list_model = image_tag_list_model
        # Set by the main window; returns the number of selected images.
        self.selected_image_count_getter = None
        self.setModel(self.image_tag_list_model)
        self.setItemDelegate(TextEditItemDelegate(self))
        self.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setWordWrap(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)

    def contextMenuEvent(self, event):
        index = self.indexAt(event.pos())
        if not index.isValid():
            return
        tag = index.data(Qt.ItemDataRole.EditRole)
        menu = build_tag_filter_menu(
            self, tag, self.image_list_filter_extension_requested.emit)
        if self.get_selected_image_count() > 1:
            selected_tags = [selected_index.data(Qt.ItemDataRole.EditRole)
                             for selected_index in self.selectedIndexes()]
            tags = selected_tags if tag in selected_tags else [tag]
            menu.addSeparator()
            remove_action = menu.addAction(
                f'Remove from {self.get_selected_image_count()} '
                f'Selected Images')
            remove_action.triggered.connect(
                lambda: self.multi_image_tags_removal_requested.emit(tags))
        selected_tags = [selected_index.data(Qt.ItemDataRole.EditRole)
                         for selected_index in self.selectedIndexes()]
        color_tags = selected_tags if tag in selected_tags else [tag]
        menu.addSeparator()
        add_color_menu(menu, self, get_tag_colors(), color_tags)
        menu.exec(event.globalPos())

    def get_selected_image_count(self) -> int:
        if self.selected_image_count_getter is None:
            return 1
        return self.selected_image_count_getter()

    def keyPressEvent(self, event: QKeyEvent):
        """
        Delete selected tags when the delete key or backspace key is pressed.
        """
        if event.key() not in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            super().keyPressEvent(event)
            return
        rows_to_remove = [index.row() for index in self.selectedIndexes()]
        if not rows_to_remove:
            return
        if self.get_selected_image_count() > 1:
            # Remove the tags from all selected images that have them.
            tag_list = self.image_tag_list_model.stringList()
            tags = list(dict.fromkeys(tag_list[row] for row in rows_to_remove))
            self.multi_image_tags_removal_requested.emit(tags)
            return
        remaining_tags = [tag for i, tag
                          in enumerate(self.image_tag_list_model.stringList())
                          if i not in rows_to_remove]
        self.image_tag_list_model.setStringList(remaining_tags)
        min_removed_row = min(rows_to_remove)
        remaining_row_count = self.image_tag_list_model.rowCount()
        if min_removed_row < remaining_row_count:
            self.select_tag(min_removed_row)
        elif remaining_row_count:
            # Select the last tag.
            self.select_tag(remaining_row_count - 1)

    def select_tag(self, row: int):
        # If the current index is not set, using the arrow keys to navigate
        # through the tags after selecting the tag will not work.
        self.setCurrentIndex(self.image_tag_list_model.index(row))
        self.selectionModel().select(
            self.image_tag_list_model.index(row),
            QItemSelectionModel.SelectionFlag.ClearAndSelect)


class NaturalLanguageEdit(QPlainTextEdit):
    """The free-form caption under the tags. Saved when it loses focus."""
    editing_finished = Signal()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.editing_finished.emit()


class ImageTagsEditor(QDockWidget):
    # The image and its new natural-language caption.
    nl_edit_requested = Signal(object, str)

    def __init__(self, proxy_image_list_model: ProxyImageListModel,
                 tag_counter_model: TagCounterModel,
                 image_tag_list_model: QStringListModel, image_list: ImageList,
                 tokenizer: PreTrainedTokenizerBase, tag_separator: str):
        super().__init__()
        self.proxy_image_list_model = proxy_image_list_model
        self.image_tag_list_model = image_tag_list_model
        self.tokenizer = tokenizer
        self.tag_separator = tag_separator
        self.image_index = None

        # Each `QDockWidget` needs a unique object name for saving its state.
        self.setObjectName('image_tags_editor')
        self.setWindowTitle('Image Tags')
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea
                             | Qt.DockWidgetArea.RightDockWidgetArea)
        self.tag_input_box = TagInputBox(self.image_tag_list_model,
                                         tag_counter_model, image_list,
                                         tag_separator)
        self.image_tags_list = ImageTagsList(self.image_tag_list_model)
        self.token_count_label = QLabel()
        # TagBench's Image Tags pane (src/App.tsx): a lock note on completed
        # images and a Natural language button that swaps the tag list for a
        # freeform caption.
        self.lock_label = QLabel(
            'Tags are locked. Mark the image incomplete to edit them.')
        self.lock_label.setWordWrap(True)
        self.lock_label.setStyleSheet('font-size: 13px;')
        self.lock_label.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        self.lock_label.hide()
        self.is_locked = False
        self.nl_toggle_button = QPushButton('Natural language')
        self.nl_toggle_button.setCheckable(True)
        self.nl_text_edit = NaturalLanguageEdit()
        self.nl_text_edit.setPlaceholderText(
            'Freeform caption. Saved under the tags, after the first line '
            'break.')
        self.nl_text_edit.setTabChangesFocus(True)
        self.nl_image: Image | None = None
        self.nl_toggle_button.toggled.connect(self.update_nl_visibility)
        self.nl_text_edit.editing_finished.connect(self.commit_nl)
        self.is_nl_unavailable = separator_uses_newline(tag_separator)
        if self.is_nl_unavailable:
            # The whole caption file is tags when the separator is a line
            # break, so there is nowhere to put the natural language.
            self.nl_toggle_button.setEnabled(False)
        # A container widget is required to use a layout with a `QDockWidget`.
        container = QWidget()
        layout = QVBoxLayout(container)
        head_layout = QHBoxLayout()
        head_layout.addStretch()
        head_layout.addWidget(self.nl_toggle_button)
        layout.addLayout(head_layout)
        layout.addWidget(self.lock_label)
        layout.addWidget(self.tag_input_box)
        layout.addWidget(self.image_tags_list)
        layout.addWidget(self.nl_text_edit)
        layout.addWidget(self.token_count_label)
        self.setWidget(container)
        self.update_nl_visibility()

        # When a tag is added, select it and scroll to the bottom of the list.
        self.image_tag_list_model.rowsInserted.connect(
            lambda _, __, last_index:
            self.image_tags_list.selectionModel().select(
                self.image_tag_list_model.index(last_index),
                QItemSelectionModel.SelectionFlag.ClearAndSelect))
        self.image_tag_list_model.rowsInserted.connect(
            self.image_tags_list.scrollToBottom)
        # `rowsInserted` does not have to be connected because `dataChanged`
        # is emitted when a tag is added.
        self.image_tag_list_model.modelReset.connect(self.count_tokens)
        self.image_tag_list_model.dataChanged.connect(self.count_tokens)

    @Slot()
    def count_tokens(self):
        caption = self.tag_separator.join(
            self.image_tag_list_model.stringList())
        # Subtract 2 for the `<|startoftext|>` and `<|endoftext|>` tokens.
        caption_token_count = len(self.tokenizer(caption).input_ids) - 2
        if caption_token_count > MAX_TOKEN_COUNT:
            self.token_count_label.setStyleSheet('color: red;')
        else:
            self.token_count_label.setStyleSheet('')
        self.token_count_label.setText(f'{caption_token_count} / '
                                       f'{MAX_TOKEN_COUNT} Tokens')

    @Slot()
    def select_first_tag(self):
        if self.image_tag_list_model.rowCount() == 0:
            return
        self.image_tags_list.select_tag(0)

    def select_last_tag(self):
        tag_count = self.image_tag_list_model.rowCount()
        if tag_count == 0:
            return
        self.image_tags_list.select_tag(tag_count - 1)

    @Slot()
    def update_nl_visibility(self):
        is_nl_mode = self.nl_toggle_button.isChecked()
        if not is_nl_mode:
            self.commit_nl()
        self.nl_text_edit.setVisible(is_nl_mode)
        self.tag_input_box.setVisible(not is_nl_mode)
        self.image_tags_list.setVisible(not is_nl_mode)

    @Slot()
    def commit_nl(self):
        """Save the natural-language caption of the image it belongs to."""
        if self.nl_image is None:
            return
        if self.is_locked or not self.nl_text_edit.document().isModified():
            return
        self.nl_text_edit.document().setModified(False)
        self.nl_edit_requested.emit(self.nl_image,
                                    self.nl_text_edit.toPlainText())

    def set_locked(self, is_locked: bool):
        """Lock tag editing for images marked complete."""
        self.is_locked = is_locked
        self.lock_label.setVisible(is_locked)
        self.tag_input_box.setDisabled(is_locked)
        self.tag_input_box.setPlaceholderText(
            'Tags locked' if is_locked else 'Add Tag')
        self.image_tags_list.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers if is_locked
            else QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed)
        self.image_tags_list.setDragDropMode(
            QAbstractItemView.DragDropMode.NoDragDrop if is_locked
            else QAbstractItemView.DragDropMode.InternalMove)
        self.nl_text_edit.setReadOnly(is_locked)
        self.nl_toggle_button.setDisabled(is_locked or self.is_nl_unavailable)

    def refresh_lock(self):
        if self.image_index is None or not self.image_index.isValid():
            return
        image_list_model = self.proxy_image_list_model.sourceModel()
        image = image_list_model.data(self.image_index,
                                      Qt.ItemDataRole.UserRole)
        self.set_locked(image_list_model.is_completed(image))

    @Slot()
    def load_image_tags(self, proxy_image_index: QModelIndex):
        # Save the natural language of the previous image first.
        self.commit_nl()
        self.image_index = self.proxy_image_list_model.mapToSource(
            proxy_image_index)
        image: Image = self.proxy_image_list_model.data(
            proxy_image_index, Qt.ItemDataRole.UserRole)
        if image is None:
            return
        self.refresh_lock()
        is_typing_here = (self.nl_text_edit.hasFocus()
                          and self.nl_image is image)
        if not is_typing_here and (self.nl_image is not image
                                   or self.nl_text_edit.toPlainText()
                                   != image.nl):
            self.nl_text_edit.setPlainText(image.nl)
            self.nl_text_edit.document().setModified(False)
        self.nl_image = image
        # If the string list already contains the image's tags, do not reload
        # them. This is the case when the tags are edited directly through the
        # image tags editor. Removing this check breaks the functionality of
        # reordering multiple tags at the same time because it gets interrupted
        # after one tag is moved.
        current_string_list = self.image_tag_list_model.stringList()
        if current_string_list == image.tags:
            return
        self.image_tag_list_model.setStringList(image.tags)
        self.count_tokens()
        if self.image_tags_list.hasFocus():
            self.select_first_tag()

    @Slot()
    def reload_image_tags_if_changed(self, first_changed_index: QModelIndex,
                                     last_changed_index: QModelIndex):
        """
        Reload the tags for the current image if its index is in the range of
        changed indices.
        """
        if (first_changed_index.row() <= self.image_index.row()
                <= last_changed_index.row()):
            proxy_image_index = self.proxy_image_list_model.mapFromSource(
                self.image_index)
            self.load_image_tags(proxy_image_index)
