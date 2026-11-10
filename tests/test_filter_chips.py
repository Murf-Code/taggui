import pytest

from utils.filter_chips import (EXCLUDE, INCLUDE, OTHER, add_chip,
                                chips_to_text, clause_to_chip, make_chip,
                                parse_chip_input, remove_chip,
                                split_top_level, text_to_chips, toggle_chip)
from utils.filter_text import ADD, ADD_OR, EXCLUDE as MODE_EXCLUDE
from utils.filter_text import extend_filter_text


def test_empty_text_has_no_chips():
    assert text_to_chips('') == []
    assert text_to_chips('   ') == []


def test_include_and_exclude_chips():
    chips = text_to_chips('tag:"cat ears" AND NOT tag:"dog"')
    assert [(c.kind, c.label) for c in chips] == [(INCLUDE, 'cat ears'),
                                                  (EXCLUDE, 'dog')]


def test_round_trip_keeps_text():
    text = 'tag:"a" AND NOT tag:"b" AND name:foo'
    assert chips_to_text(text_to_chips(text)) == text


def test_or_group_is_one_neutral_chip_and_keeps_parentheses():
    text = '(tag:"a" OR tag:"b") AND tag:"c"'
    chips = text_to_chips(text)
    assert [c.kind for c in chips] == [OTHER, INCLUDE]
    assert chips_to_text(chips) == text
    # Removing the AND part leaves the OR group on its own.
    assert remove_chip(text, 1) == '(tag:"a" OR tag:"b")'


def test_and_inside_quotes_is_not_split():
    assert split_top_level('tag:"black AND white" AND tag:"x"') == [
        'tag:"black AND white"', 'tag:"x"']


def test_special_characters_round_trip():
    for tag in ['star*', 'what?', '[bracket]', 'quote"d', r'back\slash',
                'black AND white']:
        chip = make_chip(tag)
        parsed = clause_to_chip(chip.clause)
        assert parsed.kind == INCLUDE
        assert parsed.label == tag


def test_parse_chip_input():
    assert parse_chip_input('-dog').kind == EXCLUDE
    assert parse_chip_input('-dog').label == 'dog'
    assert parse_chip_input('+cat').kind == INCLUDE
    assert parse_chip_input('cat').label == 'cat'
    assert parse_chip_input('name:foo').kind == OTHER
    assert parse_chip_input('   ') is None
    # A lone dash is a tag, not an empty exclude.
    assert parse_chip_input('-').kind == INCLUDE


def test_add_chip_replaces_opposite_and_skips_duplicates():
    text = add_chip('', make_chip('cat'))
    text = add_chip(text, make_chip('cat'))
    assert text == 'tag:"cat"'
    text = add_chip(text, make_chip('cat', exclude=True))
    assert text == 'NOT tag:"cat"'


def test_toggle_chip():
    text = 'tag:"a" AND NOT tag:"b"'
    assert toggle_chip(text, 0) == 'NOT tag:"a" AND NOT tag:"b"'
    assert toggle_chip(text, 1) == 'tag:"a" AND tag:"b"'


def test_untagged_chip_label():
    chip = clause_to_chip('tags:=0')
    assert chip.kind == OTHER and chip.label == 'untagged'


@pytest.mark.parametrize('mode,kind', [(ADD, INCLUDE),
                                       (MODE_EXCLUDE, EXCLUDE)])
def test_right_click_stacking_shows_as_chips(mode, kind):
    text = extend_filter_text('tag:"cat"', 'dog', mode)
    chips = text_to_chips(text)
    assert chips[-1].kind == kind and chips[-1].label == 'dog'


def test_right_click_or_stacking_shows_one_group_chip():
    text = extend_filter_text('tag:"cat"', 'dog', ADD_OR)
    chips = text_to_chips(text)
    assert len(chips) == 1 and chips[0].kind == OTHER


def test_generated_text_parses_and_filters(qapp):
    from widgets.image_list import FilterLineEdit
    from utils.image import Image
    from pathlib import Path
    edit = FilterLineEdit()
    text = add_chip(add_chip('', make_chip('cat')),
                    make_chip('dog', exclude=True))
    text = add_chip(text, make_chip('star*'))
    edit.setText(text)
    filter_ = edit.parse_filter_text()
    assert filter_ is not None

    class Proxy:
        tag_separator = ', '
    from models.proxy_image_list_model import ProxyImageListModel
    match = ProxyImageListModel.does_image_match_filter
    proxy = Proxy()
    proxy.does_image_match_filter = lambda image, f: match(proxy, image, f)
    yes = Image(Path('a.png'), None, ['cat', 'star*'])
    no_dog = Image(Path('b.png'), None, ['cat', 'star*', 'dog'])
    no_star = Image(Path('c.png'), None, ['cat', 'starfish'])
    assert match(proxy, yes, filter_)
    assert not match(proxy, no_dog, filter_)
    assert not match(proxy, no_star, filter_)
