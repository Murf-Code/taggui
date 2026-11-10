"""Per-folder state that is not stored in the caption files: which images
are marked complete. Kept in TagGUI's user data folder (not in the dataset
folder), one small JSON file per loaded folder."""
import hashlib
import json
from pathlib import Path

from utils.app_paths import get_user_data_dir


def get_state_path(directory_path: Path, base_dir: Path | None = None) -> Path:
    base_dir = base_dir or get_user_data_dir() / 'dataset_state'
    key = hashlib.sha1(str(Path(directory_path).resolve()).encode(
        'utf-8')).hexdigest()[:16]
    return base_dir / f'{key}.json'


def load_completed(directory_path: Path,
                   base_dir: Path | None = None) -> set[str]:
    """Paths (relative to the folder, with forward slashes) of completed
    images."""
    path = get_state_path(directory_path, base_dir)
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return set()
    completed = data.get('completed', [])
    return {str(item) for item in completed if isinstance(item, str)}


def save_completed(directory_path: Path, completed: set[str],
                   base_dir: Path | None = None):
    path = get_state_path(directory_path, base_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            'directory': str(Path(directory_path).resolve()),
            'completed': sorted(completed)}, indent=1), encoding='utf-8')
    except OSError:
        pass


def relative_key(directory_path: Path, image_path: Path) -> str:
    try:
        relative = Path(image_path).resolve().relative_to(
            Path(directory_path).resolve())
    except ValueError:
        relative = Path(image_path).name
    return relative.as_posix()
