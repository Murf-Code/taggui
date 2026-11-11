"""Smoke tests on the real main window: filters, file location, locking."""
import pytest
from PIL import Image as PilImage
from PySide6.QtCore import Qt

from utils.filter_text import ADD, ADD_OR, EXCLUDE


@pytest.fixture
def window(qapp, tmp_path, monkeypatch):
    folder = tmp_path / 'ds'
    folder.mkdir()
    for name, caption in [('a', 'cat, solo'), ('b', 'dog, solo'),
                          ('c', 'cat, dog')]:
        PilImage.new('RGB', (32, 32), 'blue').save(folder / f'{name}.png')
        (folder / f'{name}.txt').write_text(caption, encoding='utf-8')
    from widgets.main_window import MainWindow
    window = MainWindow(qapp)
    window.image_list_model.dataset_state_dir = tmp_path / 'state'
    window.load_directory(folder)
    qapp.processEvents()
    yield window
    window.close()


def visible_names(window):
    model = window.proxy_image_list_model
    return sorted(model.index(row, 0).data(Qt.ItemDataRole.UserRole).path.name
                  for row in range(model.rowCount()))


def test_right_click_filter_stacking(window, qapp):
    window.extend_image_list_filter_text('cat', ADD)
    window.extend_image_list_filter_text('dog', EXCLUDE)
    qapp.processEvents()
    assert visible_names(window) == ['a.png']
    assert (window.image_list.filter_line_edit.text()
            == 'tag:"cat" AND NOT tag:"dog"')
    window.extend_image_list_filter_text('solo', ADD_OR)
    qapp.processEvents()
    assert visible_names(window) == ['a.png', 'b.png']


def test_open_file_location(window, monkeypatch):
    import widgets.image_list as image_list
    opened = []
    monkeypatch.setattr(image_list, 'show_in_file_manager',
                        lambda path: opened.append(path) or True)
    view = window.image_list.list_view
    view.setCurrentIndex(window.proxy_image_list_model.index(1, 0))
    assert view.open_file_location_action in view.context_menu.actions()
    view.open_file_location_action.trigger()
    assert opened and opened[0].name == 'b.png'


def test_mark_complete_locks_tag_editor(window, qapp):
    view = window.image_list.list_view
    view.setCurrentIndex(window.proxy_image_list_model.index(0, 0))
    qapp.processEvents()
    view.toggle_completed_action.trigger()
    qapp.processEvents()
    image = window.proxy_image_list_model.index(0, 0).data(
        Qt.ItemDataRole.UserRole)
    assert window.image_list_model.is_completed(image)
    assert not window.image_tags_editor.lock_label.isHidden()
    view.toggle_completed_action.trigger()
    qapp.processEvents()
    assert window.image_tags_editor.lock_label.isHidden()


def test_original_filter_box_is_unchanged(window):
    image_list = window.image_list
    assert not hasattr(image_list, 'filter_chip_bar')
    assert image_list.filter_line_edit.isVisibleTo(image_list)


def test_missing_tags_checkbox(window, qapp):
    folder = window.directory_path
    (folder / 'c.txt').write_text('', encoding='utf-8')
    window.reload_directory()
    qapp.processEvents()
    window.image_list.missing_tags_check_box.setChecked(True)
    qapp.processEvents()
    assert visible_names(window) == ['c.png']
    window.image_list.missing_tags_check_box.setChecked(False)
    qapp.processEvents()
    assert visible_names(window) == ['a.png', 'b.png', 'c.png']


def test_natural_language_button_swaps_the_tag_list(window, qapp):
    editor = window.image_tags_editor
    editor.nl_toggle_button.setChecked(True)
    assert editor.image_tags_list.isHidden()
    assert editor.tag_input_box.isHidden()
    assert not editor.nl_text_edit.isHidden()
    editor.nl_toggle_button.setChecked(False)
    assert not editor.image_tags_list.isHidden()
    assert editor.nl_text_edit.isHidden()


def test_explore_views(window, qapp):
    image_list_dock = window.image_list
    assert window.view == 'tags'
    window.set_view('waterfall')
    qapp.processEvents()
    assert window.centralWidget().currentWidget() is window.waterfall_view
    assert image_list_dock.isHidden()
    assert len(window.waterfall_view.images) == 3
    # Clicking a picture selects it in the image list.
    image = window.waterfall_view.images[2]
    window.select_explore_image(image, False)
    current = window.image_list.list_view.currentIndex()
    assert current.data(Qt.ItemDataRole.UserRole) is image
    window.set_view('constellation')
    qapp.processEvents()
    view = window.constellation_view
    tags = sorted(node.tag for node in view.canvas.model.nodes)
    assert tags == ['cat', 'dog', 'solo']
    # Picking a tag selects the first image that has it.
    view.tag_focused.emit('dog')
    qapp.processEvents()
    current = window.image_list.list_view.currentIndex()
    assert 'dog' in current.data(Qt.ItemDataRole.UserRole).tags
    window.set_view('tags')
    qapp.processEvents()
    assert not image_list_dock.isHidden()
    assert window.centralWidget().currentWidget() is not view


def test_view_shortcuts(window, qapp):
    keys = {shortcut.key().toString(): shortcut
            for shortcut in window.view_shortcuts}
    assert sorted(keys) == ['Ctrl+1', 'Ctrl+2', 'Ctrl+3']
    keys['Ctrl+3'].activated.emit()
    assert window.view == 'constellation'
    keys['Ctrl+1'].activated.emit()
    assert window.view == 'tags'


def make_trash(monkeypatch):
    """A trash can on the same drive as the test images."""
    import os
    from pathlib import Path
    from PySide6.QtWidgets import QMessageBox
    data = Path(os.environ['XDG_DATA_HOME'])
    for name in ('files', 'info'):
        (data / 'Trash' / name).mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(QMessageBox, 'critical', staticmethod(
        lambda *args: pytest.fail(f'trash failed: {args[2]}')))


def test_delete_images_skips_folder_rescan(window, qapp, monkeypatch):
    import widgets.image_list as image_list
    from PySide6.QtWidgets import QMessageBox
    make_trash(monkeypatch)
    monkeypatch.setattr(image_list, 'get_confirmation_dialog_reply',
                        lambda *args: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(window.image_list_model, 'load_directory',
                        lambda *args: pytest.fail('folder was rescanned'))
    view = window.image_list.list_view
    view.setCurrentIndex(window.proxy_image_list_model.index(1, 0))
    qapp.processEvents()
    view.delete_selected_images()
    qapp.processEvents()
    assert visible_names(window) == ['a.png', 'c.png']
    assert not (window.directory_path / 'b.png').exists()
    assert not (window.directory_path / 'b.txt').exists()
    from collections import Counter
    expected = Counter()
    for image in window.image_list_model.images:
        expected.update(image.tags)
    assert window.tag_counter_model.tag_counter == expected
    assert view.currentIndex().row() == 1


def test_remove_images_keeps_order(window, qapp):
    model = window.image_list_model
    names = [image.path.name for image in model.images]
    removed = model.remove_images({model.images[0].path,
                                   model.images[2].path})
    assert [image.path.name for image in removed] == [names[0], names[2]]
    assert [image.path.name for image in model.images] == [names[1]]
    assert visible_names(window) == [names[1]]


def test_find_duplicates_drop_the_others(window, qapp, monkeypatch):
    import shutil
    import dialogs.find_duplicates_dialog as dialog_module
    from PySide6.QtWidgets import QMessageBox
    make_trash(monkeypatch)
    folder = window.directory_path
    shutil.copy(folder / 'a.png', folder / 'd.png')
    (folder / 'd.txt').write_text('cat, extra', encoding='utf-8')
    window.reload_directory()
    qapp.processEvents()
    monkeypatch.setattr(dialog_module, 'get_confirmation_dialog_reply',
                        lambda **kwargs: QMessageBox.StandardButton.Yes)
    dialog = dialog_module.FindDuplicatesDialog(window,
                                                window.image_list_model)
    dialog.images_deleted.connect(window.remove_deleted_images)
    dialog.compute_fingerprints()
    dialog.fingerprint_thread.wait()
    for _ in range(20):
        qapp.processEvents()
    # Every image is blue and 32x32, so they all look alike.
    assert dialog.groups and len(dialog.groups[0]) == 4
    dialog.strictness_slider.setValue(0)
    dialog.drop_others()
    qapp.processEvents()
    assert dialog.dropped_count == 3
    assert len(window.image_list_model.images) == 1
    dialog.done(0)
