"""Duplicate image detection, ported from TagBench's dupe-match.

Each image gets three fingerprints: a 64-bit difference hash of its shape
(9x8 grayscale), a 4x4 color grid, and a hash of the file bytes. Two images
are "apart" by the larger of the shape-hash bit difference and the number
of color-grid cells that differ noticeably; identical files are 0 apart.
Images within the chosen strictness are grouped together.
Everything runs locally with Pillow.
"""
import hashlib
from dataclasses import dataclass
from pathlib import Path

from PIL import Image as PilImage
from PIL.ImageOps import exif_transpose

# Two color cells differ when their RGB distance is above this.
COLOR_CELL_THRESHOLD = 40
DEFAULT_STRICTNESS = 4
MAX_STRICTNESS = 16


@dataclass
class Fingerprint:
    key: Path
    shape_hash: int
    colors: bytes
    exact: str


def dhash(image: PilImage.Image) -> int:
    gray = image.convert('L').resize((9, 8), PilImage.Resampling.BILINEAR)
    pixels = list(gray.getdata())
    value = 0
    bit = 0
    for y in range(8):
        for x in range(8):
            left = pixels[y * 9 + x]
            right = pixels[y * 9 + x + 1]
            if left > right:
                value |= 1 << bit
            bit += 1
    return value


def color_grid(image: PilImage.Image) -> bytes:
    small = image.convert('RGB').resize((4, 4), PilImage.Resampling.BILINEAR)
    return bytes(channel for pixel in small.getdata() for channel in pixel)


def file_hash(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def fingerprint(path: Path) -> Fingerprint:
    data = Path(path).read_bytes()
    exact = file_hash(data)
    try:
        with PilImage.open(path) as image:
            # Decode JPEGs at a reduced size; only 9x8 and 4x4 are needed.
            image.draft('RGB', (128, 128))
            image = exif_transpose(image)
            image.load()
            if image.mode not in ('RGB', 'L'):
                # Composite transparency onto white, like TagBench's canvas.
                rgba = image.convert('RGBA')
                background = PilImage.new('RGBA', rgba.size,
                                          (255, 255, 255, 255))
                image = PilImage.alpha_composite(background, rgba)
            return Fingerprint(Path(path), dhash(image), color_grid(image),
                               exact)
    except OSError:
        # Unreadable images only match byte-identical copies.
        return Fingerprint(Path(path), 0, bytes(48), f'bad-{exact}')


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count('1')


def color_distance(a: bytes, b: bytes) -> int:
    count = 0
    limit = COLOR_CELL_THRESHOLD * COLOR_CELL_THRESHOLD
    for i in range(0, min(len(a), len(b)), 3):
        dr = a[i] - b[i]
        dg = a[i + 1] - b[i + 1]
        db = a[i + 2] - b[i + 2]
        if dr * dr + dg * dg + db * db > limit:
            count += 1
    return count


def apart(a: Fingerprint, b: Fingerprint) -> int:
    if a.exact == b.exact:
        return 0
    return max(hamming(a.shape_hash, b.shape_hash),
               color_distance(a.colors, b.colors))


def group_duplicates(fingerprints: list[Fingerprint],
                     max_distance: int) -> list[list[Path]]:
    """Groups (in input order) of two or more images within
    `max_distance` of each other, joined transitively."""
    parent: dict[Path, Path] = {}

    def find(key: Path) -> Path:
        root = parent.get(key, key)
        if root != key:
            root = find(root)
            parent[key] = root
        return root

    def union(a: Path, b: Path):
        root_a = find(a)
        root_b = find(b)
        if root_a != root_b:
            parent[root_a] = root_b

    for i, a in enumerate(fingerprints):
        for b in fingerprints[i + 1:]:
            if a.exact == b.exact or apart(a, b) <= max_distance:
                union(a.key, b.key)
    groups: dict[Path, list[Path]] = {}
    for fp in fingerprints:
        groups.setdefault(find(fp.key), []).append(fp.key)
    return [group for group in groups.values() if len(group) > 1]


def default_keeper(group: list[Path], tag_counts: dict[Path, int]) -> Path:
    """The image with the most tags (the first one on a tie)."""
    return max(group, key=lambda key: tag_counts.get(key, 0))


def plan_removal(groups: list[list[Path]], keep: dict[tuple, list[Path]],
                 tag_counts: dict[Path, int], copy_tags: bool):
    """Return (paths to drop, {kept path: [dropped paths whose tags it
    gets]})."""
    drop: list[Path] = []
    copies: dict[Path, list[Path]] = {}
    for group in groups:
        keepers = [key for key in keep.get(group_id(group), [])
                   if key in group]
        if not keepers:
            keepers = [default_keeper(group, tag_counts)]
        rest = [key for key in group if key not in keepers]
        drop.extend(rest)
        if copy_tags and rest:
            for keeper in keepers:
                copies.setdefault(keeper, []).extend(rest)
    return drop, copies


def group_id(group: list[Path]) -> tuple:
    return tuple(sorted(str(key) for key in group))
