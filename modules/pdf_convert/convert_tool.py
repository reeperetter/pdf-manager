"""
Універсальний пакетний інструмент конвертації: список файлів, "Нещодавні",
"Пропускати файли, для яких уже є результат", вибір папки при натисканні
кнопки запуску, прогрес, журнал і "Відкрити папку результатів".

Конкретна конвертація описується ConvertSpec (які файли приймає, яке
розширення створює, яка функція з converters.py її виконує, які додаткові
параметри показати).
"""
import os
import threading
from dataclasses import dataclass, field

from PyQt5 import QtCore, QtWidgets
from modules.common.settings import SETTINGS_APP, SETTINGS_ORG

from ui_batch_extras import BatchExtras


@dataclass
class ConvertSpec:
    key: str
    title: str
    in_exts: tuple            # допустимі розширення вхідних файлів
    out_ext: str              # розширення результату (для pdf->img - формат)
    func: callable            # func(src, out_path, **options) -> [paths]
    in_label: str = "Файли"
    multi_output: bool = False   # одна вхідна -> багато файлів (сторінки)
    # (ключ, підпис, [(значення, текст), ...], значення за замовчуванням)
    options: list = field(default_factory=list)


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
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        self.filesDropped.emit(paths)
        e.acceptProposedAction()


class ConvertToolWidget(QtWidgets.QWidget):
    def __init__(self, spec: ConvertSpec, parent=None):
        super().__init__(parent)
        self.spec = spec
        self.paths = []
        self._cancel = threading.Event()
        self._thread = None
        self.signals = _Signals()
        self.signals.log.connect(self._append_log)
        self.signals.progress.connect(self._set_progress)
        self.signals.finished.connect(self._on_finished)
        self.settings = QtCore.QSettings(SETTINGS_ORG, SETTINGS_APP)
        self.last_dir = self.settings.value("last_dir", os.path.expanduser("~"))
        self._build_ui()

    # ------------------------------------------------------------- UI --
    def _build_ui(self):
        exts = " ".join(f"*{e}" for e in self.spec.in_exts)
        self._filter = f"{self.spec.in_label} ({exts})"

        left = QtWidgets.QGroupBox(self.spec.in_label)
        ll = QtWidgets.QVBoxLayout(left)
        self.list_widget = _DropList()
        self.list_widget.filesDropped.connect(self.add_files)
        ll.addWidget(self.list_widget, 1)
        row = QtWidgets.QHBoxLayout()
        btn_add = QtWidgets.QPushButton("Додати файли...")
        btn_add.clicked.connect(self.add_files_dialog)
        self.extras = BatchExtras(self, f"conv_{self.spec.key}", self.add_files,
                                  extensions=self.spec.in_exts)
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
        self.option_widgets = {}
        if self.spec.options:
            grp = QtWidgets.QGroupBox("Параметри")
            gl = QtWidgets.QGridLayout(grp)
            for r, (key, label, choices, default) in enumerate(self.spec.options):
                gl.addWidget(QtWidgets.QLabel(label), r, 0)
                combo = QtWidgets.QComboBox()
                for value, text in choices:
                    combo.addItem(text, value)
                saved = self.settings.value(f"conv_{self.spec.key}/{key}", default)
                idx = combo.findData(type(default)(saved))
                combo.setCurrentIndex(max(idx, 0))
                gl.addWidget(combo, r, 1)
                self.option_widgets[key] = combo
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
        self.btn_start = QtWidgets.QPushButton("Конвертувати")
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
        gll = QtWidgets.QVBoxLayout(grp_log)
        gll.addWidget(self.log_view)
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

    # ---------------------------------------------------------- список --
    def add_files_dialog(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Виберіть файли", self.last_dir, self._filter)
        if paths:
            self.last_dir = os.path.dirname(paths[0])
            self.settings.setValue("last_dir", self.last_dir)
            self.add_files(paths)

    def add_files(self, paths):
        for p in paths:
            if (os.path.isfile(p) and p.lower().endswith(self.spec.in_exts)
                    and p not in self.paths):
                self.paths.append(p)
                self.list_widget.addItem(os.path.basename(p))
                self.extras.remember([p])

    def clear_list(self):
        self.paths.clear()
        self.list_widget.clear()

    # ------------------------------------------------------------ запуск --
    def _options(self):
        return {k: w.currentData() for k, w in self.option_widgets.items()}

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        if not self.paths:
            QtWidgets.QMessageBox.warning(self, "Немає файлів",
                                          "Додайте хоча б один файл.")
            return
        out_dir = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Куди зберегти результат", self.last_dir)
        if not out_dir:
            return
        self.last_dir = out_dir
        self.settings.setValue("last_dir", out_dir)
        opts = self._options()
        for k, v in opts.items():
            self.settings.setValue(f"conv_{self.spec.key}/{k}", v)
        self.extras.set_output_dir(out_dir)
        self.log_view.clear()
        self.progress.setMaximum(len(self.paths))
        self.progress.setValue(0)
        self._cancel.clear()
        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.status_label.setText("Конвертація...")
        skip = self.extras.skip_existing
        self._thread = threading.Thread(
            target=self._run, args=(list(self.paths), out_dir, opts, skip),
            daemon=True)
        self._thread.start()

    def _out_base(self, src, out_dir):
        stem = os.path.splitext(os.path.basename(src))[0]
        return os.path.join(out_dir, stem)

    def _run(self, paths, out_dir, opts, skip):
        done = skipped = failed = 0
        used = set()
        for i, src in enumerate(paths, 1):
            if self._cancel.is_set():
                self.signals.log.emit("Скасовано.")
                break
            name = os.path.basename(src)
            out_ext = opts.get("fmt", self.spec.out_ext)
            base = self._out_base(src, out_dir)
            if self.spec.multi_output:
                first = f"{base}_001.{out_ext}"
                target = base
                exists = os.path.exists(first)
            else:
                target = f"{base}.{out_ext}"
                exists = os.path.exists(target)
            if exists and skip and target not in used:
                skipped += 1
                self.signals.log.emit(f"Пропущено (вже є): {name}")
                self.signals.progress.emit(i)
                continue
            if exists and not skip:
                n = 1
                while True:
                    cand = f"{base}_{n}" if self.spec.multi_output \
                        else f"{base}_{n}.{out_ext}"
                    probe = f"{cand}_001.{out_ext}" \
                        if self.spec.multi_output else cand
                    if not os.path.exists(probe):
                        target = cand
                        break
                    n += 1
            used.add(target)
            self.signals.log.emit(f"{name} ...")
            try:
                created = self.spec.func(src, target, **opts)
                done += 1
                self.signals.log.emit(
                    f"  -> {len(created)} файл(ів)" if len(created) > 1
                    else f"  -> {os.path.basename(created[0])}")
            except Exception as e:
                failed += 1
                self.signals.log.emit(f"[ПОМИЛКА] {name}: {e}")
            self.signals.progress.emit(i)
        summary = f"Готово: {done}"
        if skipped:
            summary += f", пропущено: {skipped}"
        if failed:
            summary += f", помилок: {failed}"
        self.signals.finished.emit(summary)

    # ------------------------------------------------------------ слоти --
    def _append_log(self, msg):
        self.log_view.appendPlainText(msg)

    def _set_progress(self, v):
        self.progress.setValue(v)

    def _on_finished(self, summary):
        self.btn_start.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.status_label.setText(summary)
        self.log_view.appendPlainText("=== " + summary + " ===")
