"""Duplicate image detection, ported from TagBench's dupe-match.

Each image gets three fingerprints: a 64-bit difference hash of its shape
(9x8 grayscale), a 4x4 color grid, and a hash of the file bytes. Two images
are "apart" by the larger of the shape-hash bit difference and the number
of color-grid cells that differ noticeably; identical files are 0 apart.
Images within the chosen strictness are grouped together.
Everything runs locally with Pillow.
"""
import hashlib
import io
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
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


# Bit weights of the 8x8 difference hash, row by row.
_DHASH_WEIGHTS = (np.uint64(1) << np.arange(64, dtype=np.uint64)).reshape(8, 8)


def dhash(image: PilImage.Image) -> int:
    gray = image.convert('L').resize((9, 8), PilImage.Resampling.BILINEAR)
    pixels = np.frombuffer(gray.tobytes(), np.uint8).reshape(8, 9)
    bits = pixels[:, :8] > pixels[:, 1:]
    return int(_DHASH_WEIGHTS[bits].sum(dtype=np.uint64))


def color_grid(image: PilImage.Image) -> bytes:
    small = image.convert('RGB').resize((4, 4), PilImage.Resampling.BILINEAR)
    return small.tobytes()


def file_hash(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def fingerprint(path: Path) -> Fingerprint:
    # Read the file once: hash the bytes and decode from memory.
    data = Path(path).read_bytes()
    exact = file_hash(data)
    try:
        with PilImage.open(io.BytesIO(data)) as image:
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


def _components(count: int, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Connected-component label (smallest member) of each node."""
    labels = np.arange(count)
    if not len(a):
        return labels
    while True:
        low = np.minimum(labels[a], labels[b])
        previous = labels.copy()
        np.minimum.at(labels, a, low)
        np.minimum.at(labels, b, low)
        # Pointer jumping.
        while True:
            jumped = labels[labels]
            if np.array_equal(jumped, labels):
                break
            labels = jumped
        if np.array_equal(labels, previous):
            return labels


def _popcount(values: np.ndarray) -> np.ndarray:
    if hasattr(np, 'bitwise_count'):
        return np.bitwise_count(values)
    table = np.array([bin(i).count('1') for i in range(256)], np.uint8)
    return table[values.view(np.uint8)].reshape(*values.shape, 8).sum(
        axis=-1, dtype=np.uint8)


class FingerprintArrays:
    """The fingerprints packed into numpy arrays for fast grouping. Build
    once and group at any strictness without touching the images."""

    def __init__(self, fingerprints: list[Fingerprint]):
        self.fingerprints = fingerprints
        count = len(fingerprints)
        self.hashes = np.fromiter(
            (fp.shape_hash & 0xFFFFFFFFFFFFFFFF for fp in fingerprints),
            np.uint64, count)
        colors = np.zeros((count, 48), np.int32)
        for i, fp in enumerate(fingerprints):
            cells = np.frombuffer(fp.colors[:48], np.uint8)
            colors[i, :len(cells)] = cells
        self.colors = colors.reshape(count, 16, 3)
        # Cells beyond the shorter grid are not compared.
        self.cell_counts = np.fromiter(
            (min(len(fp.colors), 48) // 3 for fp in fingerprints),
            np.int32, count)
        _, self.exact_ids = np.unique([fp.exact for fp in fingerprints],
                                      return_inverse=True)
        # Paths that appear more than once are the same node.
        node_of: dict[Path, int] = {}
        self.nodes = np.fromiter(
            (node_of.setdefault(fp.key, i)
             for i, fp in enumerate(fingerprints)), np.int64, count)
        self.is_simple = (bool((self.cell_counts == 16).all())
                          and all(0 <= fp.shape_hash < 1 << 64
                                  for fp in fingerprints))

    def pairs_within(self, max_distance: int, block: int = 256):
        """Index pairs (i < j) whose files are identical or that are within
        `max_distance` apart."""
        count = len(self.fingerprints)
        limit = COLOR_CELL_THRESHOLD * COLOR_CELL_THRESHOLD
        firsts, seconds = [], []
        # Identical files: link each to the first copy.
        first_of = np.full(int(self.exact_ids.max(initial=-1)) + 1, -1)
        for i in range(count - 1, -1, -1):
            first_of[self.exact_ids[i]] = i
        same = np.nonzero(first_of[self.exact_ids] != np.arange(count))[0]
        firsts.append(first_of[self.exact_ids[same]])
        seconds.append(same)
        for start in range(0, count, block):
            stop = min(count, start + block)
            rows = self.hashes[start:stop, None]
            columns = self.hashes[None, start:]
            bits = _popcount(rows ^ columns)
            # Only j > i; the color check can only raise the distance.
            candidates = bits <= max_distance
            candidates &= (np.arange(start, count)[None, :]
                           > np.arange(start, stop)[:, None])
            i, j = np.nonzero(candidates)
            if not len(i):
                continue
            i = i + start
            j = j + start
            differences = self.colors[i] - self.colors[j]
            far = ((differences * differences).sum(axis=2) > limit).sum(
                axis=1)
            keep = far <= max_distance
            firsts.append(i[keep])
            seconds.append(j[keep])
        return np.concatenate(firsts), np.concatenate(seconds)

    def group(self, max_distance: int) -> list[list[Path]]:
        if len(self.fingerprints) < 2:
            return []
        if not self.is_simple:
            return _group_duplicates_slow(self.fingerprints, max_distance)
        count = len(self.fingerprints)
        a, b = self.pairs_within(max_distance)
        labels = _components(count, self.nodes[a], self.nodes[b])
        labels = labels[self.nodes]
        groups: dict[int, list[Path]] = {}
        for fp, label in zip(self.fingerprints, labels.tolist()):
            groups.setdefault(label, []).append(fp.key)
        return [group for group in groups.values() if len(group) > 1]


def group_duplicates(fingerprints: list[Fingerprint],
                     max_distance: int) -> list[list[Path]]:
    """Groups (in input order) of two or more images within
    `max_distance` of each other, joined transitively."""
    return FingerprintArrays(fingerprints).group(max_distance)


def _group_duplicates_slow(fingerprints: list[Fingerprint],
                           max_distance: int) -> list[list[Path]]:
    """The plain pairwise version, for unusual fingerprints."""
    parent: dict[Path, Path] = {}

    def find(key: Path) -> Path:
        root = parent.get(key, key)
        while root != parent.get(root, root):
            root = parent.get(root, root)
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


# Fingerprint cache ----------------------------------------------------------

CACHE_VERSION = 1
MAX_CACHE_ENTRIES = 300_000


def _cache_key(path: Path, stat: os.stat_result) -> str:
    return f'{path}|{stat.st_mtime_ns}|{stat.st_size}'


class FingerprintCache:
    """Fingerprints saved by path, modification time and size, so running
    Find Duplicate Images again does not read unchanged images."""

    def __init__(self, path: Path | None):
        self.path = path
        self.entries: dict[str, list] = {}
        self.is_dirty = False
        if path is None:
            return
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            if data.get('version') == CACHE_VERSION:
                self.entries = data.get('entries', {})
        except (OSError, ValueError, AttributeError):
            self.entries = {}

    def get(self, key: str, path: Path) -> Fingerprint | None:
        entry = self.entries.get(key)
        if entry is None:
            return None
        try:
            return Fingerprint(path, int(entry[0], 16),
                               bytes.fromhex(entry[1]), entry[2])
        except (ValueError, IndexError, TypeError):
            return None

    def put(self, key: str, fp: Fingerprint):
        self.entries[key] = [format(fp.shape_hash, 'x'), fp.colors.hex(),
                             fp.exact]
        self.is_dirty = True

    def save(self):
        if self.path is None or not self.is_dirty:
            return
        entries = self.entries
        if len(entries) > MAX_CACHE_ENTRIES:
            entries = dict(list(entries.items())[-MAX_CACHE_ENTRIES:])
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix('.tmp')
            temporary.write_text(json.dumps(
                {'version': CACHE_VERSION, 'entries': entries}),
                encoding='utf-8')
            os.replace(temporary, self.path)
            self.is_dirty = False
        except OSError:
            pass


def default_cache_path() -> Path:
    from utils.app_paths import get_user_data_dir
    return get_user_data_dir() / 'duplicate-fingerprints.json'


def fingerprint_all(paths: list[Path], cache: FingerprintCache | None = None,
                    workers: int | None = None,
                    progress: Callable[[int], None] | None = None,
                    cancel: threading.Event | None = None
                    ) -> list[Fingerprint] | None:
    """Fingerprint `paths` on several threads (decoding and hashing release
    the GIL). Results are in input order; files that cannot be read are left
    out. Returns None if canceled."""
    results: list[Fingerprint | None] = [None] * len(paths)
    todo: list[tuple[int, Path, str | None]] = []
    for i, path in enumerate(paths):
        key = None
        if cache is not None:
            try:
                key = _cache_key(Path(path), os.stat(path))
            except OSError:
                continue
            cached = cache.get(key, Path(path))
            if cached is not None:
                results[i] = cached
                continue
        todo.append((i, Path(path), key))
    done = len(paths) - len(todo)
    if progress:
        progress(done)

    def work(item):
        if cancel is not None and cancel.is_set():
            return item, None
        try:
            return item, fingerprint(item[1])
        except OSError:
            return item, None

    workers = workers or min(32, (os.cpu_count() or 1) + 2)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        try:
            for (i, _, key), fp in executor.map(work, todo, chunksize=8):
                done += 1
                if cancel is not None and cancel.is_set():
                    break
                if fp is not None:
                    results[i] = fp
                    if cache is not None and key is not None:
                        cache.put(key, fp)
                if progress:
                    progress(done)
        finally:
            if cancel is not None and cancel.is_set():
                executor.shutdown(wait=True, cancel_futures=True)
    if cache is not None:
        cache.save()
    if cancel is not None and cancel.is_set():
        return None
    return [fp for fp in results if fp is not None]


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
