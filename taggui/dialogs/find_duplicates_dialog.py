"""Find Duplicate Images (ported from TagBench). Groups look-alike images,
lets you pick which to keep, optionally copies the dropped images' tags onto
the kept ones, and moves the rest (and their captions) to the trash."""
from pathlib import Path

from PySide6.QtCore import QFile, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QImageReader, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog, QFrame,
                               QHBoxLayout, QLabel, QMessageBox, QProgressBar,
                               QPushButton, QScrollArea, QSlider, QToolButton,
                               QVBoxLayout, QWidget)

from models.image_list_model import ImageListModel
from utils.duplicates import (DEFAULT_STRICTNESS, MAX_STRICTNESS,
                              Fingerprint, apart, default_keeper,
                              fingerprint, group_duplicates, group_id,
                              plan_removal)
from utils.flow_layout import FlowLayout
from utils.image import Image
from utils.utils import get_confirmation_dialog_reply, pluralize

THUMBNAIL_SIZE = 140
CARD_WIDTH = THUMBNAIL_SIZE + 70


def load_thumbnail(image: Image) -> QIcon:
    reader = QImageReader(str(image.path))
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and size.width() and size.height():
        reader.setScaledSize(size.scaled(QSize(THUMBNAIL_SIZE * 2,
                                               THUMBNAIL_SIZE * 2),
                                         Qt.AspectRatioMode.KeepAspectRatio))
    return QIcon(QPixmap.fromImageReader(reader))


class DuplicateCard(QToolButton):
    def __init__(self, image: Image, icon: QIcon):
        super().__init__()
        self.image = image
        self.setCheckable(True)
        self.setIcon(icon)
        self.setIconSize(QSize(THUMBNAIL_SIZE, THUMBNAIL_SIZE))
        self.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        self.setFixedWidth(CARD_WIDTH)
        font = self.font()
        font.setPointSizeF(max(8.0, font.pointSizeF() * 0.8))
        self.setFont(font)
        self.setToolTip(str(image.path))
        self.setStyleSheet(
            'QToolButton { border: 2px solid palette(mid); border-radius: 8px;'
            ' padding: 6px; }'
            'QToolButton:checked { border: 3px solid #2e7d32; '
            'background: rgba(46, 125, 50, 50); }')

    def set_status(self, text: str):
        name = self.fontMetrics().elidedText(
            self.image.path.name, Qt.TextElideMode.ElideMiddle,
            CARD_WIDTH - 20)
        self.setText(f'{name}\n{text}')


class FindDuplicatesDialog(QDialog):
    directory_reload_requested = Signal()

    def __init__(self, parent, image_list_model: ImageListModel):
        super().__init__(parent)
        self.image_list_model = image_list_model
        self.images: list[Image] = list(image_list_model.images)
        self.by_path = {image.path: image for image in self.images}
        self.fingerprints: list[Fingerprint] = []
        self.by_key: dict[Path, Fingerprint] = {}
        self.groups: list[list[Path]] = []
        # Group id -> the paths chosen to keep.
        self.keep: dict[tuple, list[Path]] = {}
        self.icons: dict[Path, QIcon] = {}
        self.is_canceled = False
        self.dropped_count = 0

        self.setWindowTitle('Find Duplicate Images')
        self.resize(900, 640)
        layout = QVBoxLayout(self)
        self.progress_bar = QProgressBar()
        self.progress_bar.setFormat('Reading images... %v / %m')
        layout.addWidget(self.progress_bar)

        strictness_layout = QHBoxLayout()
        self.strictness_label = QLabel()
        self.strictness_slider = QSlider(Qt.Orientation.Horizontal)
        self.strictness_slider.setRange(0, MAX_STRICTNESS)
        self.strictness_slider.setValue(DEFAULT_STRICTNESS)
        self.strictness_slider.setToolTip(
            '0 finds only images that look identical. Higher values also '
            'group images that are more different.')
        strictness_layout.addWidget(self.strictness_label)
        strictness_layout.addWidget(self.strictness_slider, stretch=1)
        strictness_layout.addWidget(QLabel('More lenient'))
        layout.addLayout(strictness_layout)
        self.copy_tags_check_box = QCheckBox(
            "Copy the dropped images' tags onto every image you keep")
        self.copy_tags_check_box.setChecked(True)
        layout.addWidget(self.copy_tags_check_box)
        self.summary_label = QLabel()
        layout.addWidget(self.summary_label)
        hint = QLabel('Click a picture to keep it too. A group always keeps '
                      'at least one. Green pictures are kept.')
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.groups_widget = QWidget()
        self.groups_layout = QVBoxLayout(self.groups_widget)
        self.groups_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setWidget(self.groups_widget)
        layout.addWidget(scroll_area, stretch=1)

        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch()
        self.drop_button = QPushButton('Drop the Others')
        self.drop_button.setEnabled(False)
        self.drop_button.clicked.connect(self.drop_others)
        close_button = QPushButton('Close')
        close_button.clicked.connect(self.reject)
        buttons_layout.addWidget(self.drop_button)
        buttons_layout.addWidget(close_button)
        layout.addLayout(buttons_layout)

        self.strictness_slider.valueChanged.connect(self.regroup)
        self.update_strictness_label()

    def reject(self):
        self.is_canceled = True
        super().reject()

    def update_strictness_label(self):
        value = self.strictness_slider.value()
        self.strictness_label.setText(
            f'Strictness {value}' + (' (looks identical)' if value == 0
                                     else ''))

    def compute_fingerprints(self) -> bool:
        """Fingerprint every image, keeping the dialog responsive. Returns
        False if the dialog was closed first."""
        self.progress_bar.setRange(0, len(self.images))
        self.progress_bar.show()
        for i, image in enumerate(self.images):
            if self.is_canceled:
                return False
            try:
                self.fingerprints.append(fingerprint(image.path))
            except OSError:
                continue
            if i % 4 == 0:
                self.progress_bar.setValue(i + 1)
                QApplication.processEvents()
        self.by_key = {fp.key: fp for fp in self.fingerprints}
        self.progress_bar.hide()
        return True

    def tag_counts(self) -> dict[Path, int]:
        return {image.path: len(image.tags) for image in self.images}

    def keepers_of(self, group: list[Path]) -> list[Path]:
        chosen = [key for key in self.keep.get(group_id(group), [])
                  if key in group]
        return chosen or [default_keeper(group, self.tag_counts())]

    def regroup(self):
        self.update_strictness_label()
        self.groups = group_duplicates(self.fingerprints,
                                       self.strictness_slider.value())
        self.render_groups()

    def icon_for(self, image: Image) -> QIcon:
        if image.path not in self.icons:
            self.icons[image.path] = load_thumbnail(image)
        return self.icons[image.path]

    def render_groups(self):
        while self.groups_layout.count():
            item = self.groups_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        group_count = len(self.groups)
        image_count = sum(len(group) for group in self.groups)
        if group_count:
            self.summary_label.setText(
                f'{group_count} {pluralize("group", group_count)} of '
                f'look-alike images ({image_count} images).')
        else:
            self.summary_label.setText('No duplicates at this strictness.')
        self.drop_button.setEnabled(bool(group_count))
        for group in self.groups:
            frame = QFrame()
            frame.setFrameShape(QFrame.Shape.StyledPanel)
            flow = FlowLayout(frame, spacing=8)
            flow.setContentsMargins(8, 8, 8, 8)
            keepers = self.keepers_of(group)
            for key in group:
                image = self.by_path.get(key)
                if image is None:
                    continue
                card = DuplicateCard(image, self.icon_for(image))
                is_kept = key in keepers
                card.setChecked(is_kept)
                card.set_status('Keep' if is_kept
                                else self.difference_text(keepers, key))
                card.clicked.connect(
                    lambda _=False, group_=group, key_=key:
                    self.toggle_keep(group_, key_))
                flow.addWidget(card)
            self.groups_layout.addWidget(frame)

    def difference_text(self, keepers: list[Path], key: Path) -> str:
        fp = self.by_key.get(key)
        if fp is None:
            return ''
        distances = []
        for keeper in keepers:
            other = self.by_key.get(keeper)
            if other is None:
                continue
            if other.exact == fp.exact:
                return 'Identical file'
            distances.append(apart(other, fp))
        return f'Differs by {min(distances)}' if distances else ''

    def toggle_keep(self, group: list[Path], key: Path):
        keepers = list(self.keepers_of(group))
        if key in keepers:
            if len(keepers) > 1:
                keepers.remove(key)
        else:
            keepers.append(key)
        self.keep[group_id(group)] = keepers
        self.render_groups()

    def drop_others(self):
        drop, copies = plan_removal(self.groups, self.keep, self.tag_counts(),
                                    self.copy_tags_check_box.isChecked())
        if not drop:
            return
        reply = get_confirmation_dialog_reply(
            title='Drop Duplicate Images',
            question=f'Move {len(drop)} duplicate '
                     f'{pluralize("image", len(drop))} and '
                     f'{"its" if len(drop) == 1 else "their"} '
                     f'{pluralize("caption", len(drop))} to the trash?')
        if reply != QMessageBox.StandardButton.Yes:
            return
        if copies:
            self.image_list_model.merge_tags_into(copies)
        failed = []
        for path in drop:
            if not QFile(str(path)).moveToTrash():
                failed.append(path)
                continue
            caption_path = path.with_suffix('.txt')
            caption_file = QFile(str(caption_path))
            if caption_file.exists() and not caption_file.moveToTrash():
                failed.append(caption_path)
        if failed:
            QMessageBox.critical(
                self, 'Error', 'Failed to move to the trash:\n'
                + '\n'.join(str(path) for path in failed[:20]))
        self.dropped_count = len(drop) - len(
            [path for path in failed if path.suffix != '.txt'])
        self.directory_reload_requested.emit()
        self.accept()

    def exec(self) -> int:
        self.show()
        QApplication.processEvents()
        if not self.compute_fingerprints():
            return QDialog.DialogCode.Rejected
        self.regroup()
        return super().exec()
