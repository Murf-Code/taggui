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
