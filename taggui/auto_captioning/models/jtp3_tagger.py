"""JTP-3 Hydra tagger: Project RedRocket's e621 tagger for furry art
(https://huggingface.co/RedRocket/Hydra, formerly RedRocket/JTP-3,
Apache-2.0). Runs with plain PyTorch through the network modules vendored in
jtp3_hydra/ (credit and licence there), the same way Fizgig runs it: weights
loaded from a local copy when one exists (TAGGUI_JTP3_DIR, Fizgig's models
folder on Windows, or TagGUI's models folder: %LOCALAPPDATA%/taggui/models on
Windows, ~/.local/share/taggui/models on Linux), otherwise downloaded once
from the pinned Hugging Face revision.

Scores are shown as the JTP-3 demo shows them, confidence = 2p - 1 (0 = unsure,
1 = sure), and a tag scores at least as high as any tag that implies it
(Hydra's "inherit" mode). Tags use spaces instead of underscores. The rating
tags (safe, questionable, explicit) are left out, as with the WD tagger.
"""
import csv
import os
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image as PilImage

import auto_captioning.captioning_thread as captioning_thread
from auto_captioning.models.wd_tagger import WdTagger, get_tags_to_exclude
from utils import app_paths
from utils.image import Image

JTP3_MODEL_ID = 'JTP-3 Hydra tagger'
REPO = 'RedRocket/Hydra'
REVISION = 'cfa9b0a1ffcf2b8df8553be7673210fd60fba23b'
WEIGHTS = 'models/jtp-3-hydra.safetensors'
TAGS = 'data/jtp-3-hydra-tags.csv'
ARCH = 'naflexvit_so400m_patch16_siglip+rr_hydra'
PATCH = 16
MAX_PATCHES = 1024
RATING_TAGS = {'safe', 'questionable', 'explicit'}


def candidate_dirs() -> list[Path]:
    dirs = []
    if os.environ.get('TAGGUI_JTP3_DIR'):
        dirs.append(Path(os.environ['TAGGUI_JTP3_DIR']))
    if sys.platform == 'win32':
        # Fizgig's copy (read only), if it is on this Windows PC.
        dirs.append(Path(r'H:\Stable_Diffusion\Fizgig\user_data\models'
                         r'\jtp-3-hydra'))
    # Last entry is where it downloads to when no copy is found.
    dirs.append(app_paths.get_models_dir() / 'jtp-3-hydra')
    return dirs


def find_model_dir() -> Path:
    for folder in candidate_dirs():
        if (folder / WEIGHTS).is_file() and (folder / TAGS).is_file():
            return folder
    import huggingface_hub
    folder = candidate_dirs()[-1]
    for filename in (TAGS, WEIGHTS):
        huggingface_hub.hf_hub_download(REPO, filename, revision=REVISION,
                                        local_dir=folder)
    return folder


def fit_patches(width, height):
    """Whole 16-pixel patches, at most 1024 of them, aspect kept, never
    enlarged."""
    pw, ph = max(1, width // PATCH), max(1, height // PATCH)
    if pw * ph <= MAX_PATCHES:
        return pw * PATCH, ph * PATCH
    lo, hi = 0.0, 1.0
    for _ in range(40):
        mid = (lo + hi) / 2
        if (max(1, int(width * mid) // PATCH)
                * max(1, int(height * mid) // PATCH) <= MAX_PATCHES):
            lo = mid
        else:
            hi = mid
    return (max(1, int(width * lo) // PATCH) * PATCH,
            max(1, int(height * lo) // PATCH) * PATCH)


def preprocess(pil_image: PilImage.Image, background=(0, 0, 0)):
    import torch
    if 'A' in pil_image.getbands() or pil_image.mode == 'P':
        pil_image = pil_image.convert('RGBA')
        canvas = PilImage.new('RGBA', pil_image.size,
                              tuple(background) + (255,))
        pil_image = PilImage.alpha_composite(canvas, pil_image)
    pil_image = pil_image.convert('RGB')
    size = fit_patches(*pil_image.size)
    if size != pil_image.size:
        pil_image = pil_image.resize(size, PilImage.Resampling.LANCZOS,
                                     reducing_gap=3.0)
    array = torch.from_numpy(np.asarray(pil_image, dtype=np.uint8).copy())
    rows, cols = size[1] // PATCH, size[0] // PATCH
    array = (array.reshape(rows, PATCH, cols, PATCH, 3)
             .permute(0, 2, 1, 3, 4).reshape(1, rows, cols, PATCH * PATCH * 3))
    return array.float().div_(127.5).sub_(1.0)


def build_network(weights_path: Path, device: str):
    import torch
    from safetensors import safe_open
    from auto_captioning.models.jtp3_hydra.head import (ExtremumPool,
                                                        SwiGLUHead)
    from auto_captioning.models.jtp3_hydra.pool import HydraPool
    from auto_captioning.models.jtp3_hydra.siglip2 import NaFlexVit
    with safe_open(str(weights_path), framework='pt', device='cpu') as file:
        metadata = file.metadata() or {}
        if metadata.get('modelspec.architecture') != ARCH:
            raise RuntimeError(f'{weights_path.name} is not the JTP-3 Hydra '
                               f'checkpoint.')
        state_dict = {key: file.get_tensor(key) for key in file.keys()
                      if key != 'validation'}
    labels = metadata['classifier.labels'].split()
    dtype = torch.bfloat16
    network = NaFlexVit(device='cpu', dtype=dtype)
    network.attn_pool = HydraPool(len(labels), 2048, 64, input_dim=1152,
                                  mid_blocks=0, ff_dim=6144, device='cpu',
                                  dtype=dtype)
    network.head = SwiGLUHead(len(labels), 2048, logit=False, device='cpu',
                              dtype=dtype)
    network.emb_head = ExtremumPool()
    for old, new in (('ff_in.weight', 'ff.proj_in.weight'),
                     ('ff_out.weight', 'ff.proj_out.weight'),
                     ('ff_norm.weight', 'ff.norm.weight'),
                     ('ff_norm.bias', 'ff.norm.bias')):
        state_dict['attn_pool.' + new] = state_dict.pop('attn_pool.' + old)
    state_dict['head.proj.weight'] = state_dict.pop(
        'attn_pool.out_proj.weight').mT
    network.load_state_dict(state_dict, strict=True)
    del state_dict
    network.eval().requires_grad_(False)
    network.to(device=device, dtype=dtype)
    background = {'white': 255, 'grey': 127}.get(
        metadata.get('classifier.background', 'black'), 0)
    return network, labels, (background,) * 3


class Jtp3HydraModel:
    def __init__(self):
        import torch
        folder = find_model_dir()
        self.model_dir = folder
        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self.network, self.labels, self.background = build_network(
            folder / WEIGHTS, self.device)
        implies = {}
        with open(folder / TAGS, encoding='utf-8', newline='') as file:
            for row in csv.DictReader(file):
                if row['implications'].split():
                    implies[row['tag']] = row['implications'].split()
        self.implied_by = {}
        for tag, parents in implies.items():
            for parent in parents:
                self.implied_by.setdefault(parent, []).append(tag)

    def inherit(self, scores: dict) -> dict:
        done = {}

        def best(tag, seen=()):
            if tag in done:
                return done[tag]
            value = scores.get(tag, 0.0)
            for child in self.implied_by.get(tag, ()):
                if child not in seen:
                    value = max(value, best(child, seen + (tag,)))
            done[tag] = value
            return value
        return {tag: best(tag) for tag in scores}

    def generate_tags(self, pil_image: PilImage.Image,
                      settings: dict) -> tuple[tuple, tuple]:
        import torch
        weight = self.network.embeds.proj.weight
        inputs = preprocess(pil_image, self.background).to(
            device=weight.device, dtype=weight.dtype)
        with torch.inference_mode():
            probabilities = self.network(inputs)[0].float().cpu().tolist()
        scores = {label: max(0.0, 2.0 * p - 1.0)
                  for label, p in zip(self.labels, probabilities)}
        scores = self.inherit(scores)
        tags_to_exclude = set(get_tags_to_exclude(settings['tags_to_exclude']))
        seen = set()
        results = []
        for label, score in sorted(scores.items(), key=lambda x: x[1],
                                   reverse=True):
            if score < settings['min_probability']:
                break
            tag = label.replace('_', ' ')
            if (label in RATING_TAGS or tag in tags_to_exclude
                    or label in tags_to_exclude or tag in seen):
                continue
            seen.add(tag)
            results.append((tag, score))
        results = results[:settings['max_tags']]
        if not results:
            return (), ()
        tags, scores_out = zip(*results)
        return tags, scores_out


class Jtp3HydraTagger(WdTagger):
    image_mode = 'RGBA'

    def __init__(self,
                 captioning_thread_: 'captioning_thread.CaptioningThread',
                 caption_settings: dict):
        super().__init__(captioning_thread_, caption_settings)

    def get_model(self):
        return Jtp3HydraModel()

    def get_model_inputs(self, image_prompt: str, image: Image):
        return self.load_image(image)
