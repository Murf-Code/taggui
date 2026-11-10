from pathlib import Path

from PySide6.QtCore import QKeyCombination, QModelIndex, QUrl, Qt, Slot
from PySide6.QtGui import (QAction, QCloseEvent, QDesktopServices, QIcon,
                           QKeySequence, QPixmap, QShortcut)
from PySide6.QtWidgets import (QApplication, QFileDialog, QMainWindow,
                               QMessageBox, QStackedWidget, QVBoxLayout,
                               QWidget)

from dialogs.find_duplicates_dialog import FindDuplicatesDialog
from utils.dataset_export import export_wildcard, export_zip
from utils.tag_colors import get_tag_colors
from widgets.hotkey_bar import HotkeyBar
from transformers import AutoTokenizer

from dialogs.batch_reorder_tags_dialog import BatchReorderTagsDialog
from dialogs.find_and_replace_dialog import FindAndReplaceDialog
from dialogs.settings_dialog import SettingsDialog
from models.image_list_model import ImageListModel, Scope
from models.image_tag_list_model import ImageTagListModel
from models.proxy_image_list_model import ProxyImageListModel
from models.tag_counter_model import TagCounterModel
from utils import edit_history
from utils.big_widgets import BigPushButton
from utils.image import Image
from utils.key_press_forwarder import KeyPressForwarder
from utils.filter_text import extend_filter_text
from utils.settings import DEFAULT_SETTINGS, get_settings, get_tag_separator
from utils.shortcut_remover import ShortcutRemover
from utils.utils import (get_confirmation_dialog_reply, get_resource_path,
                         pluralize)
from widgets.all_tags_editor import AllTagsEditor
from widgets.auto_captioner import AutoCaptioner
from widgets.image_list import ImageList
from widgets.image_tags_editor import ImageTagsEditor
from widgets.image_viewer import ImageViewer

ICON_PATH = Path('images/icon.ico')
GITHUB_REPOSITORY_URL = 'https://github.com/jhc13/taggui'
BUY_ME_A_COFFEE_URL = 'https://buymeacoffee.com/murf_'
# How long status bar messages stay (ms).
STATUS_MESSAGE_TIMEOUT = 6000
TOKENIZER_DIRECTORY_PATH = Path('clip-vit-base-patch32')


class MainWindow(QMainWindow):
    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.settings = get_settings()
        # The path of the currently loaded directory. This is set later when a
        # directory is loaded.
        self.directory_path = None
        image_list_image_width = self.settings.value(
            'image_list_image_width',
            defaultValue=DEFAULT_SETTINGS['image_list_image_width'], type=int)
        tag_separator = get_tag_separator()
        self.image_list_model = ImageListModel(image_list_image_width,
                                               tag_separator)
        tokenizer = AutoTokenizer.from_pretrained(
            get_resource_path(TOKENIZER_DIRECTORY_PATH))
        self.proxy_image_list_model = ProxyImageListModel(
            self.image_list_model, tokenizer, tag_separator)
        self.image_list_model.proxy_image_list_model = (
            self.proxy_image_list_model)
        self.tag_counter_model = TagCounterModel()
        self.image_tag_list_model = ImageTagListModel()

        self.setWindowIcon(QIcon(QPixmap(get_resource_path(ICON_PATH))))
        # Not setting this results in some ugly colors.
        self.setPalette(self.app.style().standardPalette())
        # The font size must be set before creating the widgets to ensure that
        # everything has the correct font size.
        self.set_font_size()
        self.image_viewer = ImageViewer(self.proxy_image_list_model)
        self.create_central_widget()
        self.image_list = ImageList(self.proxy_image_list_model,
                                    tag_separator, image_list_image_width)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea,
                           self.image_list)
        self.image_tags_editor = ImageTagsEditor(
            self.proxy_image_list_model, self.tag_counter_model,
            self.image_tag_list_model, self.image_list, tokenizer,
            tag_separator)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea,
                           self.image_tags_editor)
        self.all_tags_editor = AllTagsEditor(self.tag_counter_model,
                                             tokenizer)
        self.tag_counter_model.all_tags_list = (self.all_tags_editor
                                                .all_tags_list)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea,
                           self.all_tags_editor)
        self.auto_captioner = AutoCaptioner(self.image_list_model,
                                            self.image_list)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea,
                           self.auto_captioner)
        self.tabifyDockWidget(self.all_tags_editor, self.auto_captioner)
        self.all_tags_editor.raise_()
        # Set default widths for the dock widgets.
        # Temporarily set a size for the window so that the dock widgets can be
        # expanded to their default widths. If the window geometry was
        # previously saved, it will be restored later.
        self.resize(image_list_image_width * 8,
                    int(image_list_image_width * 4.5))
        self.resizeDocks([self.image_list, self.image_tags_editor,
                          self.all_tags_editor],
                         [int(image_list_image_width * 2.5)] * 3,
                         Qt.Orientation.Horizontal)
        # Disable some widgets until a directory is loaded.
        self.image_tags_editor.tag_input_box.setDisabled(True)
        self.auto_captioner.start_cancel_button.setDisabled(True)
        self.reload_directory_action = QAction('Reload Directory', parent=self)
        self.reload_directory_action.setDisabled(True)
        self.undo_action = QAction('Undo', parent=self)
        self.redo_action = QAction('Redo', parent=self)
        self.toggle_image_list_action = QAction('Images', parent=self)
        self.toggle_image_tags_editor_action = QAction('Image Tags',
                                                       parent=self)
        self.toggle_all_tags_editor_action = QAction('All Tags', parent=self)
        self.toggle_auto_captioner_action = QAction('Auto-Captioner',
                                                    parent=self)
        self.show_tags_in_image_list_action = QAction(
            'Show Tags in Image List', parent=self)
        self.dataset_actions: list[QAction] = []
        self.create_menus()
        # Context-sensitive shortcuts on the left of the status bar; status
        # messages show in the same place for a few seconds.
        self.hotkey_bar = HotkeyBar()
        self.statusBar().addWidget(self.hotkey_bar, 1)
        self.statusBar().setSizeGripEnabled(True)
        self.app.focusChanged.connect(self.update_hotkey_zone)
        for button in (self.image_viewer.crop_button,
                       self.image_viewer.remove_button):
            button.toggled.connect(
                lambda: self.update_hotkey_zone(None,
                                                self.app.focusWidget()))

        self.image_list_selection_model = (self.image_list.list_view
                                           .selectionModel())
        self.image_list_model.image_list_selection_model = (
            self.image_list_selection_model)
        self.connect_image_list_signals()
        self.connect_image_tags_editor_signals()
        self.connect_all_tags_editor_signals()
        self.connect_auto_captioner_signals()
        # Forward any unhandled image changing key presses to the image list.
        key_press_forwarder = KeyPressForwarder(
            parent=self, target=self.image_list.list_view,
            keys_to_forward=(Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_PageUp,
                             Qt.Key.Key_PageDown, Qt.Key.Key_Home,
                             Qt.Key.Key_End))
        self.installEventFilter(key_press_forwarder)
        # Remove the Ctrl+Z shortcut from text input boxes to prevent it from
        # conflicting with the undo action.
        ctrl_z = QKeyCombination(Qt.KeyboardModifier.ControlModifier,
                                 key=Qt.Key.Key_Z)
        ctrl_y = QKeyCombination(Qt.KeyboardModifier.ControlModifier,
                                 key=Qt.Key.Key_Y)
        shortcut_remover = ShortcutRemover(parent=self,
                                           shortcuts=(ctrl_z, ctrl_y))
        self.image_list.filter_line_edit.installEventFilter(shortcut_remover)
        self.image_tags_editor.tag_input_box.installEventFilter(
            shortcut_remover)
        self.all_tags_editor.filter_line_edit.installEventFilter(
            shortcut_remover)
        # Set keyboard shortcuts.
        focus_filter_images_box_shortcut = QShortcut(
            QKeySequence('Alt+F'), self)
        focus_filter_images_box_shortcut.activated.connect(
            self.image_list.raise_)
        focus_filter_images_box_shortcut.activated.connect(
            self.focus_image_list_filter)
        focus_add_tag_box_shortcut = QShortcut(QKeySequence('Alt+A'), self)
        focus_add_tag_box_shortcut.activated.connect(
            self.image_tags_editor.raise_)
        focus_add_tag_box_shortcut.activated.connect(
            self.image_tags_editor.tag_input_box.setFocus)
        focus_image_tags_list_shortcut = QShortcut(QKeySequence('Alt+I'), self)
        focus_image_tags_list_shortcut.activated.connect(
            self.image_tags_editor.raise_)
        focus_image_tags_list_shortcut.activated.connect(
            self.image_tags_editor.image_tags_list.setFocus)
        focus_image_tags_list_shortcut.activated.connect(
            self.image_tags_editor.select_first_tag)
        focus_search_tags_box_shortcut = QShortcut(QKeySequence('Alt+S'), self)
        focus_search_tags_box_shortcut.activated.connect(
            self.all_tags_editor.raise_)
        focus_search_tags_box_shortcut.activated.connect(
            self.all_tags_editor.filter_line_edit.setFocus)
        focus_caption_button_shortcut = QShortcut(QKeySequence('Alt+C'), self)
        focus_caption_button_shortcut.activated.connect(
            self.auto_captioner.raise_)
        focus_caption_button_shortcut.activated.connect(
            self.auto_captioner.start_cancel_button.setFocus)
        go_to_previous_image_shortcut = QShortcut(QKeySequence('Ctrl+Up'),
                                                  self)
        go_to_previous_image_shortcut.activated.connect(
            self.image_list.go_to_previous_image)
        go_to_next_image_shortcut = QShortcut(QKeySequence('Ctrl+Down'), self)
        go_to_next_image_shortcut.activated.connect(
            self.image_list.go_to_next_image)
        jump_to_first_untagged_image_shortcut = QShortcut(
            QKeySequence('Ctrl+J'), self)
        jump_to_first_untagged_image_shortcut.activated.connect(
            self.image_list.jump_to_first_untagged_image)
        self.restore()
        self.image_tags_editor.tag_input_box.setFocus()

    def closeEvent(self, event: QCloseEvent):
        """Save the window geometry and state before closing."""
        self.settings.setValue('geometry', self.saveGeometry())
        self.settings.setValue('window_state', self.saveState())
        super().closeEvent(event)

    def set_font_size(self):
        font = self.app.font()
        font_size = self.settings.value(
            'font_size', defaultValue=DEFAULT_SETTINGS['font_size'], type=int)
        font.setPointSize(font_size)
        self.app.setFont(font)

    def create_central_widget(self):
        central_widget = QStackedWidget()
        # Put the button inside a widget so that it will not fill up the entire
        # space.
        load_directory_widget = QWidget()
        load_directory_button = BigPushButton('Load Directory...')
        load_directory_button.clicked.connect(self.select_and_load_directory)
        QVBoxLayout(load_directory_widget).addWidget(
            load_directory_button, alignment=Qt.AlignmentFlag.AlignCenter)
        central_widget.addWidget(load_directory_widget)
        central_widget.addWidget(self.image_viewer)
        self.setCentralWidget(central_widget)

    def load_directory(self, path: Path, select_index: int = 0,
                       save_path_to_settings: bool = False):
        self.directory_path = path.resolve()
        if save_path_to_settings:
            self.settings.setValue('directory_path', str(self.directory_path))
        self.setWindowTitle(path.name)
        self.image_list_model.load_directory(path)
        self.image_list.filter_line_edit.clear()
        for action in self.dataset_actions:
            action.setDisabled(False)
        self.all_tags_editor.filter_line_edit.clear()
        # Clear the current index first to make sure that the `currentChanged`
        # signal is emitted even if the image at the index is already selected.
        self.image_list_selection_model.clearCurrentIndex()
        self.image_list.list_view.setCurrentIndex(
            self.proxy_image_list_model.index(select_index, 0))
        self.centralWidget().setCurrentWidget(self.image_viewer)
        self.reload_directory_action.setDisabled(False)
        self.image_tags_editor.tag_input_box.setDisabled(False)
        self.auto_captioner.start_cancel_button.setDisabled(False)
        self.image_tags_editor.refresh_lock()
        self.update_hotkey_zone(None, self.app.focusWidget())

    @Slot()
    def select_and_load_directory(self):
        initial_directory = (str(self.directory_path)
                             if self.directory_path else '')
        load_directory_path = QFileDialog.getExistingDirectory(
            parent=self, caption='Select directory to load images from',
            dir=initial_directory)
        if not load_directory_path:
            return
        self.load_directory(Path(load_directory_path),
                            save_path_to_settings=True)

    @Slot()
    def reload_directory(self):
        # Save the filter text and the index of the selected image to restore
        # them after reloading the directory.
        filter_text = self.image_list.filter_line_edit.text()
        select_index_key = ('image_index'
                            if self.proxy_image_list_model.filter is None
                            else 'filtered_image_index')
        select_index = self.settings.value(select_index_key, type=int) or 0
        self.load_directory(self.directory_path)
        self.image_list.filter_line_edit.setText(filter_text)
        # If the selected image index is out of bounds due to images being
        # deleted, select the last image.
        if select_index >= self.proxy_image_list_model.rowCount():
            select_index = self.proxy_image_list_model.rowCount() - 1
        self.image_list.list_view.setCurrentIndex(
            self.proxy_image_list_model.index(select_index, 0))

    @Slot()
    def show_settings_dialog(self):
        settings_dialog = SettingsDialog(parent=self)
        settings_dialog.exec()

    @Slot()
    def show_find_and_replace_dialog(self):
        find_and_replace_dialog = FindAndReplaceDialog(
            parent=self, image_list_model=self.image_list_model)
        find_and_replace_dialog.exec()

    @Slot()
    def show_batch_reorder_tags_dialog(self):
        batch_reorder_tags_dialog = BatchReorderTagsDialog(
            parent=self, image_list_model=self.image_list_model,
            tag_counter_model=self.tag_counter_model)
        batch_reorder_tags_dialog.exec()

    @Slot()
    def remove_duplicate_tags(self):
        removed_tag_count = self.image_list_model.remove_duplicate_tags()
        message_box = QMessageBox()
        message_box.setWindowTitle('Remove Duplicate Tags')
        message_box.setIcon(QMessageBox.Icon.Information)
        if not removed_tag_count:
            text = 'No duplicate tags were found.'
        else:
            text = (f'Removed {removed_tag_count} duplicate '
                    f'{pluralize("tag", removed_tag_count)}.')
        message_box.setText(text)
        message_box.exec()

    @Slot()
    def remove_empty_tags(self):
        removed_tag_count = self.image_list_model.remove_empty_tags()
        message_box = QMessageBox()
        message_box.setWindowTitle('Remove Empty Tags')
        message_box.setIcon(QMessageBox.Icon.Information)
        if not removed_tag_count:
            text = 'No empty tags were found.'
        else:
            text = (f'Removed {removed_tag_count} empty '
                    f'{pluralize("tag", removed_tag_count)}.')
        message_box.setText(text)
        message_box.exec()

    def create_menus(self):
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu('File')
        load_directory_action = QAction('Load Directory...', parent=self)
        load_directory_action.setShortcut(QKeySequence('Ctrl+L'))
        load_directory_action.triggered.connect(self.select_and_load_directory)
        file_menu.addAction(load_directory_action)
        self.reload_directory_action.setShortcuts(
            [QKeySequence('Ctrl+Shift+L'), QKeySequence('F5')])
        self.reload_directory_action.triggered.connect(self.reload_directory)
        file_menu.addAction(self.reload_directory_action)
        file_menu.addSeparator()
        export_zip_action = QAction('Export Dataset as Zip...', parent=self)
        export_zip_action.setShortcut(QKeySequence('Ctrl+Shift+E'))
        export_zip_action.triggered.connect(self.export_dataset_zip)
        file_menu.addAction(export_zip_action)
        export_wildcard_action = QAction('Export Wildcard File...',
                                         parent=self)
        export_wildcard_action.setToolTip(
            'One caption per line, for __wildcard__ prompts')
        export_wildcard_action.triggered.connect(self.export_wildcard_file)
        file_menu.addAction(export_wildcard_action)
        file_menu.addSeparator()
        settings_action = QAction('Settings...', parent=self)
        settings_action.setShortcut(QKeySequence('Ctrl+Alt+S'))
        settings_action.triggered.connect(self.show_settings_dialog)
        file_menu.addAction(settings_action)
        exit_action = QAction('Exit', parent=self)
        exit_action.setShortcut(QKeySequence('Ctrl+W'))
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        edit_menu = menu_bar.addMenu('Edit')
        self.undo_action.setShortcut(QKeySequence('Ctrl+Z'))
        self.undo_action.triggered.connect(self.undo_any)
        self.undo_action.setDisabled(True)
        edit_menu.addAction(self.undo_action)
        self.redo_action.setShortcuts([QKeySequence('Ctrl+Y'),
                                       QKeySequence('Ctrl+Shift+Z')])
        self.redo_action.triggered.connect(self.redo_any)
        self.redo_action.setDisabled(True)
        edit_menu.addAction(self.redo_action)
        find_and_replace_action = QAction('Find and Replace...', parent=self)
        find_and_replace_action.setShortcut(QKeySequence('Ctrl+R'))
        find_and_replace_action.triggered.connect(
            self.show_find_and_replace_dialog)
        edit_menu.addAction(find_and_replace_action)
        batch_reorder_tags_action = QAction('Batch Reorder Tags...',
                                            parent=self)
        batch_reorder_tags_action.setShortcut(QKeySequence('Ctrl+B'))
        batch_reorder_tags_action.triggered.connect(
            self.show_batch_reorder_tags_dialog)
        edit_menu.addAction(batch_reorder_tags_action)
        remove_duplicate_tags_action = QAction('Remove Duplicate Tags',
                                               parent=self)
        remove_duplicate_tags_action.setShortcut(QKeySequence('Ctrl+D'))
        remove_duplicate_tags_action.triggered.connect(
            self.remove_duplicate_tags)
        edit_menu.addAction(remove_duplicate_tags_action)
        remove_empty_tags_action = QAction('Remove Empty Tags', parent=self)
        remove_empty_tags_action.setShortcut(QKeySequence('Ctrl+E'))
        remove_empty_tags_action.triggered.connect(
            self.remove_empty_tags)
        edit_menu.addAction(remove_empty_tags_action)
        strip_at_tags_action = QAction('Strip @ Tags', parent=self)
        strip_at_tags_action.setToolTip(
            'Remove artist tags that start with @ from every image')
        strip_at_tags_action.triggered.connect(self.strip_at_tags)
        edit_menu.addAction(strip_at_tags_action)
        edit_menu.addSeparator()
        find_duplicates_action = QAction('Find Duplicate Images...',
                                         parent=self)
        find_duplicates_action.setShortcut(QKeySequence('Ctrl+Shift+D'))
        find_duplicates_action.triggered.connect(
            self.show_find_duplicates_dialog)
        edit_menu.addAction(find_duplicates_action)
        edit_menu.addAction(self.image_list.list_view.toggle_completed_action)
        self.dataset_actions = [export_zip_action, export_wildcard_action,
                                strip_at_tags_action, find_duplicates_action]
        for action in self.dataset_actions:
            action.setDisabled(True)

        view_menu = menu_bar.addMenu('View')
        self.toggle_image_list_action.setCheckable(True)
        self.toggle_image_tags_editor_action.setCheckable(True)
        self.toggle_all_tags_editor_action.setCheckable(True)
        self.toggle_auto_captioner_action.setCheckable(True)
        self.toggle_image_list_action.triggered.connect(
            lambda is_checked: self.image_list.setVisible(is_checked))
        self.toggle_image_tags_editor_action.triggered.connect(
            lambda is_checked: self.image_tags_editor.setVisible(is_checked))
        self.toggle_all_tags_editor_action.triggered.connect(
            lambda is_checked: self.all_tags_editor.setVisible(is_checked))
        self.toggle_auto_captioner_action.triggered.connect(
            lambda is_checked: self.auto_captioner.setVisible(is_checked))
        view_menu.addAction(self.toggle_image_list_action)
        view_menu.addAction(self.toggle_image_tags_editor_action)
        view_menu.addAction(self.toggle_all_tags_editor_action)
        view_menu.addAction(self.toggle_auto_captioner_action)
        view_menu.addSeparator()
        self.show_tags_in_image_list_action.setCheckable(True)
        self.show_tags_in_image_list_action.setChecked(
            self.image_list.list_view.show_tags)
        self.show_tags_in_image_list_action.setToolTip(
            'Show each thumbnail with its tags beside it instead of as a '
            'card')
        self.show_tags_in_image_list_action.toggled.connect(
            self.set_show_tags_in_image_list)
        view_menu.addAction(self.show_tags_in_image_list_action)

        help_menu = menu_bar.addMenu('Help')
        open_github_repository_action = QAction('GitHub', parent=self)
        open_github_repository_action.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(GITHUB_REPOSITORY_URL)))
        help_menu.addAction(open_github_repository_action)
        buy_me_a_coffee_action = QAction('Buy Me a Coffee', parent=self)
        buy_me_a_coffee_action.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl(BUY_ME_A_COFFEE_URL)))
        help_menu.addAction(buy_me_a_coffee_action)

    @Slot()
    def next_history_target(self, is_undo: bool):
        """Which history (tags or image edits) Ctrl+Z / Ctrl+Y acts on: the
        most recent one. Returns (kind, action name) or None."""
        tag_stack = (self.image_list_model.undo_stack if is_undo
                     else self.image_list_model.redo_stack)
        candidates = []
        if tag_stack:
            candidates.append((tag_stack[-1].seq, 'tags',
                               tag_stack[-1].action_name))
        image_top = (self.image_viewer.top_undo() if is_undo
                     else self.image_viewer.top_redo())
        if image_top:
            candidates.append((image_top[0], 'image', image_top[1]))
        if not candidates:
            return None
        _, kind, name = max(candidates)
        return kind, name

    @Slot()
    def undo_any(self):
        label = self.image_viewer.image_label
        if label.has_pending_edit():
            # First Ctrl+Z discards an unapplied crop box or brush strokes.
            label.reset_edit()
            label.update()
            self.update_undo_and_redo_actions()
            return
        target = self.next_history_target(is_undo=True)
        if target is None:
            return
        if target[0] == 'image':
            self.image_viewer.undo_edit()
        else:
            self.image_list_model.undo()
        self.update_undo_and_redo_actions()

    @Slot()
    def redo_any(self):
        target = self.next_history_target(is_undo=False)
        if target is None:
            return
        if target[0] == 'image':
            self.image_viewer.redo_edit()
        else:
            self.image_list_model.redo()
        self.update_undo_and_redo_actions()

    def handle_new_edit(self, source: str):
        # A new image edit makes tag redo meaningless.
        if source == 'image' and self.image_list_model.redo_stack:
            self.image_list_model.redo_stack.clear()
        self.update_undo_and_redo_actions()

    def update_undo_and_redo_actions(self):
        undo_target = self.next_history_target(is_undo=True)
        if self.image_viewer.image_label.has_pending_edit():
            # Ctrl+Z first discards unapplied crop or brush strokes.
            self.undo_action.setText('Undo Unapplied Edit')
            self.undo_action.setDisabled(False)
        elif undo_target:
            self.undo_action.setText(f'Undo "{undo_target[1]}"')
            self.undo_action.setDisabled(False)
        else:
            self.undo_action.setText('Undo')
            self.undo_action.setDisabled(True)
        redo_target = self.next_history_target(is_undo=False)
        if redo_target:
            self.redo_action.setText(f'Redo "{redo_target[1]}"')
            self.redo_action.setDisabled(False)
        else:
            self.redo_action.setText('Redo')
            self.redo_action.setDisabled(True)

    @Slot()
    def set_image_list_filter(self):
        filter_ = self.image_list.filter_line_edit.parse_filter_text()
        self.proxy_image_list_model.filter = filter_
        # Apply the new filter.
        self.proxy_image_list_model.invalidateFilter()
        if filter_ is None:
            all_tags_list_selection_model = (self.all_tags_editor
                                             .all_tags_list.selectionModel())
            all_tags_list_selection_model.clearSelection()
            # Clear the current index.
            self.all_tags_editor.all_tags_list.setCurrentIndex(QModelIndex())
            # Select the previously selected image in the unfiltered image
            # list.
            select_index = self.settings.value('image_index', type=int) or 0
            self.image_list.list_view.setCurrentIndex(
                self.proxy_image_list_model.index(select_index, 0))
        else:
            # Select the first image.
            self.image_list.list_view.setCurrentIndex(
                self.proxy_image_list_model.index(0, 0))

    @Slot()
    def save_image_index(self, proxy_image_index: QModelIndex):
        """Save the index of the currently selected image."""
        settings_key = ('image_index'
                        if self.proxy_image_list_model.filter is None
                        else 'filtered_image_index')
        self.settings.setValue(settings_key, proxy_image_index.row())

    def connect_image_list_signals(self):
        self.image_list.filter_line_edit.textChanged.connect(
            self.set_image_list_filter)
        self.image_list_selection_model.currentChanged.connect(
            self.save_image_index)
        self.image_list_selection_model.currentChanged.connect(
            self.image_list.update_image_index_label)
        self.image_list_selection_model.currentChanged.connect(
            self.image_viewer.load_image)
        self.image_list_selection_model.currentChanged.connect(
            self.image_tags_editor.load_image_tags)
        self.image_list_model.modelReset.connect(
            lambda: self.tag_counter_model.count_tags(
                self.image_list_model.images))
        self.image_list_model.dataChanged.connect(
            lambda: self.tag_counter_model.count_tags(
                self.image_list_model.images))
        self.image_list_model.dataChanged.connect(
            self.image_tags_editor.reload_image_tags_if_changed)
        self.image_list_model.update_undo_and_redo_actions_requested.connect(
            self.update_undo_and_redo_actions)
        self.image_viewer.history_changed.connect(
            self.update_undo_and_redo_actions)
        self.image_viewer.image_label.edit_state_changed.connect(
            self.update_undo_and_redo_actions)
        edit_history.on_new_edit(self.handle_new_edit)
        # Rows are inserted or removed from the proxy image list model when the
        # filter is changed.
        self.proxy_image_list_model.rowsInserted.connect(
            lambda: self.image_list.update_image_index_label(
                self.image_list.list_view.currentIndex()))
        self.proxy_image_list_model.rowsRemoved.connect(
            lambda: self.image_list.update_image_index_label(
                self.image_list.list_view.currentIndex()))
        self.image_list.list_view.directory_reload_requested.connect(
            self.reload_directory)
        self.image_list.list_view.tags_paste_requested.connect(
            self.image_list_model.add_tags)
        self.image_list.list_view.completion_toggled.connect(
            self.show_completion_message)
        self.image_list_model.completed_images_changed.connect(
            self.image_tags_editor.refresh_lock)
        self.image_list_model.locked_images_skipped.connect(
            self.show_locked_message)
        self.image_list_model.modelReset.connect(
            self.image_tags_editor.refresh_lock)
        self.tag_counter_model.modelReset.connect(
            lambda: self.image_list.filter_chip_bar.set_tags(
                [tag for tag, _ in self.tag_counter_model.most_common_tags]))
        get_tag_colors().changed.connect(self.refresh_tag_colors)
        # Connecting the signal directly without `isVisible()` causes the menu
        # item to be unchecked when the widget is an inactive tab.
        self.image_list.visibilityChanged.connect(
            lambda: self.toggle_image_list_action.setChecked(
                self.image_list.isVisible()))

    @Slot()
    def update_image_tags(self):
        image_index = self.image_tags_editor.image_index
        image: Image = self.image_list_model.data(image_index,
                                                  Qt.ItemDataRole.UserRole)
        old_tags = image.tags
        new_tags = self.image_tag_list_model.stringList()
        if old_tags == new_tags:
            return
        if self.image_list_model.is_completed(image):
            # Refused by the model, which also restores the editor.
            self.image_list_model.update_image_tags(image_index, new_tags)
            return
        old_tags_count = len(old_tags)
        new_tags_count = len(new_tags)
        if new_tags_count > old_tags_count:
            self.image_list_model.add_to_undo_stack(
                action_name='Add Tag', should_ask_for_confirmation=False)
        elif new_tags_count == old_tags_count:
            if set(new_tags) == set(old_tags):
                self.image_list_model.add_to_undo_stack(
                    action_name='Reorder Tags',
                    should_ask_for_confirmation=False)
            else:
                self.image_list_model.add_to_undo_stack(
                    action_name='Rename Tag',
                    should_ask_for_confirmation=False)
        elif old_tags_count - new_tags_count == 1:
            self.image_list_model.add_to_undo_stack(
                action_name='Delete Tag', should_ask_for_confirmation=False)
        else:
            self.image_list_model.add_to_undo_stack(
                action_name='Delete Tags', should_ask_for_confirmation=False)
        self.image_list_model.update_image_tags(image_index, new_tags)

    def connect_image_tags_editor_signals(self):
        # `rowsInserted` does not have to be connected because `dataChanged`
        # is emitted when a tag is added.
        self.image_tag_list_model.modelReset.connect(self.update_image_tags)
        self.image_tag_list_model.dataChanged.connect(self.update_image_tags)
        self.image_tag_list_model.rowsMoved.connect(self.update_image_tags)
        self.image_tags_editor.visibilityChanged.connect(
            lambda: self.toggle_image_tags_editor_action.setChecked(
                self.image_tags_editor.isVisible()))
        (self.image_tags_editor.image_tags_list
         .image_list_filter_extension_requested.connect(
            self.extend_image_list_filter_text))
        self.image_tags_editor.tag_input_box.tags_addition_requested.connect(
            self.image_list_model.add_tags)
        image_tags_list = self.image_tags_editor.image_tags_list
        image_tags_list.selected_image_count_getter = lambda: len(
            self.image_list.get_selected_image_indices())
        image_tags_list.multi_image_tags_removal_requested.connect(
            self.remove_tags_from_selected_images)
        self.image_tags_editor.nl_edit_requested.connect(self.update_image_nl)

    @Slot(list)
    def remove_tags_from_selected_images(self, tags: list[str]):
        """Remove tags from the selected images that have them, after
        confirmation."""
        selected_images = self.image_list.list_view.get_selected_images()
        affected_count = sum(
            1 for image in selected_images
            if any(tag in image.tags for tag in tags))
        if not affected_count:
            return
        if len(tags) == 1:
            tag_text = f'"{tags[0]}"'
        elif len(tags) < 10:
            tag_text = ', '.join(f'"{tag}"' for tag in tags)
        else:
            tag_text = f'{len(tags)} tags'
        reply = get_confirmation_dialog_reply(
            title=f'Remove {pluralize("Tag", len(tags))}',
            question=f'Remove {tag_text} from {affected_count} selected '
                     f'{pluralize("image", affected_count)}?')
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.image_list_model.delete_tags(tags, scope=Scope.SELECTED_IMAGES)

    @Slot()
    def set_image_list_filter_text(self, selected_tag: str):
        """
        Construct and set the image list filter text from the selected tag in
        the all tags list.
        """
        escaped_selected_tag = (selected_tag.replace('\\', '\\\\')
                                .replace('"', r'\"').replace("'", r"\'"))
        self.image_list.filter_line_edit.setText(
            f'tag:"{escaped_selected_tag}"')

    @Slot(str, str)
    def extend_image_list_filter_text(self, tag: str, mode: str):
        """Stack a tag onto the image list filter (AND, AND NOT or OR)."""
        filter_line_edit = self.image_list.filter_line_edit
        new_text = extend_filter_text(filter_line_edit.text(), tag, mode)
        if new_text != filter_line_edit.text():
            # Setting the text applies the filter like typing does.
            filter_line_edit.setText(new_text)

    @Slot(str)
    def add_tag_to_selected_images(self, tag: str):
        selected_image_indices = self.image_list.get_selected_image_indices()
        self.image_list_model.add_tags([tag], selected_image_indices)
        self.image_tags_editor.select_last_tag()

    def connect_all_tags_editor_signals(self):
        self.all_tags_editor.clear_filter_button.clicked.connect(
            self.image_list.filter_line_edit.clear)
        self.tag_counter_model.tags_renaming_requested.connect(
            get_tag_colors().rename)
        self.tag_counter_model.tags_renaming_requested.connect(
            self.image_list_model.rename_tags)
        self.tag_counter_model.tags_renaming_requested.connect(
            self.image_list.filter_line_edit.clear)
        self.all_tags_editor.all_tags_list.image_list_filter_requested.connect(
            self.set_image_list_filter_text)
        (self.all_tags_editor.all_tags_list
         .image_list_filter_extension_requested.connect(
            self.extend_image_list_filter_text))
        self.all_tags_editor.all_tags_list.tag_addition_requested.connect(
            self.add_tag_to_selected_images)
        self.all_tags_editor.all_tags_list.tags_deletion_requested.connect(
            self.image_list_model.delete_tags)
        (self.all_tags_editor.all_tags_list
         .selected_images_tags_deletion_requested.connect(
            self.remove_tags_from_selected_images))
        self.all_tags_editor.all_tags_list.tags_deletion_requested.connect(
            self.image_list.filter_line_edit.clear)
        self.all_tags_editor.visibilityChanged.connect(
            lambda: self.toggle_all_tags_editor_action.setChecked(
                self.all_tags_editor.isVisible()))

    def connect_auto_captioner_signals(self):
        self.auto_captioner.caption_generated.connect(
            lambda image_index, _, tags:
            self.image_list_model.update_image_tags(image_index, tags))
        self.auto_captioner.caption_generated.connect(
            lambda image_index, *_:
            self.image_tags_editor.reload_image_tags_if_changed(image_index,
                                                                image_index))
        self.auto_captioner.nl_caption_generated.connect(
            lambda image_index, caption, append:
            self.image_list_model.update_image_nl(image_index, caption,
                                                  append=append))
        self.auto_captioner.visibilityChanged.connect(
            lambda: self.toggle_auto_captioner_action.setChecked(
                self.auto_captioner.isVisible()))

    # Features ported from TagBench --------------------------------------

    def show_status(self, text: str):
        self.statusBar().showMessage(text, STATUS_MESSAGE_TIMEOUT)

    @Slot()
    def focus_image_list_filter(self):
        if self.image_list.filter_line_edit.isVisible():
            self.image_list.filter_line_edit.setFocus()
        else:
            self.image_list.filter_chip_bar.tag_input.setFocus()

    @Slot(int)
    def show_locked_message(self, count: int):
        self.show_status(
            f'Skipped {count} complete {pluralize("image", count)}: their '
            f'tags are locked. Press Ctrl+K to mark an image incomplete.')

    @Slot(bool, int)
    def show_completion_message(self, is_completed: bool, count: int):
        state = 'complete (tags locked)' if is_completed else 'incomplete'
        self.show_status(f'Marked {count} {pluralize("image", count)} '
                         f'{state}.')

    @Slot(object, str)
    def update_image_nl(self, image: Image, nl: str):
        if image not in self.image_list_model.images:
            return
        row = self.image_list_model.images.index(image)
        self.image_list_model.update_image_nl(
            self.image_list_model.index(row), nl, add_to_undo_stack=True)

    @Slot()
    def refresh_tag_colors(self):
        for view in (self.image_tags_editor.image_tags_list,
                     self.all_tags_editor.all_tags_list):
            view.viewport().update()

    @Slot(bool)
    def set_show_tags_in_image_list(self, show_tags: bool):
        self.settings.setValue('image_list_show_tags', show_tags)
        self.image_list.list_view.set_show_tags(show_tags)

    @Slot()
    def strip_at_tags(self):
        removed_tag_count = self.image_list_model.strip_at_tags()
        if removed_tag_count:
            self.show_status(f'Removed {removed_tag_count} @ '
                             f'{pluralize("tag", removed_tag_count)}.')
        else:
            self.show_status('No tags start with @.')

    @Slot()
    def show_find_duplicates_dialog(self):
        if len(self.image_list_model.images) < 2:
            self.show_status('Load a folder with at least two images first.')
            return
        dialog = FindDuplicatesDialog(self, self.image_list_model)
        dialog.directory_reload_requested.connect(self.reload_directory)
        dialog.exec()
        if dialog.dropped_count:
            self.show_status(
                f'Moved {dialog.dropped_count} duplicate '
                f'{pluralize("image", dialog.dropped_count)} to the trash.')

    @Slot()
    def export_dataset_zip(self):
        if not self.image_list_model.images or not self.directory_path:
            return
        default_path = str(self.directory_path.parent
                           / f'{self.directory_path.name}.zip')
        zip_path, _ = QFileDialog.getSaveFileName(
            self, 'Export Dataset as Zip', default_path, 'Zip files (*.zip)')
        if not zip_path:
            return
        try:
            count = export_zip(self.image_list_model.images,
                               self.directory_path, Path(zip_path),
                               self.image_list_model.tag_separator)
        except OSError as error:
            QMessageBox.critical(self, 'Error',
                                 f'Failed to write {zip_path}: {error}')
            return
        self.show_status(f'Exported {count} {pluralize("image", count)} and '
                         f'their captions to {zip_path}.')

    @Slot()
    def export_wildcard_file(self):
        if not self.image_list_model.images or not self.directory_path:
            return
        default_path = str(self.directory_path.parent
                           / f'{self.directory_path.name}.txt')
        path, _ = QFileDialog.getSaveFileName(
            self, 'Export Wildcard File', default_path,
            'Text files (*.txt)')
        if not path:
            return
        try:
            count = export_wildcard(self.image_list_model.images, Path(path),
                                    self.image_list_model.tag_separator)
        except OSError as error:
            QMessageBox.critical(self, 'Error',
                                 f'Failed to write {path}: {error}')
            return
        self.show_status(
            f'Wrote {count} {pluralize("caption", count)} to {path}. Use '
            f'__{Path(path).stem}__ in a prompt.')

    @Slot()
    def update_hotkey_zone(self, _old=None, widget=None):
        if self.directory_path is None:
            self.hotkey_bar.set_zone('start')
            return
        # While cropping or brushing, its keys matter most wherever focus is.
        mode = str(self.image_viewer.image_label.mode)
        if mode in ('crop', 'remove'):
            self.hotkey_bar.set_zone(mode)
            return
        zone = None
        editor = self.image_tags_editor
        checks = (
            (self.image_list.filter_chip_bar, 'filter'),
            (self.image_list.filter_line_edit, 'filter'),
            (self.image_list.list_view, 'list'),
            (editor.tag_input_box, 'add'),
            (editor.image_tags_list, 'tags'),
            (editor.nl_text_edit, 'nl'),
            (self.all_tags_editor.filter_line_edit, 'search'),
            (self.all_tags_editor.all_tags_list, 'all'),
            (self.auto_captioner, 'auto'),
            (self.image_viewer, 'view'),
        )
        while widget is not None and zone is None:
            for target, name in checks:
                if widget is target:
                    zone = name
                    break
            widget = widget.parentWidget()
        if zone is None and self.hotkey_bar.zone == 'start':
            zone = 'list'
        if zone:
            self.hotkey_bar.set_zone(zone)

    def restore(self):
        # Restore the window geometry and state.
        if self.settings.contains('geometry'):
            self.restoreGeometry(self.settings.value('geometry', type=bytes))
        else:
            self.showMaximized()
        self.restoreState(self.settings.value('window_state', type=bytes))
        # Get the last index of the last selected image.
        if self.settings.contains('image_index'):
            image_index = self.settings.value('image_index', type=int)
        else:
            image_index = 0
        # Load the last loaded directory.
        if self.settings.contains('directory_path'):
            directory_path = Path(self.settings.value('directory_path',
                                                      type=str))
            if directory_path.is_dir():
                self.load_directory(directory_path, select_index=image_index)
