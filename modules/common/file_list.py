"""Список файлів із підтримкою перетягування (drag-and-drop)."""
from PyQt5 import QtWidgets


class DropFileList(QtWidgets.QListWidget):
    """owner.append_files(list[str]) викликається для файлів з потрібним
    розширенням, скинутих на список."""

    def __init__(self, owner, extensions=(".pdf",), extended=False, parent=None):
        super().__init__(parent)
        self.owner = owner
        self.extensions = tuple(e.lower() for e in extensions)
        self.setAcceptDrops(True)
        if extended:
            self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            files = [u.toLocalFile() for u in event.mimeData().urls()
                     if u.toLocalFile().lower().endswith(self.extensions)]
            if files:
                self.owner.append_files(files)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)
