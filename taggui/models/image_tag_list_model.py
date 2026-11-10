from PySide6.QtCore import QMimeData, QModelIndex, QStringListModel, Qt

from utils.tag_colors import get_tag_colors


class ImageTagListModel(QStringListModel):
    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DecorationRole:
            # The tag's category color, if it has one.
            return get_tag_colors().icon_for(
                super().data(index, Qt.ItemDataRole.EditRole))
        return super().data(index, role)

    def dropMimeData(self, data: QMimeData, action: Qt.DropAction, row: int,
                     column: int, parent: QModelIndex) -> bool:
        # Overriding this method like this somehow disables dropping a tag onto
        # another tag, preventing tags from being overwritten.
        return False
