import zipfile
from pathlib import Path

from utils.dataset_export import export_wildcard, export_zip
from utils.image import Image


def test_export_zip_keeps_subfolders_and_captions(tmp_path):
    root = tmp_path / 'ds'
    (root / 'sub').mkdir(parents=True)
    a = root / 'a.png'
    b = root / 'sub' / 'b.jpg'
    a.write_bytes(b'png')
    b.write_bytes(b'jpg')
    images = [Image(a, None, ['x', 'y'], nl='Prose.'),
              Image(b, None, ['z'])]
    out = tmp_path / 'out.zip'
    assert export_zip(images, root, out, ', ') == 2
    with zipfile.ZipFile(out) as archive:
        names = set(archive.namelist())
        assert names == {'a.png', 'a.txt', 'sub/b.jpg', 'sub/b.txt'}
        assert archive.read('a.txt').decode() == 'x, y\nProse.'
        assert archive.read('sub/b.jpg') == b'jpg'


def test_export_zip_renames_clashing_names(tmp_path):
    a = tmp_path / 'one' / 'pic.png'
    b = tmp_path / 'two' / 'pic.png'
    for path in (a, b):
        path.parent.mkdir()
        path.write_bytes(b'x')
    out = tmp_path / 'out.zip'
    export_zip([Image(a, None, []), Image(b, None, [])], None, out, ', ')
    with zipfile.ZipFile(out) as archive:
        assert set(archive.namelist()) == {'pic.png', 'pic.txt',
                                           'pic-2.png', 'pic-2.txt'}


def test_export_wildcard(tmp_path):
    images = [Image(Path('a.png'), None, ['x', 'y'], nl='Line\ntwo.'),
              Image(Path('b.png'), None, []),
              Image(Path('c.png'), None, ['z'])]
    out = tmp_path / 'w.txt'
    assert export_wildcard(images, out, ', ') == 2
    assert out.read_text() == 'x, y Line two.\nz\n'
