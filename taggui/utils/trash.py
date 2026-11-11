"""Move images and their captions to the trash on a worker thread, so a
big delete does not freeze the window."""
from pathlib import Path

from PySide6.QtCore import QEventLoop, QFile, QThread, Qt, Signal
from PySide6.QtWidgets import QProgressDialog


class TrashThread(QThread):
    progress = Signal(int)

    def __init__(self, image_paths: list[Path],
                 keep_caption_if_image_fails: bool = False):
        super().__init__()
        self.image_paths = image_paths
        self.keep_caption_if_image_fails = keep_caption_if_image_fails
        self.trashed: list[Path] = []
        # (path, is_caption) of every file that could not be trashed, in
        # order.
        self.failed: list[tuple[Path, bool]] = []

    def run(self):
        for i, image_path in enumerate(self.image_paths):
            if QFile(str(image_path)).moveToTrash():
                self.trashed.append(image_path)
            else:
                self.failed.append((image_path, False))
                if self.keep_caption_if_image_fails:
                    self.progress.emit(i + 1)
                    continue
            caption_path = image_path.with_suffix('.txt')
            caption_file = QFile(str(caption_path))
            if caption_file.exists() and not caption_file.moveToTrash():
                self.failed.append((caption_path, True))
            self.progress.emit(i + 1)


def move_images_to_trash(parent, image_paths: list[Path],
                         keep_caption_if_image_fails: bool = False
                         ) -> TrashThread:
    """Trash the images and their captions, showing progress if it takes a
    while. Returns the finished thread with `trashed` and `failed`."""
    thread = TrashThread(list(image_paths), keep_caption_if_image_fails)
    progress_dialog = QProgressDialog(
        'Moving to the trash...', None, 0, len(thread.image_paths), parent)
    progress_dialog.setWindowTitle('Delete')
    progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
    progress_dialog.setMinimumDuration(400)
    progress_dialog.setAutoClose(False)
    progress_dialog.setAutoReset(False)
    thread.progress.connect(progress_dialog.setValue)
    loop = QEventLoop()
    thread.finished.connect(loop.quit)
    thread.start()
    if not thread.isFinished():
        loop.exec()
    thread.wait()
    progress_dialog.close()
    progress_dialog.deleteLater()
    return thread
