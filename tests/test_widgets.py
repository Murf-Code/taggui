from pathlib import Path

from utils.dataset_state import load_completed, save_completed


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
