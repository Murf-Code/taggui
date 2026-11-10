from pathlib import Path

import pytest
from PIL import Image as PilImage
from PySide6.QtCore import Qt

from models.image_list_model import COMPLETED_ROLE, ImageListModel, Scope


@pytest.fixture
def dataset(tmp_path):
    folder = tmp_path / 'ds'
    folder.mkdir()
    for name, caption in [('a', 'cat, @artist, solo\nA cat sitting.'),
                          ('b', 'dog, solo'), ('c', None)]:
        PilImage.new('RGB', (8, 8), 'red').save(folder / f'{name}.png')
        if caption is not None:
            (folder / f'{name}.txt').write_text(caption, encoding='utf-8')
    return folder


@pytest.fixture
def model(qapp, dataset, tmp_path, monkeypatch):
    import models.image_list_model as module
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(module, 'get_confirmation_dialog_reply',
                        lambda **kwargs: QMessageBox.StandardButton.Yes)
    model = ImageListModel(64, ', ')
    model.dataset_state_dir = tmp_path / 'state'
    model.load_directory(dataset)
    return model


def caption(folder, name):
    return (folder / f'{name}.txt').read_text(encoding='utf-8')


def test_load_splits_natural_language(model):
    a = model.images[0]
    assert a.tags == ['cat', '@artist', 'solo']
    assert a.nl == 'A cat sitting.'


def test_tag_edits_keep_natural_language(model, dataset):
    model.add_tags(['new'], [model.index(0)])
    assert caption(dataset, 'a') == 'cat, @artist, solo, new\nA cat sitting.'


def test_update_nl_and_undo(model, dataset):
    model.update_image_nl(model.index(1), 'A dog.', add_to_undo_stack=True)
    assert caption(dataset, 'b') == 'dog, solo\nA dog.'
    model.update_image_nl(model.index(1), 'Running.', append=True)
    assert model.images[1].nl == 'A dog. Running.'
    model.undo()
    assert model.images[1].nl == ''
    assert caption(dataset, 'b') == 'dog, solo'


def test_strip_at_tags(model, dataset):
    assert model.strip_at_tags() == 1
    assert model.images[0].tags == ['cat', 'solo']
    assert caption(dataset, 'a') == 'cat, solo\nA cat sitting.'


def test_completed_images_are_locked(model, dataset):
    skipped = []
    model.locked_images_skipped.connect(skipped.append)
    a = model.images[0]
    assert model.toggle_completed([a]) is True
    assert model.data(model.index(0), COMPLETED_ROLE) is True
    before = caption(dataset, 'a')
    model.add_tags(['x'], [model.index(0), model.index(1)])
    model.delete_tags(['solo'])
    model.update_image_tags(model.index(0), ['changed'])
    model.update_image_nl(model.index(0), 'changed')
    assert caption(dataset, 'a') == before
    assert model.images[1].tags == ['dog', 'x']
    assert skipped
    # Undo does not touch the locked image either.
    model.undo()
    assert caption(dataset, 'a') == before
    # The state survives a reload.
    model.load_directory(dataset)
    assert model.is_completed(model.images[0])
    model.toggle_completed([model.images[0]])
    model.load_directory(dataset)
    assert not model.is_completed(model.images[0])


def test_merge_tags_into(model):
    a, b = model.images[0].path, model.images[1].path
    assert model.merge_tags_into({b: [a]}) == 1
    assert model.images[1].tags == ['dog', 'solo', 'cat', '@artist']
