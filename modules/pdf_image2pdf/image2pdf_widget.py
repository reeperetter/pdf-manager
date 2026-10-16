"""
Окремий інструмент "Зображення → PDF" - збирає JPG/PNG/BMP/TIFF/WEBP у один
або кілька PDF-файлів.

Раніше ця функція жила всередині вкладки "OCR та Переклад"
(modules/pdf_translator/gui.py) як одна кнопка серед багатьох налаштувань
розпізнавання - непомітна й логічно не пов'язана з рештою цієї вкладки.
Тут вона - самостійний інструмент зі своєю вкладкою та інтуїтивним GUI:
список зображень зліва (з мініатюрами й можливістю перетягуванням міняти
порядок сторінок - саме цей порядок і потрапить у підсумковий PDF),
великий попередній перегляд вибраного зображення справа, і прості елементи
керування внизу.

Сама логіка збирання зображень у PDF (images_to_pdf) лишається у
modules/pdf_translator/pdf_pipeline.py - вона не специфічна для OCR, це
просто спільний код, яким тепер користуються обидва модулі.
"""
import os
import sys
import threading
import traceback

from PyQt5 import QtCore, QtGui, QtWidgets

from theme import COLORS
from ui_batch_extras import BatchExtras
from ui_icons import create_vector_icon
from modules.pdf_translator.pdf_pipeline import (
    IMAGE_EXTENSIONS,
    ProcessingCancelled,
    images_to_pdf,
)


class ImageDropListWidget(QtWidgets.QListWidget):
    """Список зображень з drag-and-drop додаванням і перетягуванням для
    зміни порядку (саме порядок у списку визначає порядок сторінок)."""

    imagesDropped = QtCore.pyqtSignal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.setIconSize(QtCore.QSize(48, 48))
        self.setSpacing(2)

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
            paths = [
                url.toLocalFile() for url in event.mimeData().urls()
                if url.toLocalFile().lower().endswith(IMAGE_EXTENSIONS)
            ]
            if paths:
                self.imagesDropped.emit(paths)
            event.acceptProposedAction()
        else:
            # Перетягування всередині списку - зміна порядку сторінок.
            super().dropEvent(event)


class WorkerSignals(QtCore.QObject):
    log = QtCore.pyqtSignal(str)
    progress = QtCore.pyqtSignal(int)
    status = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()
    error = QtCore.pyqtSignal(str)


class PDFImageToPdfWidget(QtWidgets.QWidget):
    """Пакетна конвертація зображень у PDF, незалежно від OCR/перекладу."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.image_paths = []
        self.cancel_event = threading.Event()
        self.worker_thread = None
        self.last_dir = os.path.expanduser("~")
        self.current_out_target = None
        self._last_result_text = ""

        self.signals = WorkerSignals()
        self.signals.log.connect(self._append_log)
        self.signals.progress.connect(self._set_progress)
        self.signals.status.connect(self._set_status)
        self.signals.finished.connect(self._on_finished)
        self.signals.error.connect(self._on_error)

        self.init_ui()

    def get_style_icon(self, standard_pixmap):
        return self.style().standardIcon(standard_pixmap)

    # ------------------------------------------------------------- UI --
    def init_ui(self):
        # ---- Ліва панель: список зображень (порядок = порядок сторінок) ----
        left_panel = QtWidgets.QWidget()
        left_layout = QtWidgets.QVBoxLayout()
        left_layout.setSpacing(6)

        btn_add = QtWidgets.QPushButton("Додати зображення (Ctrl+O)")
        btn_add.setIcon(self.get_style_icon(QtWidgets.QStyle.SP_DialogOpenButton))
        btn_add.setMinimumHeight(32)
        btn_add.clicked.connect(self.add_images)

        btn_clear = QtWidgets.QPushButton("Очистити список")
        btn_clear.setIcon(self.get_style_icon(QtWidgets.QStyle.SP_TrashIcon))
        btn_clear.setMinimumHeight(30)
        btn_clear.clicked.connect(self.clear_list)

        hint = QtWidgets.QLabel(
            "Перетягніть зображення сюди, щоб додати.\n"
            "Перетягніть рядки у списку, щоб змінити порядок сторінок."
        )
        hint.setObjectName("MutedLabel")
        hint.setWordWrap(True)

        self.list_widget = ImageDropListWidget(self)
        self.list_widget.imagesDropped.connect(self.append_images)
        self.list_widget.currentRowChanged.connect(self.on_selection_changed)
        self.list_widget.model().rowsMoved.connect(self._resync_order_from_list)

        reorder_layout = QtWidgets.QHBoxLayout()
        btn_up = QtWidgets.QPushButton("▲ Вгору")
        btn_up.clicked.connect(self.move_selected_up)
        btn_down = QtWidgets.QPushButton("▼ Вниз")
        btn_down.clicked.connect(self.move_selected_down)
        btn_remove = QtWidgets.QPushButton("Видалити вибране")
        btn_remove.setIcon(self.get_style_icon(QtWidgets.QStyle.SP_DialogDiscardButton))
        btn_remove.clicked.connect(self.remove_selected)
        reorder_layout.addWidget(btn_up)
        reorder_layout.addWidget(btn_down)

        self.extras = BatchExtras(
            self, "image2pdf", self.append_images,
            extensions=tuple(IMAGE_EXTENSIONS))
        self.extras.skip_checkbox.setToolTip(
            "Діє в режимі «окремий PDF для кожного зображення»: якщо PDF із "
            "такою назвою вже є в папці, зображення пропускається.")

        left_layout.addWidget(btn_add)
        left_layout.addWidget(self.extras.recent_button)
        left_layout.addWidget(btn_clear)
        left_layout.addWidget(hint)
        left_layout.addWidget(self.list_widget, 1)
        left_layout.addLayout(reorder_layout)
        left_layout.addWidget(btn_remove)
        left_panel.setLayout(left_layout)

        # ---- Права панель: попередній перегляд + налаштування + запуск ----
        right_panel = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout()
        right_layout.setSpacing(8)

        preview_label = QtWidgets.QLabel("Попередній перегляд:")
        right_layout.addWidget(preview_label)

        self.preview = QtWidgets.QLabel("Виберіть зображення зі списку")
        self.preview.setObjectName("PagePreview")
        self.preview.setAlignment(QtCore.Qt.AlignCenter)
        self.preview.setMinimumHeight(360)
        self.preview.setScaledContents(False)
        right_layout.addWidget(self.preview, 1)

        # ---- Що робити зі списком ----
        grp_mode = QtWidgets.QGroupBox("Що створити")
        mode_layout = QtWidgets.QVBoxLayout(grp_mode)

        self.radio_combined = QtWidgets.QRadioButton(
            "Один PDF з усіх зображень (кожне зображення - окрема сторінка)")
        self.radio_combined.setChecked(True)
        self.radio_separate = QtWidgets.QRadioButton(
            "Окремий PDF-файл для кожного зображення")
        mode_layout.addWidget(self.radio_combined)
        mode_layout.addWidget(self.radio_separate)
        mode_layout.addWidget(self.extras.skip_checkbox)

        right_layout.addWidget(grp_mode)

        # Куди зберегти результат питаємо НЕ тут окремим кроком, а прямо
        # при натисканні "Конвертувати у PDF" нижче - і одразу правильний
        # діалог (вибір файлу .pdf чи вибір папки) залежно від того, який
        # з двох варіантів вище обрано. Раніше це був окремий рядок із
        # полем і кнопкою "Огляд...", який треба було не забути натиснути
        # заздалегідь - і, що гірше, якщо після вибору шляху користувач
        # перемикав режим (один файл / декілька), поле не очищалось і
        # лишало шлях від попереднього режиму (наприклад, вибрану папку,
        # коли насправді вже обрано "один PDF").
        self.out_hint = QtWidgets.QLabel()
        self.out_hint.setObjectName("MutedLabel")
        self.out_hint.setWordWrap(True)
        self.radio_combined.toggled.connect(self._update_out_hint)
        right_layout.addWidget(self.out_hint)

        # ---- Прогрес + запуск/скасування ----
        self.status_label = QtWidgets.QLabel("Готово")
        self.status_label.setObjectName("MutedLabel")
        right_layout.addWidget(self.status_label)

        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setValue(0)
        right_layout.addWidget(self.progress_bar)

        actions_layout = QtWidgets.QHBoxLayout()
        self.btn_convert = QtWidgets.QPushButton("Конвертувати у PDF")
        self.btn_convert.setIcon(create_vector_icon("play", COLORS["text_on_accent"]))
        self.btn_convert.setIconSize(QtCore.QSize(18, 18))
        self.btn_convert.setObjectName("BtnPrimary")
        self.btn_convert.setMinimumHeight(35)
        self.btn_convert.clicked.connect(self.start_conversion)

        self.btn_cancel = QtWidgets.QPushButton("Скасувати")
        self.btn_cancel.setIcon(create_vector_icon("stop", COLORS["text_on_accent"]))
        self.btn_cancel.setIconSize(QtCore.QSize(16, 16))
        self.btn_cancel.setObjectName("BtnDanger")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_conversion)

        actions_layout.addWidget(self.btn_convert, 2)
        actions_layout.addWidget(self.btn_cancel, 1)
        actions_layout.addWidget(self.extras.open_button, 1)
        right_layout.addLayout(actions_layout)

        right_panel.setLayout(right_layout)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([360, 920])

        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.addWidget(splitter)
        main_layout.setContentsMargins(4, 4, 4, 4)

        QtWidgets.QShortcut(QtGui.QKeySequence("Ctrl+O"), self, self.add_images)

        self._update_out_hint()

    # --------------------------------------------------------- список --
    def append_images(self, paths):
        for path in paths:
            if path not in self.image_paths:
                self.image_paths.append(path)
                item = QtWidgets.QListWidgetItem(os.path.basename(path))
                item.setIcon(self._make_thumbnail(path))
                item.setData(QtCore.Qt.UserRole, path)
                self.list_widget.addItem(item)
                self.extras.remember([path])

        if self.list_widget.currentRow() == -1 and self.image_paths:
            self.list_widget.setCurrentRow(0)

        self._renumber_items()

    def _make_thumbnail(self, path):
        pixmap = QtGui.QPixmap(path)
        if pixmap.isNull():
            return self.get_style_icon(QtWidgets.QStyle.SP_FileIcon)
        return QtGui.QIcon(pixmap.scaled(
            48, 48, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))

    def _renumber_items(self):
        """Показує порядковий номер сторінки перед назвою файлу - щоб
        одразу було видно, у якому порядку зображення підуть у PDF."""
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            path = item.data(QtCore.Qt.UserRole)
            item.setText(f"{i + 1}. {os.path.basename(path)}")

    def _resync_order_from_list(self, *args):
        self.image_paths = [
            self.list_widget.item(i).data(QtCore.Qt.UserRole)
            for i in range(self.list_widget.count())
        ]
        self._renumber_items()

    def add_images(self):
        patterns = " ".join(f"*{ext}" for ext in IMAGE_EXTENSIONS)
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Виберіть зображення", self.last_dir,
            f"Зображення ({patterns})")
        if paths:
            self.last_dir = os.path.dirname(paths[0])
            self.append_images(paths)

    def clear_list(self):
        self.image_paths.clear()
        self.list_widget.clear()
        self.preview.clear()
        self.preview.setText("Виберіть зображення зі списку")

    def remove_selected(self):
        for item in self.list_widget.selectedItems():
            self.list_widget.takeItem(self.list_widget.row(item))
        self._resync_order_from_list()

    def move_selected_up(self):
        row = self.list_widget.currentRow()
        if row > 0:
            item = self.list_widget.takeItem(row)
            self.list_widget.insertItem(row - 1, item)
            self.list_widget.setCurrentRow(row - 1)
            self._resync_order_from_list()

    def move_selected_down(self):
        row = self.list_widget.currentRow()
        if 0 <= row < self.list_widget.count() - 1:
            item = self.list_widget.takeItem(row)
            self.list_widget.insertItem(row + 1, item)
            self.list_widget.setCurrentRow(row + 1)
            self._resync_order_from_list()

    def on_selection_changed(self, row):
        if row < 0 or row >= len(self.image_paths):
            self.preview.clear()
            self.preview.setText("Виберіть зображення зі списку")
            return
        path = self.image_paths[row]
        pixmap = QtGui.QPixmap(path)
        if pixmap.isNull():
            self.preview.setText(f"Не вдалося показати прев'ю:\n{os.path.basename(path)}")
            return
        self.preview.setPixmap(pixmap.scaled(
            self.preview.width(), self.preview.height(),
            QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.on_selection_changed(self.list_widget.currentRow())

    # --------------------------------------------------------- режим --
    def _update_out_hint(self):
        if self.radio_combined.isChecked():
            self.out_hint.setText(
                "Натискання «Конвертувати у PDF» одразу запропонує вибрати "
                "файл .pdf для збереження.")
        else:
            self.out_hint.setText(
                "Натискання «Конвертувати у PDF» одразу запропонує вибрати "
                "папку - по одному PDF-файлу на кожне зображення.")

    # ----------------------------------------------------- конвертація --
    def start_conversion(self):
        if not self.image_paths:
            QtWidgets.QMessageBox.warning(self, "Помилка", "Список зображень порожній!")
            return

        mode = "combined" if self.radio_combined.isChecked() else "separate"

        if mode == "combined":
            default_name = "images.pdf"
            if self.image_paths:
                default_name = os.path.splitext(os.path.basename(self.image_paths[0]))[0] + ".pdf"
            out_target, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "Зберегти як PDF", os.path.join(self.last_dir, default_name),
                "PDF files (*.pdf)")
            if not out_target:
                return
            if not out_target.lower().endswith(".pdf"):
                out_target += ".pdf"
            self.last_dir = os.path.dirname(out_target)
        else:
            out_target = QtWidgets.QFileDialog.getExistingDirectory(
                self, "Папка для окремих PDF-файлів", self.last_dir)
            if not out_target:
                return
            self.last_dir = out_target

        self.current_out_target = out_target
        self.extras.set_output_dir(
            os.path.dirname(out_target) if mode == "combined" else out_target)

        self.cancel_event.clear()
        self.btn_convert.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.progress_bar.setMaximum(len(self.image_paths))
        self.progress_bar.setValue(0)
        self.status_label.setText(f"Конвертація: 0/{len(self.image_paths)}")

        # Знімок списку в момент запуску - щоб подальша зміна списку
        # користувачем під час фонової обробки не вплинула на те, що
        # вже конвертується.
        self.worker_thread = threading.Thread(
            target=self._run_conversion,
            args=(list(self.image_paths), mode, out_target),
            daemon=True,
        )
        self.worker_thread.start()

    def cancel_conversion(self):
        self.cancel_event.set()
        self.signals.status.emit("Скасування...")

    def _run_conversion(self, image_paths, mode, out_target):
        def progress_cb(done, total):
            self.signals.progress.emit(done)
            self.signals.status.emit(f"Конвертація: {done}/{total}")

        def log_cb(msg):
            self.signals.log.emit(msg)

        self._last_result_text = ""
        try:
            if mode == "combined":
                images_to_pdf(
                    image_paths, out_target, log_fn=log_cb,
                    progress_fn=progress_cb, cancel_event=self.cancel_event,
                )
                self._last_result_text = (
                    f"Створено один PDF із {len(image_paths)} зображень:\n{out_target}")
            else:
                total = len(image_paths)
                # Імена вихідних файлів беруться з назви зображення. Якщо
                # серед вибраних є файли з однаковою назвою (з різних
                # папок, або "photo.png" і "photo.jpg"), без цього вони
                # писали б в один і той самий .pdf, і кожен наступний
                # мовчки затирав би попередній - в результаті з кількох
                # зображень лишався б лише один PDF. Додаємо лічильник
                # "_1", "_2", ... і не перезаписуємо вже наявні файли.
                used_paths = set()
                created = 0
                existing = 0
                for i, img_path in enumerate(image_paths):
                    if self.cancel_event.is_set():
                        raise ProcessingCancelled()
                    base = os.path.splitext(os.path.basename(img_path))[0]
                    out_path = os.path.join(out_target, base + ".pdf")
                    if self.extras.skip_existing and os.path.exists(out_path) \
                            and out_path not in used_paths:
                        existing += 1
                        progress_cb(i + 1, total)
                        continue
                    counter = 1
                    while out_path in used_paths or os.path.exists(out_path):
                        out_path = os.path.join(out_target, f"{base}_{counter}.pdf")
                        counter += 1
                    used_paths.add(out_path)
                    images_to_pdf([img_path], out_path, log_fn=log_cb)
                    created += 1
                    progress_cb(i + 1, total)
                extra = (f"\nПропущено (вже є результат): {existing}"
                         if existing else "")
                self._last_result_text = (
                    f"Створено PDF-файлів: {created}{extra}\nПапка:\n{out_target}")
        except ProcessingCancelled:
            self._last_result_text = ""
            self.signals.status.emit("Скасовано")
        except Exception:
            self._last_result_text = ""
            self.signals.error.emit(traceback.format_exc())
        finally:
            self.signals.finished.emit()

    # ------------------------------------------------------- сигнали --
    def _append_log(self, msg):
        # Поки що без окремого вікна журналу - помилки показуються через
        # QMessageBox у _on_error, а проміжні повідомлення (просування по
        # сторінках) дублюються у статус-рядок через _set_status.
        pass

    def _set_progress(self, value):
        self.progress_bar.setValue(value)
        QtCore.QCoreApplication.processEvents()

    def _set_status(self, text):
        self.status_label.setText(text)
        QtCore.QCoreApplication.processEvents()

    def _on_finished(self):
        self.btn_convert.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        if self._last_result_text:
            self.status_label.setText("Готово")
            QtWidgets.QMessageBox.information(
                self, "Успішно!", f"Конвертацію завершено.\n\n{self._last_result_text}")

    def _on_error(self, trace_text):
        QtWidgets.QMessageBox.critical(
            self, "Помилка конвертації",
            f"Під час конвертації сталася помилка:\n\n{trace_text}")


if __name__ == "__main__":
    from theme import apply_theme
    app = QtWidgets.QApplication(sys.argv)
    apply_theme(app)
    window = PDFImageToPdfWidget()
    window.resize(1280, 800)
    window.show()
    sys.exit(app.exec_())
