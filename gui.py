"""
GUI на PyQt5: головне вікно, список файлів з drag-and-drop, увесь
робочий процес (фонові потоки, сигнали, журнал, налаштування).

Уся логіка розпізнавання/PDF/перекладу - в ocr.py та pdf_pipeline.py;
цей модуль лише викликає її та показує результат користувачу.
"""
import os
import glob
import html
import time
import threading
import traceback

from PyQt5 import QtCore, QtGui, QtWidgets

from ocr import TESSERACT_CMD, _lazy_import_cv2
from pdf_pipeline import (
    IMAGE_EXTENSIONS,
    ProcessingCancelled,
    process_pdf,
    images_to_pdf,
)


_DARK_STYLESHEET = """
QWidget { background-color: #2b2b2b; color: #dddddd; }
QGroupBox { border: 1px solid #444444; margin-top: 8px; padding-top: 6px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
QLineEdit, QPlainTextEdit, QTextBrowser, QListWidget, QSpinBox {
    background-color: #383838; color: #dddddd; border: 1px solid #555555;
}
QPushButton { background-color: #454545; border: 1px solid #5a5a5a; padding: 4px 8px; }
QPushButton:hover { background-color: #525252; }
QPushButton:disabled { color: #888888; }
QProgressBar { background-color: #383838; border: 1px solid #555555; }
QProgressBar::chunk { background-color: #3a7bd5; }
QMenuBar, QMenu { background-color: #2b2b2b; color: #dddddd; }
QMenu::item:selected { background-color: #3a7bd5; }
"""


class DropListWidget(QtWidgets.QListWidget):
    """QListWidget з підтримкою перетягування файлів/папок мишею з
    файлового менеджера прямо у список. Підтримує PDF-файли, папки
    (тоді беруться всі *.pdf всередині) та зображення (jpg/png/...) -
    для них окремий сигнал, бо їх спершу треба зібрати в PDF.

    Додатково підтримує перетягування ЕЛЕМЕНТІВ ВСЕРЕДИНІ списку для
    зміни порядку обробки файлів (InternalMove) - зовнішні drop'и
    (з файлового менеджера) і внутрішнє перетягування розрізняються за
    наявністю URL у mimeData, тому обидва працюють одночасно без
    конфлікту."""
    filesDropped = QtCore.pyqtSignal(list)
    imagesDropped = QtCore.pyqtSignal(list)
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
            # Немає URL - це внутрішнє перетягування (зміна порядку
            # файлів у списку), а не файли ззовні.
            super().dropEvent(event)
            self.reordered.emit()
            return
        pdf_paths = []
        image_paths = []
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if not local:
                continue
            if os.path.isdir(local):
                pdf_paths.extend(sorted(glob.glob(os.path.join(local, "*.pdf"))))
            elif local.lower().endswith(".pdf"):
                pdf_paths.append(local)
            elif local.lower().endswith(IMAGE_EXTENSIONS):
                image_paths.append(local)
        if pdf_paths:
            self.filesDropped.emit(pdf_paths)
        if image_paths:
            self.imagesDropped.emit(image_paths)
        event.acceptProposedAction()


class WorkerSignals(QtCore.QObject):
    """Сигнали для безпечного оновлення GUI з фонового потоку обробки.
    У Qt (на відміну від Tk) не можна напряму чіпати віджети з іншого
    потоку - сигнали/слоти автоматично переносять виклик у головний
    потік, тому саме через них тут і йде весь зв'язок з робочим потоком."""
    log = QtCore.pyqtSignal(str)
    progress = QtCore.pyqtSignal(int)
    status = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()
    image_conversion_done = QtCore.pyqtSignal(str)
    page_progress = QtCore.pyqtSignal(int, int)


def _build_app_icon():
    """Малює тематичну іконку програми "з нуля" через QPainter - лист
    документа з текстовими рядками та стрілкою перекладу поверх. Без
    залежності від зовнішніх файлів зображень (які легко загубити при
    розповсюдженні програми) - іконка завжди на місці, це просто код."""
    size = 256
    pix = QtGui.QPixmap(size, size)
    pix.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.Antialiasing)

    # Лист документа з загнутим кутиком
    doc_color = QtGui.QColor("#f5f5f5")
    border_color = QtGui.QColor("#3a5a8c")
    margin = 28
    fold = 46
    path = QtGui.QPainterPath()
    path.moveTo(margin, margin)
    path.lineTo(size - margin - fold, margin)
    path.lineTo(size - margin, margin + fold)
    path.lineTo(size - margin, size - margin)
    path.lineTo(margin, size - margin)
    path.closeSubpath()
    p.setPen(QtGui.QPen(border_color, 6))
    p.setBrush(doc_color)
    p.drawPath(path)

    fold_path = QtGui.QPainterPath()
    fold_path.moveTo(size - margin - fold, margin)
    fold_path.lineTo(size - margin - fold, margin + fold)
    fold_path.lineTo(size - margin, margin + fold)
    fold_path.closeSubpath()
    p.setBrush(QtGui.QColor("#c7d4e8"))
    p.setPen(QtGui.QPen(border_color, 4))
    p.drawPath(fold_path)

    # Рядки тексту на документі
    pen = QtGui.QPen(QtGui.QColor("#8a97a8"), 8)
    pen.setCapStyle(QtCore.Qt.RoundCap)
    p.setPen(pen)
    line_xs = (margin + 20, size - margin - fold - 10)
    for ly in (98, 122, 146):
        p.drawLine(line_xs[0], ly, line_xs[1] if ly != 146 else line_xs[1] - 40, ly)

    # Кружечок з двонаправленою стрілкою перекладу (акцентний колір)
    accent = QtGui.QColor("#2f8f5b")
    cx, cy, r = size // 2, 190, 46
    p.setBrush(accent)
    p.setPen(QtGui.QPen(QtGui.QColor("#ffffff"), 5))
    p.drawEllipse(QtCore.QPoint(cx, cy), r, r)

    font = QtGui.QFont("DejaVu Sans", 26, QtGui.QFont.Bold)
    p.setFont(font)
    p.setPen(QtGui.QPen(QtGui.QColor("#ffffff")))
    p.drawText(QtCore.QRect(cx - r, cy - r, 2 * r, 2 * r),
               QtCore.Qt.AlignCenter, "A\u21c4\u042f")

    p.end()
    return QtGui.QIcon(pix)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF-manager: OCR + переклад")
        self.setWindowIcon(_build_app_icon())

        self.files = []
        self.cancel_event = threading.Event()
        self.worker_thread = None
        # Діалоги вибору файлів за замовчуванням відкриваються в домашній
        # директорії, а далі запам'ятовують останню відкриту користувачем.
        self.last_dir = os.path.expanduser("~")

        self.settings = QtCore.QSettings("pdf-ocr-translator", "PDFManager")
        self.log_file_path = os.path.join(
            os.path.expanduser("~"), "pdf_ocr_translator.log")
        self._log_file_lock = threading.Lock()

        self.signals = WorkerSignals()
        self.signals.log.connect(self._append_log)
        self.signals.progress.connect(self._set_progress)
        self.signals.status.connect(self._set_status)
        self.signals.finished.connect(self._on_finished)
        self.signals.image_conversion_done.connect(self._on_image_conversion_done)
        self.signals.page_progress.connect(self._set_page_progress)

        self._build_ui()
        self._build_menu()
        self._load_settings()
        self.resize(self.sizeHint())

    # ---------------- UI ----------------
    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root_layout = QtWidgets.QVBoxLayout(central)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(5)

        bold = QtGui.QFont()
        bold.setBold(True)

        # ---- Двоколонковий контейнер: зліва файли+вивід, справа налаштування ----
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
        left_col.addWidget(grp_files)
        files_outer = QtWidgets.QVBoxLayout(grp_files)
        files_outer.setSpacing(4)
        files_layout = QtWidgets.QHBoxLayout()
        files_outer.addLayout(files_layout)

        self.listbox = DropListWidget()
        self.listbox.setSelectionMode(
            QtWidgets.QAbstractItemView.ExtendedSelection)
        self.listbox.setMinimumHeight(110)
        self.listbox.setToolTip(
            "Можна перетягнути сюди PDF-файли, папку або зображення "
            "(зображення буде запропоновано зібрати в PDF)")
        self.listbox.filesDropped.connect(self._add_files_list)
        self.listbox.imagesDropped.connect(self.convert_images_to_pdf)
        self.listbox.reordered.connect(self._resync_files_from_listbox)
        files_layout.addWidget(self.listbox, 1)

        btns = QtWidgets.QVBoxLayout()
        btns.setSpacing(4)
        files_layout.addLayout(btns)
        btn_add_files = QtWidgets.QPushButton("Додати файли...")
        btn_add_files.clicked.connect(self.add_files)
        btn_add_folder = QtWidgets.QPushButton("Додати папку...")
        btn_add_folder.clicked.connect(self.add_folder)
        btns.addWidget(btn_add_files)
        btns.addWidget(btn_add_folder)
        btns.addSpacing(6)
        btn_remove = QtWidgets.QPushButton("Видалити вибране")
        btn_remove.clicked.connect(self.remove_selected)
        btn_clear = QtWidgets.QPushButton("Очистити список")
        btn_clear.clicked.connect(self.clear_files)
        btns.addWidget(btn_remove)
        btns.addWidget(btn_clear)
        btns.addStretch(1)

        # Окремим повноширинним рядком, бо це інша дія - не керування вже
        # доданими файлами, а спосіб СТВОРИТИ вхідний PDF із зображень.
        self.btn_images = QtWidgets.QPushButton("Зображення → PDF...")
        self.btn_images.clicked.connect(lambda: self.convert_images_to_pdf(None))
        files_outer.addWidget(self.btn_images)

        # ---- Куди зберегти - під списком файлів, та сама колонка ----
        grp_out = QtWidgets.QGroupBox("Куди зберегти результат")
        grp_out.setFont(bold)
        left_col.addWidget(grp_out)
        out_layout = QtWidgets.QHBoxLayout(grp_out)
        self.out_dir_edit = QtWidgets.QLineEdit(
            os.path.join(os.path.expanduser("~"), "pdf_ocr_output")
        )
        out_layout.addWidget(self.out_dir_edit, 1)
        btn_out = QtWidgets.QPushButton("Огляд...")
        btn_out.clicked.connect(self.choose_out_dir)
        out_layout.addWidget(btn_out)

        # ---- Текстові файли окремо від PDF - та сама ліва колонка ----
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
        grp_text.setToolTip(
            "Додатково зберігає розпізнаний і/або перекладений текст "
            "як звичайний документ (без зображення сторінки) - зручно "
            "для копіювання чи подальшого редагування тексту.")

        left_col.addStretch(1)

        # ---- Права колонка: налаштування OCR ----
        grp_opts = QtWidgets.QGroupBox("Розпізнавання (OCR)")
        grp_opts.setFont(bold)
        right_col.addWidget(grp_opts)
        opts_layout = QtWidgets.QGridLayout(grp_opts)
        opts_layout.setVerticalSpacing(4)

        opts_layout.addWidget(QtWidgets.QLabel("DPI:"), 0, 0)
        self.dpi_spin = QtWidgets.QSpinBox()
        self.dpi_spin.setRange(150, 600)
        self.dpi_spin.setSingleStep(50)
        self.dpi_spin.setValue(300)
        self.dpi_spin.setToolTip("Більше = точніше розпізнавання, менше = швидше")
        opts_layout.addWidget(self.dpi_spin, 0, 1, 1, 2)

        opts_layout.addWidget(QtWidgets.QLabel("Шрифт:"), 1, 0)
        self.font_edit = QtWidgets.QLineEdit()
        self.font_edit.setPlaceholderText("типово - вбудований DejaVu Sans")
        opts_layout.addWidget(self.font_edit, 1, 1)
        btn_font = QtWidgets.QPushButton("Огляд...")
        btn_font.setSizePolicy(
            QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        btn_font.clicked.connect(self.choose_font)
        opts_layout.addWidget(btn_font, 1, 2)

        opts_layout.addWidget(QtWidgets.QLabel("Сторінки:"), 2, 0)
        page_range_row = QtWidgets.QHBoxLayout()
        page_range_row.setContentsMargins(0, 0, 0, 0)
        self.page_start_spin = QtWidgets.QSpinBox()
        self.page_start_spin.setRange(0, 99999)
        self.page_start_spin.setValue(0)
        self.page_start_spin.setSpecialValueText("з початку")
        page_range_row.addWidget(self.page_start_spin)
        page_range_row.addWidget(QtWidgets.QLabel("–"))
        self.page_end_spin = QtWidgets.QSpinBox()
        self.page_end_spin.setRange(0, 99999)
        self.page_end_spin.setValue(0)
        self.page_end_spin.setSpecialValueText("до кінця")
        page_range_row.addWidget(self.page_end_spin)
        page_range_widget = QtWidgets.QWidget()
        page_range_widget.setLayout(page_range_row)
        page_range_widget.setToolTip(
            "Застосовується до КОЖНОГО файлу зі списку зліва однаково. "
            "Корисно, щоб обробити лише перші кілька сторінок кожного файлу.")
        opts_layout.addWidget(page_range_widget, 2, 1, 1, 2)

        self.chk_dewarp = QtWidgets.QCheckBox("Виправляти викривлення сторінки")
        self.chk_dewarp.setChecked(False)
        self.chk_dewarp.setToolTip(
            "Для сканів/фото зігнутих сторінок книг. Повільніше (~2 сек/"
            "сторінку), потребує пакет opencv-python-headless (~90 МБ). "
            "Не завжди покращує результат на складних фото - вимкнено "
            "за замовчуванням, безпечно лишати вимкненим."
        )
        opts_layout.addWidget(self.chk_dewarp, 3, 0, 1, 3)

        opts_layout.setColumnStretch(1, 1)

        # ---- Що створити ----
        grp_tasks = QtWidgets.QGroupBox("Що створити")
        grp_tasks.setFont(bold)
        right_col.addWidget(grp_tasks)
        tasks_layout = QtWidgets.QVBoxLayout(grp_tasks)
        tasks_layout.setSpacing(3)

        self.chk_searchable = QtWidgets.QCheckBox(
            "Розпізнаваний PDF (виділюваний текст)")
        self.chk_searchable.setChecked(True)
        self.chk_uk = QtWidgets.QCheckBox("Переклад українською")
        self.chk_uk.setChecked(False)
        self.chk_ru = QtWidgets.QCheckBox("Переклад російською")
        self.chk_ru.setChecked(False)
        self.chk_en = QtWidgets.QCheckBox("Переклад англійською")
        self.chk_en.setChecked(False)
        for c in (self.chk_searchable, self.chk_uk, self.chk_ru, self.chk_en):
            tasks_layout.addWidget(c)

        tasks_layout.addSpacing(4)
        self.chk_skip_existing = QtWidgets.QCheckBox(
            "Пропускати файли, для яких результат уже є")
        self.chk_skip_existing.setChecked(True)
        tasks_layout.addWidget(self.chk_skip_existing)

        btn_glossary = QtWidgets.QPushButton("Глосарій (не перекладати)...")
        btn_glossary.clicked.connect(self.edit_glossary)
        tasks_layout.addWidget(btn_glossary)

        right_col.addStretch(1)

        # ---- Запуск + прогрес (на всю ширину, під двома колонками) ----
        run_layout = QtWidgets.QHBoxLayout()
        root_layout.addLayout(run_layout)
        self.start_btn = QtWidgets.QPushButton("Почати обробку")
        self.start_btn.clicked.connect(self.start_processing)
        run_layout.addWidget(self.start_btn)
        self.cancel_btn = QtWidgets.QPushButton("Скасувати")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_processing)
        run_layout.addWidget(self.cancel_btn)
        self.btn_open_out = QtWidgets.QPushButton("Відкрити папку результатів")
        self.btn_open_out.clicked.connect(self.open_output_folder)
        run_layout.addWidget(self.btn_open_out)
        self.status_label = QtWidgets.QLabel("Готово")
        run_layout.addWidget(self.status_label)
        run_layout.addStretch(1)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setTextVisible(False)
        root_layout.addWidget(self.progress)

        page_progress_row = QtWidgets.QHBoxLayout()
        root_layout.addLayout(page_progress_row)
        self.page_progress_label = QtWidgets.QLabel("")
        self.page_progress_label.setStyleSheet("color: #666666;")
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
        normal_font = QtGui.QFont()
        normal_font.setBold(False)
        self.log_text.setFont(normal_font)
        self.log_text.setOpenLinks(False)
        self.log_text.anchorClicked.connect(self._on_log_link_clicked)
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(140)
        log_layout.addWidget(self.log_text)

    # ---------------- Дії ----------------
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
        # Після перетягування елементів для зміни порядку всередині
        # списку - Qt сам переставляє візуальні елементи, а наш паралельний
        # self.files (в тому ж порядку, що й обробка файлів) треба
        # синхронізувати вручну.
        self.files = [self.listbox.item(i).text()
                      for i in range(self.listbox.count())]

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

    def convert_images_to_pdf(self, image_paths):
        if not image_paths:
            image_paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
                self, "Виберіть зображення", self.last_dir,
                "Зображення (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp)",
            )
        if not image_paths:
            return
        self.last_dir = os.path.dirname(image_paths[0])

        mode = "combined"
        if len(image_paths) > 1:
            box = QtWidgets.QMessageBox(self)
            box.setWindowTitle("Формат результату")
            box.setText(
                f"Вибрано {len(image_paths)} зображень. Як зібрати їх у PDF?"
            )
            btn_combined = box.addButton(
                "Один PDF (усі сторінки разом)", QtWidgets.QMessageBox.AcceptRole)
            btn_separate = box.addButton(
                "Окремий PDF для кожного", QtWidgets.QMessageBox.ActionRole)
            box.addButton("Скасувати", QtWidgets.QMessageBox.RejectRole)
            box.exec_()
            clicked = box.clickedButton()
            if clicked == btn_combined:
                mode = "combined"
            elif clicked == btn_separate:
                mode = "separate"
            else:
                return

        if mode == "combined":
            default_name = os.path.splitext(os.path.basename(image_paths[0]))[0] + ".pdf"
            out_target, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "Зберегти як PDF",
                os.path.join(self.last_dir, default_name), "PDF files (*.pdf)",
            )
            if not out_target:
                return
            if not out_target.lower().endswith(".pdf"):
                out_target += ".pdf"
        else:
            out_target = QtWidgets.QFileDialog.getExistingDirectory(
                self, "Папка для окремих PDF-файлів", self.last_dir)
            if not out_target:
                return
            self.last_dir = out_target

        # Сама конвертація (відкриття/перекодування кожного зображення) -
        # у фоновому потоці: на великій кількості файлів (сотні фото)
        # це може тривати десятки секунд, а виконання прямо в обробнику
        # кліку блокує цикл подій Qt - вікно виглядає "завислим" і не
        # відповідає на жодну дію, поки все не завершиться.
        self.cancel_event.clear()
        self.start_btn.setEnabled(False)
        self.btn_images.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress.setRange(0, len(image_paths))
        self.progress.setValue(0)
        self.status_label.setText(f"Конвертація зображень: 0/{len(image_paths)}")

        self.worker_thread = threading.Thread(
            target=self._run_image_conversion,
            args=(image_paths, mode, out_target),
            daemon=True,
        )
        self.worker_thread.start()

    def _run_image_conversion(self, image_paths, mode, out_target):
        def progress_cb(done, total):
            self.signals.progress.emit(done)
            self.signals.status.emit(f"Конвертація зображень: {done}/{total}")

        try:
            if mode == "combined":
                images_to_pdf(
                    image_paths, out_target, log_fn=self.log,
                    progress_fn=progress_cb, cancel_event=self.cancel_event,
                )
                self.signals.log.emit(
                    f"Створено PDF з {len(image_paths)} зображень: {out_target}")
                self.signals.image_conversion_done.emit(out_target)
            else:
                total = len(image_paths)
                for i, img_path in enumerate(image_paths):
                    if self.cancel_event.is_set():
                        raise ProcessingCancelled()
                    base = os.path.splitext(os.path.basename(img_path))[0]
                    out_path = os.path.join(out_target, base + ".pdf")
                    images_to_pdf([img_path], out_path, log_fn=self.log)
                    self.signals.image_conversion_done.emit(out_path)
                    progress_cb(i + 1, total)
                self.signals.log.emit(
                    f"Створено {total} окремих PDF-файлів у папці: {out_target}")
        except ProcessingCancelled:
            self.signals.log.emit(">>> Конвертацію скасовано користувачем.")
        except Exception:
            self.signals.log.emit(
                f"[ПОМИЛКА] Не вдалося створити PDF із зображень:\n{traceback.format_exc()}")
        finally:
            self.signals.status.emit("Готово")
            self.signals.finished.emit()

    def _on_image_conversion_done(self, out_path):
        self._add_files_list([out_path])

    def choose_font(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Виберіть TTF-шрифт з кирилицею", self.last_dir, "TrueType Font (*.ttf)")
        if path:
            self.font_edit.setText(path)
            self.last_dir = os.path.dirname(path)

    def choose_out_dir(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Папка для результатів", self.last_dir)
        if folder:
            self.out_dir_edit.setText(folder)
            self.last_dir = folder

    def open_output_folder(self):
        out_dir = self.out_dir_edit.text().strip()
        if not out_dir:
            return
        os.makedirs(out_dir, exist_ok=True)
        QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(out_dir))

    def edit_glossary(self):
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Глосарій - терміни, які не перекладати")
        layout = QtWidgets.QVBoxLayout(dlg)
        hint = QtWidgets.QLabel(
            "По одному терміну на рядок (без урахування регістру). Такі "
            "рядки тексту завжди лишаються як в оригіналі - зручно для "
            "кодів, назв моделей, абревіатур (напр. EVIC, ESC)."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        edit = QtWidgets.QPlainTextEdit()
        edit.setPlainText("\n".join(sorted(self.glossary_terms)))
        layout.addWidget(edit)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        dlg.resize(420, 320)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            terms = {
                line.strip().lower()
                for line in edit.toPlainText().splitlines() if line.strip()
            }
            self.glossary_terms = terms
            self.settings.setValue("glossary_terms", "\n".join(sorted(terms)))

    # ---------------- Меню / налаштування, що зберігаються між запусками ----------------
    def _build_menu(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("Файл")
        self.recent_menu = file_menu.addMenu("Нещодавні файли")
        self._populate_recent_menu()

        view_menu = menubar.addMenu("Вигляд")
        self.dark_theme_action = QtWidgets.QAction(
            "Темна тема", self, checkable=True)
        self.dark_theme_action.toggled.connect(self._apply_dark_theme)
        view_menu.addAction(self.dark_theme_action)

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
                lambda checked=False, p=path: self._add_files_list([p]) if os.path.isfile(p)
                else QtWidgets.QMessageBox.warning(self, "Файл не знайдено", f"Файла більше немає:\n{p}")
            )

    def _add_recent_file(self, path):
        recent = self.settings.value("recent_files", [], type=list) or []
        recent = [p for p in recent if p != path]
        recent.insert(0, path)
        recent = recent[:10]
        self.settings.setValue("recent_files", recent)
        self._populate_recent_menu()

    def _apply_dark_theme(self, enabled):
        app = QtWidgets.QApplication.instance()
        if enabled:
            app.setStyleSheet(_DARK_STYLESHEET)
        else:
            app.setStyleSheet("")
        self.settings.setValue("dark_theme", enabled)

    def _load_settings(self):
        s = self.settings
        self.dpi_spin.setValue(int(s.value("dpi", 300)))
        self.out_dir_edit.setText(str(s.value(
            "out_dir", os.path.join(os.path.expanduser("~"), "pdf_ocr_output"))))
        self.font_edit.setText(str(s.value("font_path", "")))
        self.chk_searchable.setChecked(s.value("chk_searchable", True, type=bool))
        self.chk_uk.setChecked(s.value("chk_uk", False, type=bool))
        self.chk_ru.setChecked(s.value("chk_ru", False, type=bool))
        self.chk_en.setChecked(s.value("chk_en", False, type=bool))
        self.chk_skip_existing.setChecked(s.value("chk_skip_existing", True, type=bool))
        self.chk_dewarp.setChecked(s.value("chk_dewarp", False, type=bool))
        self.chk_text_docx.setChecked(s.value("chk_text_docx", False, type=bool))
        self.chk_text_txt.setChecked(s.value("chk_text_txt", False, type=bool))
        self.text_split_combo.setCurrentIndex(int(s.value("text_split_index", 0)))
        self.last_dir = str(s.value("last_dir", os.path.expanduser("~")))

        terms_str = str(s.value("glossary_terms", ""))
        self.glossary_terms = {
            t.strip().lower() for t in terms_str.splitlines() if t.strip()
        }

        dark = s.value("dark_theme", False, type=bool)
        self.dark_theme_action.setChecked(dark)
        self._apply_dark_theme(dark)

        geometry = s.value("window_geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)

    def _save_settings(self):
        s = self.settings
        s.setValue("dpi", self.dpi_spin.value())
        s.setValue("out_dir", self.out_dir_edit.text().strip())
        s.setValue("font_path", self.font_edit.text().strip())
        s.setValue("chk_searchable", self.chk_searchable.isChecked())
        s.setValue("chk_uk", self.chk_uk.isChecked())
        s.setValue("chk_ru", self.chk_ru.isChecked())
        s.setValue("chk_en", self.chk_en.isChecked())
        s.setValue("chk_skip_existing", self.chk_skip_existing.isChecked())
        s.setValue("chk_dewarp", self.chk_dewarp.isChecked())
        s.setValue("chk_text_docx", self.chk_text_docx.isChecked())
        s.setValue("chk_text_txt", self.chk_text_txt.isChecked())
        s.setValue("text_split_index", self.text_split_combo.currentIndex())
        s.setValue("last_dir", self.last_dir)
        s.setValue("window_geometry", self.saveGeometry())

    def closeEvent(self, event):
        self._save_settings()
        super().closeEvent(event)

    # ---------------- Лог/прогрес (виконуються в головному потоці - слоти) ----------------
    def _append_log(self, msg):
        # Рядки про збережений файл робимо клікабельним посиланням
        # (відкриває файл в асоційованій програмі перегляду PDF).
        prefix = "  -> Збережено: "
        if msg.startswith(prefix):
            path = msg[len(prefix):].strip()
            url = QtCore.QUrl.fromLocalFile(path).toString()
            self.log_text.append(
                f'{prefix}<a href="{url}">{html.escape(path)}</a>')
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
        self.btn_images.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.page_progress_label.setText("")
        self.page_progress.setValue(0)

    def log(self, msg):
        # Пишемо у файл одразу й синхронно (навіть якщо GUI зависне чи
        # впаде - лог на диску вже буде), а в GUI - через сигнал, щоб
        # безпечно оновити віджет з фонового потоку.
        with self._log_file_lock:
            try:
                with open(self.log_file_path, "a", encoding="utf-8") as f:
                    ts = time.strftime("%Y-%m-%d %H:%M:%S")
                    f.write(f"[{ts}] {msg}\n")
            except Exception:
                pass
        self.signals.log.emit(msg)

    # ---------------- Обробка ----------------
    def start_processing(self):
        if not self.files:
            QtWidgets.QMessageBox.warning(
                self, "Немає файлів", "Спочатку додайте хоча б один PDF-файл.")
            return
        if not (self.chk_searchable.isChecked() or self.chk_uk.isChecked()
                or self.chk_ru.isChecked() or self.chk_en.isChecked()):
            QtWidgets.QMessageBox.warning(
                self, "Нічого робити", "Виберіть хоча б одну дію у розділі «Що створити».")
            return

        if not TESSERACT_CMD:
            QtWidgets.QMessageBox.critical(
                self, "Tesseract не знайдено",
                "Не вдалося знайти виконуваний файл Tesseract OCR.\n\n"
                "Linux: sudo apt install tesseract-ocr tesseract-ocr-ukr tesseract-ocr-rus\n"
                "Windows: https://github.com/UB-Mannheim/tesseract/wiki\n\n"
                "OCR запуститься лише для сторінок без текстового шару — "
                "якщо всі ваші PDF уже мають текст, можна продовжити і без нього.",
            )
            return

        if self.chk_dewarp.isChecked():
            try:
                _lazy_import_cv2()
            except RuntimeError as e:
                choice = QtWidgets.QMessageBox.warning(
                    self, "Пакет для розпрямлення не встановлено", str(e) +
                    "\n\nПродовжити обробку БЕЗ розпрямлення сторінок?",
                    QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel,
                )
                if choice != QtWidgets.QMessageBox.Yes:
                    return
                self.chk_dewarp.setChecked(False)

        make_searchable = self.chk_searchable.isChecked()
        translate_targets = []
        if self.chk_uk.isChecked():
            translate_targets.append("uk")
        if self.chk_ru.isChecked():
            translate_targets.append("ru")
        if self.chk_en.isChecked():
            translate_targets.append("en")

        dpi = self.dpi_spin.value()
        font_path = self.font_edit.text().strip() or None
        out_dir = self.out_dir_edit.text().strip()
        page_start = self.page_start_spin.value() or None
        page_end = self.page_end_spin.value() or None
        skip_existing = self.chk_skip_existing.isChecked()
        glossary = set(self.glossary_terms)
        dewarp = self.chk_dewarp.isChecked()
        export_text_formats = set()
        if self.chk_text_docx.isChecked():
            export_text_formats.add("docx")
        if self.chk_text_txt.isChecked():
            export_text_formats.add("txt")
        export_text_split = self.text_split_combo.currentIndex() == 1

        self._save_settings()

        self.cancel_event.clear()
        self.start_btn.setEnabled(False)
        self.btn_images.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress.setRange(0, len(self.files))
        self.progress.setValue(0)
        self.status_label.setText(f"Обробка: 0/{len(self.files)}")

        self.worker_thread = threading.Thread(
            target=self._run_worker,
            args=(
                list(self.files), out_dir, dpi,
                make_searchable, translate_targets, font_path,
                page_start, page_end, skip_existing, glossary, dewarp,
                export_text_formats, export_text_split,
            ),
            daemon=True,
        )
        self.worker_thread.start()

    def cancel_processing(self):
        self.cancel_event.set()
        self.signals.status.emit("Скасування...")
        self.log(">>> Скасування... зачекайте завершення поточної сторінки.")

    def _expected_outputs(self, path, out_dir, make_searchable, translate_targets):
        base_name = os.path.splitext(os.path.basename(path))[0]
        expected = []
        if make_searchable:
            expected.append(os.path.join(out_dir, f"{base_name}_searchable.pdf"))
        for lang in translate_targets:
            expected.append(os.path.join(out_dir, f"{base_name}_{lang}.pdf"))
        return expected

    def _run_worker(self, files, out_dir, dpi, make_searchable, translate_targets,
                     font_path, page_start, page_end, skip_existing, glossary, dewarp,
                     export_text_formats, export_text_split):
        done = 0
        total = len(files)
        all_low_confidence = []  # [(filename, [сторінки]), ...]

        for path in files:
            if self.cancel_event.is_set():
                self.log(">>> Обробку скасовано користувачем.")
                break

            if skip_existing:
                expected = self._expected_outputs(
                    path, out_dir, make_searchable, translate_targets)
                if expected and all(os.path.isfile(p) for p in expected):
                    self.log(
                        f"=== Пропущено (результат уже є): {os.path.basename(path)} ===")
                    done += 1
                    self.signals.progress.emit(done)
                    self.signals.status.emit(f"Обробка: {done}/{total}")
                    continue

            def page_progress_cb(page_num, n_pages):
                self.signals.page_progress.emit(page_num, n_pages)

            try:
                self.log(f"=== Обробка: {os.path.basename(path)} ===")
                saved, low_conf_pages = process_pdf(
                    input_path=path,
                    output_dir=out_dir,
                    dpi=dpi,
                    make_searchable=make_searchable,
                    translate_targets=translate_targets,
                    font_path=font_path,
                    log_fn=self.log,
                    cancel_event=self.cancel_event,
                    page_start=page_start,
                    page_end=page_end,
                    page_progress_fn=page_progress_cb,
                    glossary=glossary,
                    dewarp=dewarp,
                    export_text_formats=export_text_formats,
                    export_text_split_pages=export_text_split,
                )
                for s in saved:
                    self.log(f"  -> Збережено: {s}")
                if low_conf_pages:
                    all_low_confidence.append(
                        (os.path.basename(path), low_conf_pages))
            except ProcessingCancelled:
                self.log(">>> Обробку скасовано користувачем.")
                break
            except Exception:
                self.log(f"[ПОМИЛКА] {path}:\n{traceback.format_exc()}")
            done += 1
            self.signals.progress.emit(done)
            self.signals.status.emit(f"Обробка: {done}/{total}")

        if all_low_confidence:
            self.log("=== Сторінки з невисокою впевненістю OCR (варто перевірити) ===")
            for fname, pages in all_low_confidence:
                pages_str = ", ".join(str(p) for p in pages)
                self.log(f"  {fname}: сторінки {pages_str}")

        self.signals.status.emit("Готово")
        self.log("=== Готово ===")
        self.signals.finished.emit()
