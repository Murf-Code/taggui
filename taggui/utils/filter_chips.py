"""Turn image list filter text into removable bubbles ("chips") and back.

The filter text stays the single source of truth (it is what
`FilterLineEdit` parses), so the right-click "Add to Filter" stacking, the
All Tags click filter and the text box keep working. The chip bar only
splits the text into its top-level `AND` clauses:

- `tag:"x"`        -> green include chip
- `NOT tag:"x"`    -> red exclude chip
- anything else    -> neutral chip showing the clause text
"""
import re
from dataclasses import dataclass

from utils.filter_text import get_tag_filter_clause

INCLUDE = 'include'
EXCLUDE = 'exclude'
OTHER = 'other'
UNTAGGED_CLAUSE = 'tags:=0'


@dataclass
class Chip:
    kind: str
    # The tag for include/exclude chips, the display text otherwise.
    label: str
    # The clause as it appears in the filter text.
    clause: str


def split_top_level(text: str, keyword: str = 'AND') -> list[str]:
    """Split on a keyword that is outside quotes and parentheses."""
    parts = []
    depth = 0
    in_quote = None
    start = 0
    i = 0
    pattern = re.compile(rf'\s+{keyword}\s+', re.IGNORECASE)
    while i < len(text):
        char = text[i]
        if in_quote:
            if char == '\\':
                i += 2
                continue
            if char == in_quote:
                in_quote = None
        elif char in '"\'':
            in_quote = char
        elif char == '(':
            depth += 1
        elif char == ')':
            depth -= 1
        elif depth == 0 and char.isspace():
            match = pattern.match(text, i)
            if match:
                parts.append(text[start:i])
                start = i = match.end()
                continue
        i += 1
    parts.append(text[start:])
    return [part.strip() for part in parts if part.strip()]


def unescape_tag(quoted: str) -> str:
    """Undo `get_tag_filter_clause()` escaping."""
    tag = re.sub(r'\\(.)', r'\1', quoted)
    return (tag.replace('[[]', '[').replace('[*]', '*')
            .replace('[?]', '?'))


TAG_CLAUSE = re.compile(r'^tag:(?:"((?:\\.|[^"\\])*)"|\'((?:\\.|[^\'\\])*)\''
                        r'|([^\s()"\']+))$', re.IGNORECASE)


def clause_to_chip(clause: str) -> Chip:
    body = clause.strip()
    negated = False
    match = re.match(r'^NOT\s+(.*)$', body, re.IGNORECASE | re.DOTALL)
    if match:
        negated = True
        body = match.group(1).strip()
    tag_match = TAG_CLAUSE.match(body)
    if tag_match:
        raw = next(group for group in tag_match.groups() if group is not None)
        tag = unescape_tag(raw) if not tag_match.group(3) else raw
        return Chip(EXCLUDE if negated else INCLUDE, tag, clause.strip())
    label = clause.strip()
    if re.fullmatch(r'tags\s*:\s*==?\s*0', label, re.IGNORECASE):
        label = 'untagged'
    return Chip(OTHER, label, clause.strip())


def text_to_chips(text: str) -> list[Chip]:
    text = (text or '').strip()
    if not text:
        return []
    return [clause_to_chip(clause) for clause in split_top_level(text)]


def chips_to_text(chips: list[Chip]) -> str:
    clauses = []
    for chip in chips:
        clause = chip.clause
        # A clause with a top-level OR must keep its parentheses.
        if len(split_top_level(clause, 'OR')) > 1:
            clause = f'({clause})'
        clauses.append(clause)
    return ' AND '.join(clauses)


def make_chip(tag: str, exclude: bool = False) -> Chip:
    clause = get_tag_filter_clause(tag)
    if exclude:
        clause = f'NOT {clause}'
    return Chip(EXCLUDE if exclude else INCLUDE, tag, clause)


def parse_chip_input(text: str) -> Chip | None:
    """What the "+ tag" box adds: `-tag` excludes, `+tag` or `tag`
    includes, and a filter expression such as `name:cat` or `tags:<5` is
    added as it is."""
    text = text.strip()
    if not text:
        return None
    if text.startswith('-') and len(text) > 1:
        return make_chip(text[1:].strip(), exclude=True)
    if text.startswith('+') and len(text) > 1:
        return make_chip(text[1:].strip())
    if re.match(r'^(?:NOT\s+)?(?:tag|caption|name|path|tags|chars|tokens):',
                text, re.IGNORECASE) or text.startswith('('):
        return clause_to_chip(text)
    return make_chip(text)


def add_chip(text: str, chip: Chip) -> str:
    """Add a chip; an include replaces the matching exclude and vice
    versa, and a chip that is already there is not added twice."""
    chips = text_to_chips(text)
    kept = []
    for existing in chips:
        same_tag = (existing.kind in (INCLUDE, EXCLUDE)
                    and chip.kind in (INCLUDE, EXCLUDE)
                    and existing.label == chip.label)
        if same_tag or existing.clause == chip.clause:
            continue
        kept.append(existing)
    kept.append(chip)
    return chips_to_text(kept)


def remove_chip(text: str, index: int) -> str:
    chips = text_to_chips(text)
    if 0 <= index < len(chips):
        del chips[index]
    return chips_to_text(chips)


def toggle_chip(text: str, index: int) -> str:
    """Flip an include chip to exclude and back."""
    chips = text_to_chips(text)
    if 0 <= index < len(chips) and chips[index].kind in (INCLUDE, EXCLUDE):
        chip = chips[index]
        chips[index] = make_chip(chip.label, exclude=chip.kind == INCLUDE)
    return chips_to_text(chips)
