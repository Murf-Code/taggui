"""Per-user data folders that work on Windows, Linux and macOS."""
import os
import shutil
import subprocess
import sys
from pathlib import Path


def get_user_data_dir() -> Path:
    """TagGUI's per-user data folder.

    Windows: %LOCALAPPDATA%\\taggui
    macOS:   ~/Library/Application Support/taggui
    Linux:   $XDG_DATA_HOME/taggui, or ~/.local/share/taggui
    """
    if sys.platform == 'win32':
        base = os.environ.get('LOCALAPPDATA')
        base = Path(base) if base else Path.home() / 'AppData' / 'Local'
    elif sys.platform == 'darwin':
        base = Path.home() / 'Library' / 'Application Support'
    else:
        base = os.environ.get('XDG_DATA_HOME')
        base = Path(base) if base else Path.home() / '.local' / 'share'
    return base / 'taggui'


def get_models_dir() -> Path:
    """Where downloaded models (big-lama, JTP-3) are kept."""
    override = os.environ.get('TAGGUI_MODELS_DIR')
    if override:
        return Path(override)
    return get_user_data_dir() / 'models'


def show_in_file_manager(path: Path) -> bool:
    """Open the system file manager with `path` selected (or its folder
    opened where selecting isn't supported). Returns False if nothing could
    be launched, so the caller can fall back to QDesktopServices."""
    path = Path(path).resolve()
    try:
        if sys.platform == 'win32':
            # Explorer with the file selected.
            subprocess.Popen(f'explorer /select,"{path}"')
            return True
        if sys.platform == 'darwin':
            subprocess.Popen(['open', '-R', str(path)])
            return True
        # Linux/BSD: ask the desktop's file manager (Nautilus, Dolphin, Nemo,
        # Thunar, Caja...) to select the file over D-Bus.
        if shutil.which('dbus-send'):
            result = subprocess.run(
                ['dbus-send', '--session', '--print-reply',
                 '--dest=org.freedesktop.FileManager1',
                 '--type=method_call', '/org/freedesktop/FileManager1',
                 'org.freedesktop.FileManager1.ShowItems',
                 f'array:string:{path.as_uri()}', 'string:'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=5)
            if result.returncode == 0:
                return True
        if shutil.which('xdg-open'):
            subprocess.Popen(['xdg-open', str(path.parent)],
                             stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
            return True
    except (OSError, subprocess.SubprocessError):
        pass
    return False
