"""Export the loaded dataset (ported from TagBench's downloads; free and
local here): a zip of every image with its caption, or a prompt wildcard
file with one caption per line."""
import zipfile
from pathlib import Path

from utils.caption_file import compose_caption, one_line
from utils.image import Image


def archive_name(directory_path: Path | None, image_path: Path) -> str:
    if directory_path is not None:
        try:
            return image_path.resolve().relative_to(
                Path(directory_path).resolve()).as_posix()
        except ValueError:
            pass
    return image_path.name


def export_zip(images: list[Image], directory_path: Path | None,
               zip_path: Path, tag_separator: str) -> int:
    """Write the images and their captions (as `.txt` next to each image,
    keeping subfolders) into a zip. Returns the number of images."""
    used: set[str] = set()
    count = 0
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for image in images:
            name = archive_name(directory_path, image.path)
            stem, dot, suffix = name.rpartition('.')
            if not dot:
                stem, suffix = name, ''
            candidate, n = name, 2
            while (candidate.lower() in used
                   or f'{candidate.rpartition(".")[0]}.txt'.lower() in used):
                candidate = f'{stem}-{n}.{suffix}' if suffix else f'{stem}-{n}'
                n += 1
            caption_name = (candidate.rpartition('.')[0] or candidate) + '.txt'
            used.add(candidate.lower())
            used.add(caption_name.lower())
            # Images are already compressed; store them as they are.
            archive.write(image.path, candidate,
                          compress_type=zipfile.ZIP_STORED)
            archive.writestr(caption_name, compose_caption(
                image.tags, image.nl, tag_separator))
            count += 1
    return count


def wildcard_lines(images: list[Image], tag_separator: str) -> list[str]:
    lines = [one_line(image.tags, image.nl, tag_separator)
             for image in images]
    return [line for line in lines if line]


def export_wildcard(images: list[Image], path: Path,
                    tag_separator: str) -> int:
    """One caption per line, no file names. In a prompt, `__name__` (the
    file name without .txt) picks one line. Returns the number of lines."""
    lines = wildcard_lines(images, tag_separator)
    Path(path).write_text('\n'.join(lines) + ('\n' if lines else ''),
                          encoding='utf-8')
    return len(lines)
