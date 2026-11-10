from utils.caption_file import compose_caption, one_line, split_caption


def test_split_tags_and_natural_language():
    tags, nl = split_caption('a, b, c\nA long caption.\nSecond line.', ', ')
    assert tags == ['a', 'b', 'c']
    assert nl == 'A long caption.\nSecond line.'


def test_crlf_and_blank_tags():
    tags, nl = split_caption('a, , b\r\nprose', ', ')
    assert tags == ['a', 'b'] and nl == 'prose'


def test_no_line_break_is_all_tags():
    assert split_caption('a, b', ', ') == (['a', 'b'], '')
    assert split_caption('', ', ') == ([], '')


def test_newline_separator_keeps_old_behavior():
    assert split_caption('a\nb\nc', '\n') == (['a', 'b', 'c'], '')
    assert compose_caption(['a', 'b'], 'ignored', '\n') == 'a\nb'


def test_compose_round_trip():
    text = compose_caption(['a', 'b'], ' prose here ', ', ')
    assert text == 'a, b\nprose here'
    assert split_caption(text, ', ') == (['a', 'b'], 'prose here')
    assert compose_caption(['a'], '', ', ') == 'a'


def test_one_line():
    assert one_line(['a', 'b'], 'Line one.\nLine  two.', ', ') == (
        'a, b Line one. Line two.')
