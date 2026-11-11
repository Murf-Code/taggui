"""The remove brush fills the painted area with the local big-lama model
(utils/image_editing.py); nothing is sent anywhere."""
import os
from pathlib import Path

import numpy as np
import pytest
from PIL import Image as PilImage

import utils.image_editing as image_editing

LAMA_FILE = Path(os.environ.get('TAGGUI_TEST_LAMA_DIR',
                                '/workspace/lama-models')) / 'big-lama.pt'


def striped_image(tmp_path):
    rgb = np.zeros((96, 128, 3), np.uint8)
    rgb[:, :, 0] = 200
    rgb[40:56, 56:72] = (0, 0, 255)   # a blue square to remove
    path = tmp_path / 'pic.png'
    PilImage.fromarray(rgb).save(path)
    mask = np.zeros((96, 128), np.uint8)
    mask[38:58, 54:74] = 255
    return path, rgb, mask


def test_remove_brush_uses_lama(tmp_path, monkeypatch):
    pytest.importorskip('cv2')
    pytest.importorskip('torch')
    calls = []

    def fake_lama(rgb, mask):
        calls.append(mask.copy())
        out = rgb.copy()
        out[mask > 0] = (200, 0, 0)
        return out

    monkeypatch.setattr(image_editing, '_inpaint_lama', fake_lama)
    path, rgb, mask = striped_image(tmp_path)
    image_editing.inpaint_image_file(path, mask)
    assert calls, 'LaMa was not called'
    assert image_editing.last_inpaint_method.startswith('LaMa')
    result = np.asarray(PilImage.open(path).convert('RGB'))
    # The square is gone, everything far from the stroke is untouched.
    assert (result[40:56, 56:72] == (200, 0, 0)).all()
    far = np.ones(mask.shape, bool)
    far[30:66, 46:82] = False
    assert (result[far] == rgb[far]).all()


@pytest.mark.skipif(not LAMA_FILE.exists(), reason='big-lama.pt not found')
def test_real_lama_model(tmp_path, monkeypatch):
    pytest.importorskip('cv2')
    pytest.importorskip('torch')
    monkeypatch.setenv('TAGGUI_MODELS_DIR', str(LAMA_FILE.parent))
    monkeypatch.setattr(image_editing, '_lama_model', None)
    path, rgb, mask = striped_image(tmp_path)
    image_editing.inpaint_image_file(path, mask)
    assert image_editing.last_inpaint_method.startswith('LaMa')
    result = np.asarray(PilImage.open(path).convert('RGB')).astype(int)
    # The blue square is filled with the red around it.
    patch = result[40:56, 56:72]
    assert patch[..., 2].mean() < 60 and patch[..., 0].mean() > 150
