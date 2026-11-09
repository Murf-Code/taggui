"""Image editing helpers for the image viewer: crop, remove (inpaint)."""
import io
from pathlib import Path

import numpy as np
from PIL import Image as PilImage, ImageOps

from utils import app_paths

LAMA_URL = ('https://github.com/enesmsahin/simple-lama-inpainting/releases/'
            'download/v0.1.0/big-lama.pt')
_lama_model = None
_lama_device = None
last_inpaint_method = None


def get_models_dir() -> Path:
    # %LOCALAPPDATA%/taggui/models on Windows, ~/.local/share/taggui/models
    # on Linux, ~/Library/Application Support/taggui/models on macOS.
    return app_paths.get_models_dir()


def load_pil(path: Path) -> PilImage.Image:
    image = PilImage.open(path)
    image.load()
    return image


def save_pil(image: PilImage.Image, path: Path, original: PilImage.Image):
    """Save in the original format with high quality."""
    image_format = (original.format or path.suffix.lstrip('.')).upper()
    if image_format == 'JPG':
        image_format = 'JPEG'
    kwargs = {}
    icc = original.info.get('icc_profile')
    if icc:
        kwargs['icc_profile'] = icc
    if image_format == 'JPEG':
        if image.mode not in ('RGB', 'L'):
            image = image.convert('RGB')
        kwargs.update(quality=95, subsampling=0)
    elif image_format == 'WEBP':
        kwargs.update(quality=95, method=6)
        if original.info.get('lossless'):
            kwargs['lossless'] = True
    buffer = io.BytesIO()
    image.save(buffer, format=image_format, **kwargs)
    # Write in one go so a failed save never leaves a broken file.
    path.write_bytes(buffer.getvalue())


def upright(original: PilImage.Image) -> PilImage.Image:
    """Apply the EXIF orientation so coordinates match what Qt displays."""
    return ImageOps.exif_transpose(original)


def crop_image_file(path: Path, box: tuple[int, int, int, int]):
    original = load_pil(path)
    image = upright(original)
    left, top, right, bottom = box
    left = max(0, min(left, image.width - 1))
    top = max(0, min(top, image.height - 1))
    right = max(left + 1, min(right, image.width))
    bottom = max(top + 1, min(bottom, image.height))
    save_pil(image.crop((left, top, right, bottom)), path, original)


def _get_lama():
    global _lama_model, _lama_device
    if _lama_model is None:
        import torch
        model_path = get_models_dir() / 'big-lama.pt'
        if not model_path.exists():
            model_path.parent.mkdir(parents=True, exist_ok=True)
            torch.hub.download_url_to_file(LAMA_URL, str(model_path))
        _lama_device = torch.device(
            'cuda' if torch.cuda.is_available() else 'cpu')
        _lama_model = torch.jit.load(str(model_path),
                                     map_location=_lama_device)
        _lama_model.eval()
    return _lama_model, _lama_device


def prepare_hole(mask: np.ndarray) -> np.ndarray:
    """Like PhotoCraft's Remove Tool: a stroke drawn around an object also
    removes what it encloses (close loops), and the hole grows by 2 px so the
    object's soft edge and halo go with it."""
    import cv2
    hole = (mask > 0).astype(np.uint8)
    height, width = hole.shape
    # Flood the outside from the border; whatever is not reached is enclosed.
    padded = np.pad(hole, 1)
    flood = padded.copy()
    ff_mask = np.zeros((height + 4, width + 4), np.uint8)
    cv2.floodFill(flood, ff_mask, (0, 0), 2)
    enclosed = flood[1:-1, 1:-1] == 0
    hole[enclosed] = 1
    hole = cv2.dilate(hole, np.ones((5, 5), np.uint8))
    return hole * 255


def _inpaint_lama(rgb: np.ndarray, mask: np.ndarray) -> np.ndarray:
    import torch
    model, device = _get_lama()
    height, width = mask.shape
    pad_h = (8 - height % 8) % 8
    pad_w = (8 - width % 8) % 8
    rgb_p = np.pad(rgb, ((0, pad_h), (0, pad_w), (0, 0)), mode='reflect')
    mask_p = np.pad(mask, ((0, pad_h), (0, pad_w)), mode='reflect')
    image_t = (torch.from_numpy(rgb_p).permute(2, 0, 1)[None].float()
               / 255).to(device)
    mask_t = (torch.from_numpy((mask_p > 0).astype(np.float32))[None, None]
              .to(device))
    with torch.inference_mode():
        result = model(image_t, mask_t)
    result = (result[0].permute(1, 2, 0).clamp(0, 1) * 255).round()
    return result.byte().cpu().numpy()[:height, :width]


def _inpaint_cv2(rgb: np.ndarray, mask: np.ndarray) -> np.ndarray:
    import cv2
    return cv2.inpaint(rgb, (mask > 0).astype(np.uint8) * 255, 5,
                       cv2.INPAINT_TELEA)


def inpaint_rgb(rgb: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Inpaint only a region around the mask (faster, less VRAM)."""
    global last_inpaint_method
    mask = prepare_hole(mask)
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return rgb
    height, width = mask.shape
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    # Sampling window as in PhotoCraft: 3/4 of the larger side, 32..512 px.
    margin = min(512, max(32, int(max(x1 - x0, y1 - y0) * 3 / 4)))
    x0, y0 = max(0, x0 - margin), max(0, y0 - margin)
    x1, y1 = min(width, x1 + margin), min(height, y1 + margin)
    region = rgb[y0:y1, x0:x1]
    region_mask = mask[y0:y1, x0:x1]
    # Limit the size sent to the model.
    max_side = 2048
    scale = min(1.0, max_side / max(region.shape[:2]))
    work, work_mask = region, region_mask
    if scale < 1:
        size = (max(8, int(region.shape[1] * scale)),
                max(8, int(region.shape[0] * scale)))
        work = np.asarray(PilImage.fromarray(region).resize(
            size, PilImage.Resampling.LANCZOS))
        work_mask = np.asarray(PilImage.fromarray(region_mask).resize(
            size, PilImage.Resampling.NEAREST))
    try:
        filled = _inpaint_lama(work, work_mask)
        last_inpaint_method = 'LaMa (' + str(_lama_device) + ')'
    except Exception as exception:
        print(f'LaMa inpainting failed, using OpenCV: {exception}')
        filled = _inpaint_cv2(work, work_mask)
        last_inpaint_method = 'OpenCV Telea'
    if scale < 1:
        filled = np.asarray(PilImage.fromarray(filled).resize(
            (region.shape[1], region.shape[0]), PilImage.Resampling.LANCZOS))
    out = rgb.copy()
    keep = region_mask > 0
    out_region = out[y0:y1, x0:x1]
    out_region[keep] = filled[keep]
    return out


def inpaint_image_file(path: Path, mask: np.ndarray):
    """`mask` is HxW uint8 in upright image coordinates, >0 = remove."""
    original = load_pil(path)
    image = upright(original)
    alpha = image.getchannel('A') if 'A' in image.getbands() else None
    rgb = np.asarray(image.convert('RGB'))
    if mask.shape != rgb.shape[:2]:
        mask = np.asarray(PilImage.fromarray(mask).resize(
            (rgb.shape[1], rgb.shape[0]), PilImage.Resampling.NEAREST))
    result = PilImage.fromarray(inpaint_rgb(rgb, mask))
    if alpha is not None:
        result.putalpha(alpha)
    elif image.mode == 'L':
        result = result.convert('L')
    save_pil(result, path, original)
