"""Вкладка "Об'єднання PDF": кілька PDF -> один файл у вибраному порядку."""
import os
import threading

from PyQt5 import QtCore, QtWidgets
from modules.common.settings import SETTINGS_APP, SETTINGS_ORG

from ui_batch_extras import BatchExtras
from .merge_core import merge_pdfs, page_count


class _Signals(QtCore.QObject):
    progress = QtCore.pyqtSignal(int, int)
    finished = QtCore.pyqtSignal(bool, str)


class _DropList(QtWidgets.QListWidget):
    filesDropped = QtCore.pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            self.filesDropped.emit(
                [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])
            e.acceptProposedAction()
        else:
            super().dropEvent(e)


class PDFMergeWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel = threading.Event()
        self._thread = None
        self.signals = _Signals()
        self.signals.progress.connect(self._on_progress)
        self.signals.finished.connect(self._on_finished)
        self.settings = QtCore.QSettings(SETTINGS_ORG, SETTINGS_APP)
        self.last_dir = self.settings.value("last_dir", os.path.expanduser("~"))
        self._build_ui()

    # ------------------------------------------------------------- UI --
    def _build_ui(self):
        left = QtWidgets.QGroupBox("PDF-файли (порядок = порядок у результаті)")
        ll = QtWidgets.QVBoxLayout(left)
        self.list_widget = _DropList()
        self.list_widget.filesDropped.connect(self.add_files)
        ll.addWidget(self.list_widget, 1)

        row1 = QtWidgets.QHBoxLayout()
        btn_add = QtWidgets.QPushButton("Додати файли...")
        btn_add.clicked.connect(self.add_files_dialog)
        self.extras = BatchExtras(self, "merge", self.add_files)
        btn_up = QtWidgets.QPushButton("Вгору")
        btn_up.clicked.connect(lambda: self._move(-1))
        btn_down = QtWidgets.QPushButton("Вниз")
        btn_down.clicked.connect(lambda: self._move(1))
        row1.addWidget(btn_add)
        row1.addWidget(self.extras.recent_button)
        row1.addWidget(btn_up)
        row1.addWidget(btn_down)
        ll.addLayout(row1)
        row2 = QtWidgets.QHBoxLayout()
        btn_remove = QtWidgets.QPushButton("Видалити вибране")
        btn_remove.clicked.connect(self.remove_selected)
        btn_clear = QtWidgets.QPushButton("Очистити список")
        btn_clear.clicked.connect(self.list_widget.clear)
        row2.addWidget(btn_remove)
        row2.addWidget(btn_clear)
        ll.addLayout(row2)
        hint = QtWidgets.QLabel(
            "Перетягніть файли у список; змінюйте порядок перетягуванням "
            "рядків або кнопками.")
        hint.setObjectName("MutedLabel")
        hint.setWordWrap(True)
        ll.addWidget(hint)

        right = QtWidgets.QVBoxLayout()
        grp = QtWidgets.QGroupBox("Параметри")
        gl = QtWidgets.QVBoxLayout(grp)
        self.chk_bookmarks = QtWidgets.QCheckBox(
            "Додати закладки з назв файлів")
        self.chk_bookmarks.setChecked(
            self.settings.value("merge/bookmarks", True, type=bool))
        gl.addWidget(self.chk_bookmarks)
        right.addWidget(grp)

        self.status_label = QtWidgets.QLabel("Готово")
        self.status_label.setObjectName("MutedLabel")
        right.addWidget(self.status_label)
        self.progress = QtWidgets.QProgressBar()
        right.addWidget(self.progress)

        actions = QtWidgets.QHBoxLayout()
        self.btn_start = QtWidgets.QPushButton("Об'єднати")
        self.btn_start.setObjectName("BtnPrimary")
        self.btn_start.clicked.connect(self.start)
        self.btn_cancel = QtWidgets.QPushButton("Скасувати")
        self.btn_cancel.setObjectName("BtnDanger")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel.set)
        actions.addWidget(self.btn_start, 2)
        actions.addWidget(self.btn_cancel, 1)
        actions.addWidget(self.extras.open_button, 1)
        right.addLayout(actions)
        right.addStretch(1)

        right_w = QtWidgets.QWidget()
        right_w.setLayout(right)
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right_w)
        splitter.setSizes([620, 460])
        main = QtWidgets.QVBoxLayout(self)
        main.setContentsMargins(4, 4, 4, 4)
        main.addWidget(splitter)

    # ---------------------------------------------------------- список --
    def paths(self):
        return [self.list_widget.item(i).data(QtCore.Qt.UserRole)
                for i in range(self.list_widget.count())]

    def add_files_dialog(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Виберіть PDF", self.last_dir, "PDF (*.pdf)")
        if paths:
            self.last_dir = os.path.dirname(paths[0])
            self.settings.setValue("last_dir", self.last_dir)
            self.add_files(paths)

    def add_files(self, paths):
        existing = set(self.paths())
        for p in paths:
            if not (os.path.isfile(p) and p.lower().endswith(".pdf")) \
                    or p in existing:
                continue
            try:
                label = f"{os.path.basename(p)}  ({page_count(p)} стор.)"
            except RuntimeError as e:
                label = f"{os.path.basename(p)}  [{e}]"
            item = QtWidgets.QListWidgetItem(label)
            item.setData(QtCore.Qt.UserRole, p)
            item.setToolTip(p)
            self.list_widget.addItem(item)
            existing.add(p)
            self.extras.remember([p])

    def remove_selected(self):
        for item in self.list_widget.selectedItems():
            self.list_widget.takeItem(self.list_widget.row(item))

    def _move(self, delta):
        rows = sorted((self.list_widget.row(i)
                       for i in self.list_widget.selectedItems()),
                      reverse=delta > 0)
        for row in rows:
            new = row + delta
            if 0 <= new < self.list_widget.count():
                item = self.list_widget.takeItem(row)
                self.list_widget.insertItem(new, item)
                item.setSelected(True)

    # ------------------------------------------------------------ запуск --
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        paths = self.paths()
        if len(paths) < 2:
            QtWidgets.QMessageBox.warning(
                self, "Замало файлів", "Додайте щонайменше два PDF-файли.")
            return
        default = os.path.join(
            self.last_dir,
            os.path.splitext(os.path.basename(paths[0]))[0] + "_merged.pdf")
        out_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Зберегти об'єднаний PDF", default, "PDF (*.pdf)")
        if not out_path:
            return
        if not out_path.lower().endswith(".pdf"):
            out_path += ".pdf"
        if out_path in paths:
            QtWidgets.QMessageBox.warning(
                self, "Той самий файл",
                "Результат не може збігатися з одним із вхідних файлів.")
            return
        self.last_dir = os.path.dirname(out_path)
        self.settings.setValue("last_dir", self.last_dir)
        bookmarks = self.chk_bookmarks.isChecked()
        self.settings.setValue("merge/bookmarks", bookmarks)
        self.extras.set_output_dir(self.last_dir)
        self._out_path = out_path
        self._cancel.clear()
        self.progress.setMaximum(len(paths))
        self.progress.setValue(0)
        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.status_label.setText("Об'єднання...")
        self._thread = threading.Thread(
            target=self._run, args=(paths, out_path, bookmarks), daemon=True)
        self._thread.start()

    def _run(self, paths, out_path, bookmarks):
        try:
            pages = merge_pdfs(
                paths, out_path, bookmarks=bookmarks,
                progress_cb=lambda i, n: self.signals.progress.emit(i, n),
                cancel_event=self._cancel)
            self.signals.finished.emit(
                True, f"Готово: {len(paths)} файлів, {pages} стор. → "
                      f"{os.path.basename(out_path)}")
        except Exception as e:
            if os.path.exists(out_path) and "Скасовано" in str(e):
                pass
            self.signals.finished.emit(False, str(e))

    def _on_progress(self, i, n):
        self.progress.setMaximum(n)
        self.progress.setValue(i)

    def _on_finished(self, ok, message):
        self.btn_start.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.status_label.setText(message)
        if not ok:
            QtWidgets.QMessageBox.warning(self, "Не вдалося об'єднати", message)
