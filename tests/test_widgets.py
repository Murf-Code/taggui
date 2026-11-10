from pathlib import Path

from utils.dataset_state import load_completed, save_completed
from utils.filter_chips import EXCLUDE, INCLUDE


def test_dataset_state_round_trip(tmp_path):
    save_completed(tmp_path / 'ds', {'a.png', 'sub/b.png'}, tmp_path / 's')
    assert load_completed(tmp_path / 'ds', tmp_path / 's') == {
        'a.png', 'sub/b.png'}
    assert load_completed(tmp_path / 'other', tmp_path / 's') == set()


def test_tag_colors(qapp):
    from utils.tag_colors import get_tag_colors
    colors = get_tag_colors()
    colors.set_color(['Cat'], '#ff0000')
    assert colors.color_for('cat') == '#ff0000'
    assert colors.icon_for('cat') is not None
    colors.rename(['cat'], 'kitty')
    assert colors.color_for('kitty') == '#ff0000'
    colors.set_color(['cat', 'kitty'], None)
    assert colors.color_for('cat') is None


def test_filter_chip_bar_edits_filter_text(qapp):
    from widgets.filter_chip_bar import FilterChip, FilterChipBar
    from widgets.image_list import FilterLineEdit
    edit = FilterLineEdit()
    bar = FilterChipBar(edit)
    bar.add_text('cat ears')
    bar.add_text('-dog')
    assert edit.text() == 'tag:"cat ears" AND NOT tag:"dog"'
    qapp.processEvents()
    chips = [bar.flow.itemAt(i).widget() for i in range(bar.flow.count())
             if isinstance(bar.flow.itemAt(i).widget(), FilterChip)]
    assert [(c.chip.kind, c.chip.label) for c in chips] == [
        (INCLUDE, 'cat ears'), (EXCLUDE, 'dog')]
    # The full tag is shown, not squashed.
    assert 'cat ears' in chips[0].label.text()
    chips[0].toggled.emit()
    assert edit.text() == 'NOT tag:"cat ears" AND NOT tag:"dog"'
    qapp.processEvents()
    chips = [bar.flow.itemAt(i).widget() for i in range(bar.flow.count())
             if isinstance(bar.flow.itemAt(i).widget(), FilterChip)]
    chips[1].removed.emit()
    assert edit.text() == 'NOT tag:"cat ears"'
    bar.untagged_button.setChecked(True)
    assert edit.text() == 'NOT tag:"cat ears" AND tags:=0'
    bar.untagged_button.setChecked(False)
    assert edit.text() == 'NOT tag:"cat ears"'
    # The text box is hidden behind the Text button.
    assert edit.isHidden()
