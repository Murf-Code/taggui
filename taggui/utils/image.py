from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtGui import QIcon


@dataclass
class Image:
    path: Path
    dimensions: tuple[int, int] | None
    tags: list[str] = field(default_factory=list)
    thumbnail: QIcon | None = None
    # Free-form natural-language caption, saved in the caption file after the
    # first line break (the first line holds the tags).
    nl: str = ''
