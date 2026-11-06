"""Вкладка "Розділення PDF": пакетне розділення на частини."""
import os
import threading

from PyQt5 import QtCore, QtWidgets

from ui_batch_extras import BatchExtras
from .split_core import (MODE_BOOKMARKS, MODE_EACH, MODE_EVERY_N, MODE_RANGES,
                         split_pdf)

SETTINGS_ORG = "pdf-ocr-translator"
SETTINGS_APP = "PDFManager"


class _Signals(QtCore.QObject):
    log = QtCore.pyqtSignal(str)
    progress = QtCore.pyqtSignal(int)
    finished = QtCore.pyqtSignal(str)


class _DropList(QtWidgets.QListWidget):
    filesDropped = QtCore.pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    dragMoveEvent = dragEnterEvent

    def dropEvent(self, e):
        self.filesDropped.emit(
            [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()])
        e.acceptProposedAction()


class PDFSplitWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.paths = []
        self._cancel = threading.Event()
        self._thread = None
        self.signals = _Signals()
        self.signals.log.connect(lambda m: self.log_view.appendPlainText(m))
        self.signals.finished.connect(self._on_finished)
        self.settings = QtCore.QSettings(SETTINGS_ORG, SETTINGS_APP)
        self.last_dir = self.settings.value("last_dir", os.path.expanduser("~"))
        self._build_ui()
        self.signals.progress.connect(self.progress.setValue)

    def _build_ui(self):
        left = QtWidgets.QGroupBox("PDF-файли")
        ll = QtWidgets.QVBoxLayout(left)
        self.list_widget = _DropList()
        self.list_widget.filesDropped.connect(self.add_files)
        ll.addWidget(self.list_widget, 1)
        row = QtWidgets.QHBoxLayout()
        btn_add = QtWidgets.QPushButton("Додати файли...")
        btn_add.clicked.connect(self.add_files_dialog)
        self.extras = BatchExtras(self, "split", self.add_files)
        btn_clear = QtWidgets.QPushButton("Очистити список")
        btn_clear.clicked.connect(self.clear_list)
        row.addWidget(btn_add)
        row.addWidget(self.extras.recent_button)
        row.addWidget(btn_clear)
        ll.addLayout(row)
        hint = QtWidgets.QLabel("Можна перетягнути файли у список.")
        hint.setObjectName("MutedLabel")
        ll.addWidget(hint)

        right = QtWidgets.QVBoxLayout()
        grp = QtWidgets.QGroupBox("Як розділити")
        gl = QtWidgets.QVBoxLayout(grp)
        self.radio_each = QtWidgets.QRadioButton("Кожна сторінка окремим файлом")
        self.radio_n = QtWidgets.QRadioButton("По N сторінок")
        self.radio_ranges = QtWidgets.QRadioButton("За діапазонами сторінок")
        self.radio_marks = QtWidgets.QRadioButton("За закладками верхнього рівня")
        self.radio_each.setChecked(True)
        self.spin_n = QtWidgets.QSpinBox()
        self.spin_n.setRange(1, 10000)
        self.spin_n.setValue(self.settings.value("split/n", 10, type=int))
        self.edit_ranges = QtWidgets.QLineEdit(
            self.settings.value("split/ranges", ""))
        self.edit_ranges.setPlaceholderText("наприклад: 1-3, 5, 7-9")
        gl.addWidget(self.radio_each)
        n_row = QtWidgets.QHBoxLayout()
        n_row.addWidget(self.radio_n)
        n_row.addWidget(self.spin_n)
        n_row.addStretch(1)
        gl.addLayout(n_row)
        gl.addWidget(self.radio_ranges)
        gl.addWidget(self.edit_ranges)
        gl.addWidget(self.radio_marks)
        for r in (self.radio_each, self.radio_n, self.radio_ranges, self.radio_marks):
            r.toggled.connect(self._update_enabled)
        right.addWidget(grp)

        grp_res = QtWidgets.QGroupBox("Результат")
        rl = QtWidgets.QVBoxLayout(grp_res)
        rl.addWidget(self.extras.skip_checkbox)
        right.addWidget(grp_res)

        self.status_label = QtWidgets.QLabel("Готово")
        self.status_label.setObjectName("MutedLabel")
        right.addWidget(self.status_label)
        self.progress = QtWidgets.QProgressBar()
        right.addWidget(self.progress)

        actions = QtWidgets.QHBoxLayout()
        self.btn_start = QtWidgets.QPushButton("Розділити")
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

        self.log_view = QtWidgets.QPlainTextEdit()
        self.log_view.setReadOnly(True)
        grp_log = QtWidgets.QGroupBox("Журнал")
        QtWidgets.QVBoxLayout(grp_log).addWidget(self.log_view)
        right.addWidget(grp_log, 1)

        right_w = QtWidgets.QWidget()
        right_w.setLayout(right)
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right_w)
        splitter.setSizes([520, 560])
        main = QtWidgets.QVBoxLayout(self)
        main.setContentsMargins(4, 4, 4, 4)
        main.addWidget(splitter)
        self._update_enabled()

    def _update_enabled(self, *_):
        self.spin_n.setEnabled(self.radio_n.isChecked())
        self.edit_ranges.setEnabled(self.radio_ranges.isChecked())

    # ---------------------------------------------------------- список --
    def add_files_dialog(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Виберіть PDF", self.last_dir, "PDF (*.pdf)")
        if paths:
            self.last_dir = os.path.dirname(paths[0])
            self.settings.setValue("last_dir", self.last_dir)
            self.add_files(paths)

    def add_files(self, paths):
        for p in paths:
            if os.path.isfile(p) and p.lower().endswith(".pdf") \
                    and p not in self.paths:
                self.paths.append(p)
                self.list_widget.addItem(os.path.basename(p))
                self.extras.remember([p])

    def clear_list(self):
        self.paths.clear()
        self.list_widget.clear()

    # ------------------------------------------------------------ запуск --
    def _mode(self):
        if self.radio_n.isChecked():
            return MODE_EVERY_N, self.spin_n.value()
        if self.radio_ranges.isChecked():
            return MODE_RANGES, self.edit_ranges.text()
        if self.radio_marks.isChecked():
            return MODE_BOOKMARKS, None
        return MODE_EACH, None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        if not self.paths:
            QtWidgets.QMessageBox.warning(self, "Немає файлів",
                                          "Додайте хоча б один PDF.")
            return
        mode, param = self._mode()
        if mode == MODE_RANGES and not self.edit_ranges.text().strip():
            QtWidgets.QMessageBox.warning(
                self, "Немає діапазонів", "Вкажіть діапазони, наприклад: 1-3, 5.")
            return
        out_dir = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Куди зберегти частини", self.last_dir)
        if not out_dir:
            return
        self.last_dir = out_dir
        self.settings.setValue("last_dir", out_dir)
        self.settings.setValue("split/n", self.spin_n.value())
        self.settings.setValue("split/ranges", self.edit_ranges.text())
        self.extras.set_output_dir(out_dir)
        self.log_view.clear()
        self._cancel.clear()
        self.progress.setMaximum(len(self.paths))
        self.progress.setValue(0)
        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.status_label.setText("Розділення...")
        self._thread = threading.Thread(
            target=self._run,
            args=(list(self.paths), out_dir, mode, param,
                  self.extras.skip_existing),
            daemon=True)
        self._thread.start()

    def _run(self, paths, out_dir, mode, param, skip):
        done = skipped = failed = parts = 0
        for i, src in enumerate(paths, 1):
            if self._cancel.is_set():
                self.signals.log.emit("Скасовано.")
                break
            name = os.path.basename(src)
            try:
                created, was_skipped = split_pdf(
                    src, out_dir, mode, param, skip_existing=skip,
                    cancel_event=self._cancel)
                if was_skipped:
                    skipped += 1
                    self.signals.log.emit(f"Пропущено (вже є): {name}")
                else:
                    done += 1
                    parts += len(created)
                    self.signals.log.emit(f"{name} -> {len(created)} файл(ів)")
            except Exception as e:
                failed += 1
                self.signals.log.emit(f"[ПОМИЛКА] {name}: {e}")
            self.signals.progress.emit(i)
        summary = f"Готово: оброблено {done}, створено файлів {parts}"
        if skipped:
            summary += f", пропущено {skipped}"
        if failed:
            summary += f", помилок {failed}"
        self.signals.finished.emit(summary)

    def _on_finished(self, summary):
        self.btn_start.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.status_label.setText(summary)
        self.log_view.appendPlainText("=== " + summary + " ===")
