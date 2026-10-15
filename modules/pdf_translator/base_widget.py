"""
Спільна основа для вкладок "OCR" та "Переклад PDF".

Раніше обидві функції жили в одному вікні (gui.py) з одним набором
налаштувань і одним полем "Куди зберегти результат", яке треба було
заповнити заздалегідь. Тепер це дві окремі вкладки, а все спільне - список
файлів, вибір "окремий файл на кожен PDF / один спільний файл", вибір місця
збереження ПІСЛЯ натискання кнопки запуску, прогрес, журнал, фоновий потік -
винесено сюди. Конкретні вкладки (ocr_widget.py, translate_widget.py)
додають лише свої налаштування "що створити".
"""
import glob
import html
import os
import threading
import time
import traceback

from PyQt5 import QtCore, QtGui, QtWidgets

from theme import COLORS
from ui_icons import create_vector_icon
from .ocr import _lazy_import_cv2
from .pdf_pipeline import (
    CombinedResult,
    ProcessingCancelled,
    _process_pdf_core,
    process_pdf,
)
from .tesseract_installer import ensure_tesseract_available

SETTINGS_ORG = "pdf-ocr-translator"
SETTINGS_APP = "PDFManager"


class PdfDropListWidget(QtWidgets.QListWidget):
    """Список PDF-файлів: drag-and-drop файлів і тек, зміна порядку."""
    filesDropped = QtCore.pyqtSignal(list)
    reordered = QtCore.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)

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
        if not event.mimeData().hasUrls():
            super().dropEvent(event)
            self.reordered.emit()
            return
        pdf_paths = []
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if not local:
                continue
            if os.path.isdir(local):
                pdf_paths.extend(sorted(glob.glob(os.path.join(local, "*.pdf"))))
            elif local.lower().endswith(".pdf"):
                pdf_paths.append(local)
        if pdf_paths:
            self.filesDropped.emit(pdf_paths)
        event.acceptProposedAction()


class WorkerSignals(QtCore.QObject):
    log = QtCore.pyqtSignal(str)
    progress = QtCore.pyqtSignal(int)
    status = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()
    page_progress = QtCore.pyqtSignal(int, int)


class PdfBatchToolBase(QtWidgets.QWidget):
    """Базова вкладка пакетної обробки PDF (OCR / переклад).

    Підклас задає:
      SETTINGS_PREFIX     - префікс ключів QSettings (у кожної вкладки свої);
      COMMON_GROUP_TITLE  - заголовок блоку мови/DPI/шрифту;
      EXPORT_ORIGINAL_TEXT - чи є текстовий файл "оригінальним" текстом
                            (OCR) чи перекладом (вкладка перекладу);
      build_task_group()  - блок "Що створити";
      collect_task_options() -> {"make_searchable":bool,"translate_targets":list}
                            або None (якщо показано повідомлення про помилку);
      combined_default_name(first_path) - ім'я за замовчуванням для
                            спільного файлу;
      load_task_settings(s) / save_task_settings(s).
    """

    SETTINGS_PREFIX = "tool"
    COMMON_GROUP_TITLE = "Розпізнавання"
    EXPORT_ORIGINAL_TEXT = False

    def __init__(self, parent=None):
        super().__init__(parent)
        self.files = []
        self.cancel_event = threading.Event()
        self.worker_thread = None
        self.last_dir = os.path.expanduser("~")
        self.last_output_dir = None
        self._last_summary = None

        self.settings = QtCore.QSettings(SETTINGS_ORG, SETTINGS_APP)
        self.log_file_path = os.path.join(
            os.path.expanduser("~"), "pdf_ocr_translator.log")
        self._log_file_lock = threading.Lock()

        self.signals = WorkerSignals()
        self.signals.log.connect(self._append_log)
        self.signals.progress.connect(self._set_progress)
        self.signals.status.connect(self._set_status)
        self.signals.finished.connect(self._on_finished)
        self.signals.page_progress.connect(self._set_page_progress)

        self._build_ui()
        self._load_settings()
        app = QtWidgets.QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._save_settings)

    # ------------------------------------------------ хуки підкласів --
    def build_task_group(self, bold):
        raise NotImplementedError

    def collect_task_options(self):
        raise NotImplementedError

    def combined_default_name(self, first_path):
        return os.path.splitext(os.path.basename(first_path))[0] + ".pdf"

    def load_task_settings(self, s):
        pass

    def save_task_settings(self, s):
        pass

    def _key(self, name):
        return f"{self.SETTINGS_PREFIX}/{name}"

    # ----------------------------------------------------------- UI --
    def _build_ui(self):
        root_layout = QtWidgets.QVBoxLayout(self)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(5)

        bold = QtGui.QFont()
        bold.setBold(True)

        columns = QtWidgets.QHBoxLayout()
        columns.setSpacing(8)
        root_layout.addLayout(columns)

        left_col = QtWidgets.QVBoxLayout()
        left_col.setSpacing(5)
        columns.addLayout(left_col, 3)
        right_col = QtWidgets.QVBoxLayout()
        right_col.setSpacing(5)
        columns.addLayout(right_col, 2)

        # ---- Ліва колонка: файли ----
        grp_files = QtWidgets.QGroupBox("Вхідні PDF-файли")
        grp_files.setFont(bold)
        left_col.addWidget(grp_files, 1)
        files_layout = QtWidgets.QHBoxLayout(grp_files)

        self.listbox = PdfDropListWidget()
        self.listbox.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.listbox.setMinimumHeight(180)
        self.listbox.filesDropped.connect(self._add_files_list)
        self.listbox.reordered.connect(self._resync_files_from_listbox)
        files_layout.addWidget(self.listbox, 1)

        btns = QtWidgets.QVBoxLayout()
        btns.setSpacing(4)
        files_layout.addLayout(btns)
        btn_add_files = QtWidgets.QPushButton("Додати файли...")
        btn_add_files.clicked.connect(self.add_files)
        btn_add_folder = QtWidgets.QPushButton("Додати папку...")
        btn_add_folder.clicked.connect(self.add_folder)
        self.btn_recent = QtWidgets.QPushButton("Нещодавні ▾")
        self.recent_menu = QtWidgets.QMenu(self.btn_recent)
        self.recent_menu.aboutToShow.connect(self._populate_recent_menu)
        self.btn_recent.setMenu(self.recent_menu)
        btns.addWidget(btn_add_files)
        btns.addWidget(btn_add_folder)
        btns.addWidget(self.btn_recent)
        btns.addSpacing(6)
        btn_remove = QtWidgets.QPushButton("Видалити вибране")
        btn_remove.clicked.connect(self.remove_selected)
        btn_clear = QtWidgets.QPushButton("Очистити список")
        btn_clear.clicked.connect(self.clear_files)
        btns.addWidget(btn_remove)
        btns.addWidget(btn_clear)
        btns.addStretch(1)

        # ---- Текстові файли окремо від PDF ----
        grp_text = QtWidgets.QGroupBox("Текст окремо від PDF (необов'язково)")
        grp_text.setFont(bold)
        left_col.addWidget(grp_text)
        text_layout = QtWidgets.QGridLayout(grp_text)
        text_layout.setVerticalSpacing(4)

        self.chk_text_docx = QtWidgets.QCheckBox("DOCX")
        self.chk_text_txt = QtWidgets.QCheckBox("TXT")
        text_layout.addWidget(QtWidgets.QLabel("Формат:"), 0, 0)
        fmt_row = QtWidgets.QHBoxLayout()
        fmt_row.addWidget(self.chk_text_docx)
        fmt_row.addWidget(self.chk_text_txt)
        fmt_row.addStretch(1)
        fmt_widget = QtWidgets.QWidget()
        fmt_widget.setLayout(fmt_row)
        text_layout.addWidget(fmt_widget, 0, 1)

        text_layout.addWidget(QtWidgets.QLabel("Файлів:"), 1, 0)
        self.text_split_combo = QtWidgets.QComboBox()
        self.text_split_combo.addItems([
            "Один файл (усі сторінки)", "Окремий файл на кожну сторінку"])
        text_layout.addWidget(self.text_split_combo, 1, 1)
        left_col.addStretch(0)

        # ---- Права колонка ----
        right_col.addWidget(self.build_task_group(bold))

        grp_opts = QtWidgets.QGroupBox(self.COMMON_GROUP_TITLE)
        grp_opts.setFont(bold)
        right_col.addWidget(grp_opts)
        opts_layout = QtWidgets.QGridLayout(grp_opts)
        opts_layout.setVerticalSpacing(4)

        opts_layout.addWidget(QtWidgets.QLabel("Мова оригіналу:"), 0, 0)
        self.src_lang_combo = QtWidgets.QComboBox()
        self.src_lang_combo.addItem("Автовизначення", "auto")
        self.src_lang_combo.addItem("Українська + Англійська (змішаний)", "ukr+eng")
        self.src_lang_combo.addItem("Українська", "ukr")
        self.src_lang_combo.addItem("Англійська", "eng")
        opts_layout.addWidget(self.src_lang_combo, 0, 1, 1, 2)

        opts_layout.addWidget(QtWidgets.QLabel("DPI:"), 1, 0)
        self.dpi_spin = QtWidgets.QSpinBox()
        self.dpi_spin.setRange(150, 600)
        self.dpi_spin.setSingleStep(50)
        self.dpi_spin.setValue(300)
        opts_layout.addWidget(self.dpi_spin, 1, 1, 1, 2)

        opts_layout.addWidget(QtWidgets.QLabel("Шрифт:"), 2, 0)
        self.font_edit = QtWidgets.QLineEdit()
        self.font_edit.setPlaceholderText("типово - вбудований DejaVu Sans")
        opts_layout.addWidget(self.font_edit, 2, 1)
        btn_font = QtWidgets.QPushButton("Огляд...")
        btn_font.clicked.connect(self.choose_font)
        opts_layout.addWidget(btn_font, 2, 2)

        self.chk_dewarp = QtWidgets.QCheckBox("Виправляти викривлення сторінки")
        opts_layout.addWidget(self.chk_dewarp, 3, 0, 1, 3)

        # ---- Результат: окремі файли чи один спільний ----
        grp_mode = QtWidgets.QGroupBox("Результат")
        grp_mode.setFont(bold)
        right_col.addWidget(grp_mode)
        mode_layout = QtWidgets.QVBoxLayout(grp_mode)
        mode_layout.setSpacing(3)
        self.radio_separate = QtWidgets.QRadioButton(
            "Окремий результат для кожного вхідного PDF")
        self.radio_combined = QtWidgets.QRadioButton(
            "Один спільний файл з усіх вхідних PDF")
        self.radio_separate.setChecked(True)
        self.radio_separate.toggled.connect(self._update_mode_hint)
        mode_layout.addWidget(self.radio_separate)
        mode_layout.addWidget(self.radio_combined)
        self.chk_skip_existing = QtWidgets.QCheckBox(
            "Пропускати файли, для яких результат уже є")
        self.chk_skip_existing.setChecked(True)
        mode_layout.addWidget(self.chk_skip_existing)
        # Куди зберегти - питаємо при натисканні кнопки запуску нижче, і
        # одразу відповідним діалогом (папка / ім'я файлу) залежно від
        # вибору тут.
        self.mode_hint = QtWidgets.QLabel()
        self.mode_hint.setObjectName("MutedLabel")
        self.mode_hint.setWordWrap(True)
        mode_layout.addWidget(self.mode_hint)

        # ---- Керування ----
        grp_actions = QtWidgets.QGroupBox("Керування обробкою")
        grp_actions.setFont(bold)
        right_col.addWidget(grp_actions)
        actions_layout = QtWidgets.QVBoxLayout(grp_actions)
        actions_layout.setSpacing(6)

        self.start_btn = QtWidgets.QPushButton("Почати обробку")
        self.start_btn.setIcon(create_vector_icon("play", COLORS["text_on_accent"]))
        self.start_btn.setIconSize(QtCore.QSize(18, 18))
        self.start_btn.setObjectName("BtnPrimary")
        self.start_btn.clicked.connect(self.start_processing)
        actions_layout.addWidget(self.start_btn)

        self.cancel_btn = QtWidgets.QPushButton("Скасувати")
        self.cancel_btn.setIcon(create_vector_icon("stop", COLORS["text_on_accent"]))
        self.cancel_btn.setIconSize(QtCore.QSize(16, 16))
        self.cancel_btn.setObjectName("BtnDanger")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_processing)
        actions_layout.addWidget(self.cancel_btn)

        self.btn_open_out = QtWidgets.QPushButton("Відкрити папку результатів")
        self.btn_open_out.setIcon(create_vector_icon("folder", COLORS["text_on_accent"]))
        self.btn_open_out.setIconSize(QtCore.QSize(18, 18))
        self.btn_open_out.setObjectName("BtnSecondary")
        self.btn_open_out.setEnabled(False)
        self.btn_open_out.clicked.connect(self.open_output_folder)
        actions_layout.addWidget(self.btn_open_out)

        right_col.addStretch(1)

        # ---- Нижні індикатори ----
        status_row = QtWidgets.QHBoxLayout()
        root_layout.addLayout(status_row)
        self.status_label = QtWidgets.QLabel("Готово")
        status_row.addWidget(self.status_label)
        status_row.addStretch(1)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setTextVisible(False)
        root_layout.addWidget(self.progress)

        page_progress_row = QtWidgets.QHBoxLayout()
        root_layout.addLayout(page_progress_row)
        self.page_progress_label = QtWidgets.QLabel("")
        self.page_progress_label.setObjectName("MutedLabel")
        page_progress_row.addWidget(self.page_progress_label)
        self.page_progress = QtWidgets.QProgressBar()
        self.page_progress.setTextVisible(False)
        self.page_progress.setMaximumHeight(8)
        page_progress_row.addWidget(self.page_progress, 1)

        # ---- Журнал ----
        grp_log = QtWidgets.QGroupBox("Журнал")
        grp_log.setFont(bold)
        root_layout.addWidget(grp_log, 1)
        log_layout = QtWidgets.QVBoxLayout(grp_log)
        self.log_text = QtWidgets.QTextBrowser()
        self.log_text.setOpenLinks(False)
        self.log_text.anchorClicked.connect(self._on_log_link_clicked)
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(120)
        log_layout.addWidget(self.log_text)

        self._update_mode_hint()

    def _update_mode_hint(self):
        separate = self.radio_separate.isChecked()
        self.chk_skip_existing.setEnabled(separate)
        if separate:
            self.mode_hint.setText(
                "Після натискання «Почати обробку» програма запитає, у яку "
                "папку зберегти результати - по одному набору файлів на "
                "кожен вхідний PDF.")
        else:
            self.mode_hint.setText(
                "Після натискання «Почати обробку» програма запитає ім'я "
                "файлу для збереження - усі вхідні PDF будуть зібрані в "
                "один (за порядком у списку).")

    # --------------------------------------------- нещодавні файли --
    def _populate_recent_menu(self):
        self.recent_menu.clear()
        recent = self.settings.value("recent_files", [], type=list) or []
        if not recent:
            empty = self.recent_menu.addAction("(порожньо)")
            empty.setEnabled(False)
            return
        for path in recent:
            action = self.recent_menu.addAction(path)
            action.triggered.connect(
                lambda checked=False, p=path: self._add_files_list([p])
                if os.path.isfile(p)
                else QtWidgets.QMessageBox.warning(
                    self, "Файл не знайдено", f"Файла більше немає:\n{p}")
            )

    def _add_recent_file(self, path):
        recent = self.settings.value("recent_files", [], type=list) or []
        recent = [p for p in recent if p != path]
        recent.insert(0, path)
        self.settings.setValue("recent_files", recent[:10])

    # ----------------------------------------------- список файлів --
    def _add_files_list(self, paths):
        added = False
        for p in paths:
            if p not in self.files:
                self.files.append(p)
                self.listbox.addItem(p)
                added = True
                self._add_recent_file(p)
        if paths:
            self.last_dir = os.path.dirname(paths[0])
        return added

    def _resync_files_from_listbox(self):
        self.files = [self.listbox.item(i).text() for i in range(self.listbox.count())]

    def add_files(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Виберіть PDF-файли", self.last_dir, "PDF files (*.pdf)")
        self._add_files_list(paths)

    def add_folder(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Виберіть папку з PDF-файлами", self.last_dir)
        if folder:
            self._add_files_list(sorted(glob.glob(os.path.join(folder, "*.pdf"))))
            self.last_dir = folder

    def remove_selected(self):
        for item in self.listbox.selectedItems():
            index = self.listbox.row(item)
            self.listbox.takeItem(index)
            del self.files[index]

    def clear_files(self):
        self.files.clear()
        self.listbox.clear()

    def choose_font(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Виберіть TTF-шрифт", self.last_dir, "TrueType Font (*.ttf)")
        if path:
            self.font_edit.setText(path)
            self.last_dir = os.path.dirname(path)

    def open_output_folder(self):
        if self.last_output_dir and os.path.isdir(self.last_output_dir):
            QtGui.QDesktopServices.openUrl(
                QtCore.QUrl.fromLocalFile(self.last_output_dir))

    # -------------------------------------------------- налаштування --
    def _load_settings(self):
        s = self.settings
        self.src_lang_combo.setCurrentIndex(int(s.value(self._key("src_lang_index"), 0)))
        self.dpi_spin.setValue(int(s.value(self._key("dpi"), 300)))
        self.font_edit.setText(str(s.value(self._key("font_path"), "")))
        self.chk_skip_existing.setChecked(s.value(self._key("skip_existing"), True, type=bool))
        self.chk_dewarp.setChecked(s.value(self._key("dewarp"), False, type=bool))
        self.chk_text_docx.setChecked(s.value(self._key("text_docx"), False, type=bool))
        self.chk_text_txt.setChecked(s.value(self._key("text_txt"), False, type=bool))
        self.text_split_combo.setCurrentIndex(int(s.value(self._key("text_split_index"), 0)))
        self.radio_combined.setChecked(s.value(self._key("combined"), False, type=bool))
        self.last_dir = str(s.value("last_dir", os.path.expanduser("~")))
        self.load_task_settings(s)

    def _save_settings(self):
        s = self.settings
        s.setValue(self._key("src_lang_index"), self.src_lang_combo.currentIndex())
        s.setValue(self._key("dpi"), self.dpi_spin.value())
        s.setValue(self._key("font_path"), self.font_edit.text().strip())
        s.setValue(self._key("skip_existing"), self.chk_skip_existing.isChecked())
        s.setValue(self._key("dewarp"), self.chk_dewarp.isChecked())
        s.setValue(self._key("text_docx"), self.chk_text_docx.isChecked())
        s.setValue(self._key("text_txt"), self.chk_text_txt.isChecked())
        s.setValue(self._key("text_split_index"), self.text_split_combo.currentIndex())
        s.setValue(self._key("combined"), self.radio_combined.isChecked())
        s.setValue("last_dir", self.last_dir)
        self.save_task_settings(s)

    # --------------------------------------------------- журнал/стан --
    def _append_log(self, msg):
        prefix = "  -> Збережено: "
        if msg.startswith(prefix):
            path = msg[len(prefix):].strip()
            url = QtCore.QUrl.fromLocalFile(path).toString()
            self.log_text.append(f'{prefix}<a href="{url}">{html.escape(path)}</a>')
        else:
            self.log_text.append(html.escape(msg))

    def _on_log_link_clicked(self, url):
        QtGui.QDesktopServices.openUrl(url)

    def _set_progress(self, value):
        self.progress.setValue(value)

    def _set_page_progress(self, done, total):
        self.page_progress.setRange(0, total)
        self.page_progress.setValue(done)
        self.page_progress_label.setText(f"Сторінка: {done}/{total}")

    def _set_status(self, text):
        self.status_label.setText(text)

    def _on_finished(self):
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.page_progress_label.setText("")
        self.page_progress.setValue(0)
        self.btn_open_out.setEnabled(bool(
            self.last_output_dir and os.path.isdir(self.last_output_dir)))
        summary, self._last_summary = self._last_summary, None
        if summary:
            title, text, is_problem = summary
            box = QtWidgets.QMessageBox.warning if is_problem else QtWidgets.QMessageBox.information
            box(self, title, text)

    def log(self, msg):
        with self._log_file_lock:
            try:
                with open(self.log_file_path, "a", encoding="utf-8") as f:
                    ts = time.strftime("%Y-%m-%d %H:%M:%S")
                    f.write(f"[{ts}] {msg}\n")
            except Exception:
                pass
        self.signals.log.emit(msg)

    # ------------------------------------------------------- запуск --
    def start_processing(self):
        if not self.files:
            QtWidgets.QMessageBox.warning(
                self, "Немає файлів", "Спочатку додайте хоча б один PDF-файл.")
            return

        task = self.collect_task_options()
        if task is None:
            return

        export_text_formats = set()
        if self.chk_text_docx.isChecked():
            export_text_formats.add("docx")
        if self.chk_text_txt.isChecked():
            export_text_formats.add("txt")

        if not ensure_tesseract_available(self):
            return

        dewarp = self.chk_dewarp.isChecked()
        if dewarp:
            try:
                _lazy_import_cv2()
            except Exception:
                choice = QtWidgets.QMessageBox.warning(
                    self, "Випрямлення недоступне",
                    "Не вдалося увімкнути випрямлення сторінки.\n\nПродовжити без нього?",
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel,
                )
                if choice != QtWidgets.QMessageBox.Yes:
                    return
                dewarp = False
                self.chk_dewarp.setChecked(False)

        # ---- Куди зберегти: питаємо саме тут, відповідним діалогом ----
        combined = self.radio_combined.isChecked()
        start_dir = self.last_output_dir or self.last_dir
        if combined:
            default_name = self.combined_default_name(self.files[0])
            out_target, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "Зберегти спільний файл як",
                os.path.join(start_dir, default_name), "PDF files (*.pdf)")
            if not out_target:
                return
            if not out_target.lower().endswith(".pdf"):
                out_target += ".pdf"
            out_dir = os.path.dirname(out_target)
        else:
            out_target = QtWidgets.QFileDialog.getExistingDirectory(
                self, "Папка для результатів", start_dir)
            if not out_target:
                return
            out_dir = out_target
        self.last_output_dir = out_dir

        self._save_settings()

        options = dict(
            files=list(self.files),
            combined=combined,
            out_target=out_target,
            dpi=self.dpi_spin.value(),
            font_path=self.font_edit.text().strip() or None,
            source_lang=self.src_lang_combo.currentData(),
            dewarp=dewarp,
            skip_existing=self.chk_skip_existing.isChecked(),
            export_text_formats=export_text_formats,
            export_text_split=self.text_split_combo.currentIndex() == 1,
            glossary=self.glossary_for_run(),
            **task,
        )

        self.cancel_event.clear()
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.btn_open_out.setEnabled(False)
        self.progress.setRange(0, len(options["files"]))
        self.progress.setValue(0)
        self.status_label.setText(f"Обробка: 0/{len(options['files'])}")

        self.worker_thread = threading.Thread(
            target=self._run_worker, args=(options,), daemon=True)
        self.worker_thread.start()

    def glossary_for_run(self):
        return set()

    def cancel_processing(self):
        self.cancel_event.set()
        self.signals.status.emit("Скасування...")

    # ----------------------------------------------- фонова обробка --
    def _expected_outputs(self, path, out_dir, make_searchable, translate_targets):
        base_name = os.path.splitext(os.path.basename(path))[0]
        expected = []
        if make_searchable:
            expected.append(os.path.join(out_dir, f"{base_name}_searchable.pdf"))
        for lang in translate_targets:
            expected.append(os.path.join(out_dir, f"{base_name}_{lang}.pdf"))
        return expected

    def _run_worker(self, o):
        files = o["files"]
        total = len(files)
        make_searchable = o["make_searchable"]
        translate_targets = o["translate_targets"]
        done = 0
        failed = []
        low_conf_report = []
        cancelled = False
        saved_total = []
        combined = None
        core_kwargs = dict(
            dpi=o["dpi"], make_searchable=make_searchable,
            translate_targets=translate_targets, font_path=o["font_path"],
            log_fn=self.log, cancel_event=self.cancel_event,
            glossary=o["glossary"], dewarp=o["dewarp"],
            source_lang=o["source_lang"],
        )
        want_text = bool(o["export_text_formats"])

        try:
            if o["combined"]:
                combined = CombinedResult(
                    make_searchable, translate_targets,
                    export_original_text=self.EXPORT_ORIGINAL_TEXT)

            for path in files:
                if self.cancel_event.is_set():
                    cancelled = True
                    break
                name = os.path.basename(path)

                if not o["combined"] and o["skip_existing"]:
                    expected = self._expected_outputs(
                        path, o["out_target"], make_searchable, translate_targets)
                    if expected and all(os.path.isfile(p) for p in expected):
                        self.log(f"=== Пропущено (уже є): {name} ===")
                        done += 1
                        self.signals.progress.emit(done)
                        self.signals.status.emit(f"Обробка: {done}/{total}")
                        continue

                def page_progress_cb(page_num, n_pages):
                    self.signals.page_progress.emit(page_num, n_pages)
                    time.sleep(0.001)

                try:
                    self.log(f"=== Обробка: {name} ===")
                    if o["combined"]:
                        res = _process_pdf_core(
                            path, collect_text=want_text,
                            page_progress_fn=page_progress_cb, **core_kwargs)
                        low = list(res.low_confidence_pages)
                        combined.add(res)
                    else:
                        saved, low = process_pdf(
                            path, o["out_target"],
                            export_text_formats=o["export_text_formats"],
                            export_text_split_pages=o["export_text_split"],
                            export_original_text=self.EXPORT_ORIGINAL_TEXT,
                            page_progress_fn=page_progress_cb, **core_kwargs)
                        for s in saved:
                            self.log(f"  -> Збережено: {s}")
                        saved_total += saved
                    if low:
                        low_conf_report.append((name, low))
                except ProcessingCancelled:
                    self.log(">>> Обробку скасовано.")
                    cancelled = True
                    break
                except Exception as e:
                    self.log(f"[ПОМИЛКА] {path}:\n{traceback.format_exc()}")
                    failed.append((name, str(e)))
                done += 1
                self.signals.progress.emit(done)
                self.signals.status.emit(f"Обробка: {done}/{total}")

            if combined is not None:
                if cancelled:
                    self.log(">>> Спільний файл не збережено (обробку скасовано).")
                elif combined.files_added:
                    self.signals.status.emit("Збереження спільного файлу...")
                    saved = combined.save(
                        o["out_target"], o["export_text_formats"],
                        o["export_text_split"])
                    for s in saved:
                        self.log(f"  -> Збережено: {s}")
                    saved_total += saved
        except Exception as e:
            self.log(f"[ПОМИЛКА] {traceback.format_exc()}")
            failed.append(("(збереження)", str(e)))
        finally:
            if combined is not None:
                combined.close()

        for name, pages in low_conf_report:
            self.log(
                f"  [!] {name}: невисока впевненість OCR на сторінках "
                f"{', '.join(map(str, pages))} - варто перевірити вручну")

        if cancelled:
            self.signals.status.emit("Скасовано")
            self.log("=== Скасовано ===")
        else:
            self.signals.status.emit("Готово")
            self.log("=== Готово ===")
            if failed:
                lines = "\n".join(f"  • {n}: {r}" for n, r in failed[:10])
                more = f"\n  … і ще {len(failed) - 10}" if len(failed) > 10 else ""
                self._last_summary = (
                    "Є файли з помилкою",
                    f"Створено файлів: {len(saved_total)}\n"
                    f"З помилкою: {len(failed)}\n\n{lines}{more}\n\n"
                    "Подробиці - у журналі.", True)
            elif saved_total:
                self._last_summary = (
                    "Готово", f"Створено файлів: {len(saved_total)}", False)
        self.signals.finished.emit()
