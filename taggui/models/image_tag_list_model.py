from PySide6.QtCore import QMimeData, QModelIndex, QStringListModel, Qt

from utils.tag_colors import get_tag_colors, is_dark_background


class ImageTagListModel(QStringListModel):
    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DecorationRole:
            # The tag's category or group color.
            return get_tag_colors().icon_for(
                super().data(index, Qt.ItemDataRole.EditRole))
        if role == Qt.ItemDataRole.ForegroundRole:
            return get_tag_colors().text_color_for(
                super().data(index, Qt.ItemDataRole.EditRole),
                is_dark_background())
        return super().data(index, role)

    def dropMimeData(self, data: QMimeData, action: Qt.DropAction, row: int,
                     column: int, parent: QModelIndex) -> bool:
        # Overriding this method like this somehow disables dropping a tag onto
        # another tag, preventing tags from being overwritten.
        return False
