"""Caption file layout shared with TagBench: the first line holds the tags,
and anything after the first line break is a natural-language caption.

When the tag separator itself contains a line break, the whole file is
tags (the old behavior) and there is no natural-language part."""
import re


def separator_uses_newline(tag_separator: str) -> bool:
    return '\n' in tag_separator


def split_tags(text: str, tag_separator: str) -> list[str]:
    tags = [tag.strip() for tag in text.split(tag_separator)]
    return [tag for tag in tags if tag]


def split_caption(text: str, tag_separator: str) -> tuple[list[str], str]:
    """Return (tags, natural-language caption) from caption file text."""
    if not text:
        return [], ''
    if separator_uses_newline(tag_separator):
        return split_tags(text, tag_separator), ''
    match = re.search(r'\r?\n', text)
    if not match:
        return split_tags(text, tag_separator), ''
    first_line = text[:match.start()]
    nl = text[match.end():].strip()
    return split_tags(first_line, tag_separator), nl


def compose_caption(tags: list[str], nl: str, tag_separator: str) -> str:
    caption = tag_separator.join(tags)
    nl = (nl or '').strip()
    if nl and not separator_uses_newline(tag_separator):
        return f'{caption}\n{nl}'
    return caption


def one_line(tags: list[str], nl: str, tag_separator: str) -> str:
    """The caption on a single line (for wildcard files)."""
    text = compose_caption(tags, nl, tag_separator)
    return re.sub(r'\s+', ' ', text.replace('\n', ' ')).strip()
