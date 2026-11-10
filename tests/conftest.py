import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
TAGGUI_DIR = Path(__file__).resolve().parent.parent / 'taggui'
sys.path.insert(0, str(TAGGUI_DIR))


@pytest.fixture(scope='session')
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Keep QSettings and the user data folder out of the real home."""
    from PySide6.QtCore import QSettings
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat,
                      QSettings.Scope.UserScope, str(tmp_path / 'settings'))
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'data'))
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'data'))
    import utils.tag_colors as tag_colors
    tag_colors._tag_colors = None
    yield
