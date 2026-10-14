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

        left_layout.addWidget(btn_add)
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
        self.radio_combined.toggled.connect(self._update_output_row)
        mode_layout.addWidget(self.radio_combined)
        mode_layout.addWidget(self.radio_separate)

        right_layout.addWidget(grp_mode)

        # ---- Куди зберегти (перемикається залежно від режиму вище) ----
        out_layout = QtWidgets.QHBoxLayout()
        self.out_label = QtWidgets.QLabel("Зберегти як:")
        self.out_edit = QtWidgets.QLineEdit()
        self.out_edit.setPlaceholderText("Виберіть, куди зберегти результат...")
        btn_out = QtWidgets.QPushButton("Огляд...")
        btn_out.clicked.connect(self.choose_output)
        out_layout.addWidget(self.out_label)
        out_layout.addWidget(self.out_edit, 1)
        out_layout.addWidget(btn_out)
        right_layout.addLayout(out_layout)

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

        self._update_output_row()

    # --------------------------------------------------------- список --
    def append_images(self, paths):
        for path in paths:
            if path not in self.image_paths:
                self.image_paths.append(path)
                item = QtWidgets.QListWidgetItem(os.path.basename(path))
                item.setIcon(self._make_thumbnail(path))
                item.setData(QtCore.Qt.UserRole, path)
                self.list_widget.addItem(item)

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
    def _update_output_row(self):
        if self.radio_combined.isChecked():
            self.out_label.setText("Зберегти як:")
            self.out_edit.setPlaceholderText("Виберіть файл .pdf для збереження...")
        else:
            self.out_label.setText("Папка для PDF-файлів:")
            self.out_edit.setPlaceholderText("Виберіть папку, куди зберегти по одному PDF на зображення...")

    def choose_output(self):
        if self.radio_combined.isChecked():
            default_name = "images.pdf"
            if self.image_paths:
                default_name = os.path.splitext(os.path.basename(self.image_paths[0]))[0] + ".pdf"
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "Зберегти як PDF", os.path.join(self.last_dir, default_name),
                "PDF files (*.pdf)")
            if path:
                if not path.lower().endswith(".pdf"):
                    path += ".pdf"
                self.out_edit.setText(path)
                self.last_dir = os.path.dirname(path)
        else:
            folder = QtWidgets.QFileDialog.getExistingDirectory(
                self, "Папка для окремих PDF-файлів", self.last_dir)
            if folder:
                self.out_edit.setText(folder)
                self.last_dir = folder

    # ----------------------------------------------------- конвертація --
    def start_conversion(self):
        if not self.image_paths:
            QtWidgets.QMessageBox.warning(self, "Помилка", "Список зображень порожній!")
            return

        out_target = self.out_edit.text().strip()
        if not out_target:
            QtWidgets.QMessageBox.warning(
                self, "Помилка", "Спочатку виберіть, куди зберегти результат (кнопка «Огляд...»).")
            return

        mode = "combined" if self.radio_combined.isChecked() else "separate"
        if mode == "separate":
            os.makedirs(out_target, exist_ok=True)

        self.cancel_event.clear()
        self.btn_convert.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.progress_bar.setMaximum(len(self.image_paths))
        self.progress_bar.setValue(0)
        self.status_label.setText(f"Конвертація: 0/{len(self.image_paths)}")

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

        try:
            if mode == "combined":
                images_to_pdf(
                    image_paths, out_target, log_fn=log_cb,
                    progress_fn=progress_cb, cancel_event=self.cancel_event,
                )
            else:
                total = len(image_paths)
                for i, img_path in enumerate(image_paths):
                    if self.cancel_event.is_set():
                        raise ProcessingCancelled()
                    base = os.path.splitext(os.path.basename(img_path))[0]
                    out_path = os.path.join(out_target, base + ".pdf")
                    images_to_pdf([img_path], out_path, log_fn=log_cb)
                    progress_cb(i + 1, total)
        except ProcessingCancelled:
            self.signals.status.emit("Скасовано")
        except Exception:
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
        if self.status_label.text() not in ("Скасовано",):
            self.status_label.setText("Готово")
            QtWidgets.QMessageBox.information(
                self, "Успішно!",
                f"Конвертацію завершено.\n\nРезультат збережено у:\n{self.out_edit.text().strip()}")

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
