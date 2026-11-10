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


def test_right_click_filter_stacking_and_bubbles(window, qapp):
    window.extend_image_list_filter_text('cat', ADD)
    window.extend_image_list_filter_text('dog', EXCLUDE)
    qapp.processEvents()
    assert visible_names(window) == ['a.png']
    from widgets.filter_chip_bar import FilterChip
    flow = window.image_list.filter_chip_bar.flow
    chips = [flow.itemAt(i).widget().chip for i in range(flow.count())
             if isinstance(flow.itemAt(i).widget(), FilterChip)]
    assert [(chip.kind, chip.label) for chip in chips] == [
        ('include', 'cat'), ('exclude', 'dog')]
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
