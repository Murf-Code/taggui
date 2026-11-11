from pathlib import Path

from PIL import Image as PilImage, ImageDraw

from utils.duplicates import (apart, fingerprint, group_duplicates,
                              group_id, plan_removal)


def make_image(path: Path, color, shape_offset=0, size=(120, 160)):
    image = PilImage.new('RGB', size, 'white')
    draw = ImageDraw.Draw(image)
    draw.ellipse((20 + shape_offset, 30, 100 + shape_offset, 140),
                 fill=color)
    draw.rectangle((5, 5, 40, 25), fill=(30, 30, 30))
    image.save(path)
    return path


def test_identical_and_resized_images_group(tmp_path):
    a = make_image(tmp_path / 'a.png', (200, 40, 40))
    b = tmp_path / 'b.png'
    b.write_bytes(a.read_bytes())
    c = tmp_path / 'c.jpg'
    PilImage.open(a).resize((108, 144)).save(c, quality=85)
    d = make_image(tmp_path / 'd.png', (40, 40, 220), shape_offset=0,
                   size=(160, 120))
    fps = [fingerprint(p) for p in (a, b, c, d)]
    assert apart(fps[0], fps[1]) == 0
    groups = group_duplicates(fps, 4)
    assert len(groups) == 1
    assert set(groups[0]) == {a, b, c}
    # Strictness 0 only keeps the byte-identical (or pixel-identical) pair.
    strict = group_duplicates(fps, 0)
    assert any({a, b} <= set(group) for group in strict)
    assert all(d not in group for group in strict)


def test_plan_removal_keeps_most_tagged_and_copies_tags():
    a, b, c = Path('a.png'), Path('b.png'), Path('c.png')
    groups = [[a, b, c]]
    drop, copies = plan_removal(groups, {}, {a: 1, b: 5, c: 2}, True)
    assert set(drop) == {a, c}
    assert copies == {b: [a, c]}
    keep = {group_id(groups[0]): [a, c]}
    drop, copies = plan_removal(groups, keep, {}, False)
    assert drop == [b] and copies == {}


# The original pairwise grouping, kept to check the vectorized one.
def reference_group(fingerprints, max_distance):
    def hamming(a, b):
        return bin(a ^ b).count('1')

    def color_distance(a, b):
        count = 0
        for i in range(0, min(len(a), len(b)), 3):
            d = sum((a[i + k] - b[i + k]) ** 2 for k in range(3))
            if d > 40 * 40:
                count += 1
        return count

    def apart_(a, b):
        if a.exact == b.exact:
            return 0
        return max(hamming(a.shape_hash, b.shape_hash),
                   color_distance(a.colors, b.colors))

    parent = {}

    def find(key):
        while parent.get(key, key) != key:
            key = parent[key]
        return key

    for i, a in enumerate(fingerprints):
        for b in fingerprints[i + 1:]:
            if a.exact == b.exact or apart_(a, b) <= max_distance:
                ra, rb = find(a.key), find(b.key)
                if ra != rb:
                    parent[ra] = rb
    groups = {}
    for fp in fingerprints:
        groups.setdefault(find(fp.key), []).append(fp.key)
    return [g for g in groups.values() if len(g) > 1]


def random_fingerprints(seed, count=300):
    import random
    from utils.duplicates import Fingerprint
    rng = random.Random(seed)
    bases = [(rng.getrandbits(64), bytes(rng.randrange(256)
                                         for _ in range(48)))
             for _ in range(count // 6)]
    fps = []
    for i in range(count):
        shape, colors = rng.choice(bases)
        for _ in range(rng.randrange(0, 12)):
            shape ^= 1 << rng.randrange(64)
        colors = bytes(min(255, max(0, c + rng.randrange(-60, 61)))
                       if rng.random() < 0.3 else c for c in colors)
        exact = f'h{rng.randrange(count // 2)}' if rng.random() < 0.2 \
            else f'u{i}'
        fps.append(Fingerprint(Path(f'{i}.png'), shape, colors, exact))
    # A repeated path is one image.
    fps.append(Fingerprint(fps[3].key, fps[10].shape_hash, fps[10].colors,
                           'dup-path'))
    return fps


def test_vectorized_grouping_matches_original():
    from utils.duplicates import FingerprintArrays
    grouped = 0
    for seed in range(3):
        fps = random_fingerprints(seed, 240)
        arrays = FingerprintArrays(fps)
        for strictness in (0, 1, 2, 4, 6, 9, 12, 16):
            groups = arrays.group(strictness)
            assert groups == reference_group(fps, strictness), (
                seed, strictness)
            grouped += len(groups)
    assert grouped > 50


def test_fast_hashes_match_original(tmp_path):
    from utils.duplicates import color_grid, dhash
    image = PilImage.open(make_image(tmp_path / 'a.png', (200, 40, 40)))
    gray = list(image.convert('L').resize(
        (9, 8), PilImage.Resampling.BILINEAR).getdata())
    expected = 0
    for y in range(8):
        for x in range(8):
            if gray[y * 9 + x] > gray[y * 9 + x + 1]:
                expected |= 1 << (y * 8 + x)
    assert dhash(image) == expected
    small = image.convert('RGB').resize((4, 4), PilImage.Resampling.BILINEAR)
    assert color_grid(image) == bytes(c for p in small.getdata() for c in p)


def test_fingerprint_all_uses_cache(tmp_path):
    from utils.duplicates import FingerprintCache, fingerprint_all
    paths = [make_image(tmp_path / f'{i}.png', (40 * i, 80, 120))
             for i in range(5)]
    cache_path = tmp_path / 'cache.json'
    first = fingerprint_all(paths, FingerprintCache(cache_path), workers=3)
    assert [fp.key for fp in first] == paths
    assert first == [fingerprint(p) for p in paths]
    import utils.duplicates as duplicates
    original = duplicates.fingerprint
    try:
        duplicates.fingerprint = None   # must not be called
        again = fingerprint_all(paths, FingerprintCache(cache_path))
    finally:
        duplicates.fingerprint = original
    assert again == first
