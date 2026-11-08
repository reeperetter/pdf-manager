import os
import sys

import pymupdf
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QFileDialog,
    QMessageBox, QLabel, QProgressBar, QSplitter, QComboBox,
    QLineEdit, QGroupBox, QSpinBox, QListWidget, QListWidgetItem, QStyle,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView
)
from PyQt5.QtCore import Qt, QSize
from PyQt5.QtGui import QPixmap, QImage

from modules.pdf_compressor.compressor_core import (
    COMPRESSION_PRESETS, DEFAULT_PRESET_KEY, compress_pdf_file, format_size
)
from modules.common.batch_runner import BatchRunner
from modules.common.file_list import DropFileList
from modules.common.outputs import resolve_output_path
from theme import apply_theme
from ui_batch_extras import BatchExtras


class PDFBatchCompressorWidget(QWidget):
    """
    Модуль стиснення PDF - як для одного файлу, так і для пакету файлів.

    Текст, вектори та шрифти стискаються без втрат (deflate). Основна
    економія розміру - за рахунок перекодування вбудованих зображень
    (наприклад, сканів) у JPEG з обмеженою роздільною здатністю.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.file_list_paths = []
        self.init_ui()

    # ------------------------------------------------------------------ UI

    def get_style_icon(self, standard_pixmap):
        return self.style().standardIcon(standard_pixmap)

    def init_ui(self):
        left_panel = QWidget()
        left_layout = QVBoxLayout()
        left_layout.setSpacing(6)

        btn_add_files = QPushButton("Додати PDF")
        btn_add_files.setIcon(self.get_style_icon(QStyle.SP_DialogOpenButton))
        btn_add_files.setMinimumHeight(32)
        btn_add_files.clicked.connect(self.add_files)

        btn_clear_list = QPushButton("Очистити список")
        btn_clear_list.setIcon(self.get_style_icon(QStyle.SP_TrashIcon))
        btn_clear_list.setMinimumHeight(30)
        btn_clear_list.clicked.connect(self.clear_file_list)

        self.file_list_widget = DropFileList(self, extended=True)
        self.file_list_widget.currentRowChanged.connect(self.on_file_selected)

        btn_remove_selected = QPushButton("Прибрати виділені")
        btn_remove_selected.setIcon(self.get_style_icon(QStyle.SP_DialogDiscardButton))
        btn_remove_selected.clicked.connect(self.remove_selected_files)

        self.extras = BatchExtras(self, "compress", self.append_files)

        left_layout.addWidget(btn_add_files)
        left_layout.addWidget(self.extras.recent_button)
        left_layout.addWidget(btn_clear_list)
        left_layout.addWidget(QLabel("Файли (перетягніть PDF сюди):"))
        left_layout.addWidget(self.file_list_widget)
        left_layout.addWidget(btn_remove_selected)

        settings_group = QGroupBox("Налаштування стиснення")
        settings_layout = QVBoxLayout()

        self.combo_level = QComboBox()
        for key, preset in COMPRESSION_PRESETS.items():
            self.combo_level.addItem(preset["label"], key)
        self.combo_level.addItem("Власні налаштування", "custom")
        default_index = self.combo_level.findData(DEFAULT_PRESET_KEY)
        self.combo_level.setCurrentIndex(max(0, default_index))
        self.combo_level.currentIndexChanged.connect(self.on_level_changed)

        settings_layout.addWidget(QLabel("Рівень стиснення:"))
        settings_layout.addWidget(self.combo_level)

        custom_row = QHBoxLayout()
        custom_row.addWidget(QLabel("Макс. DPI:"))
        self.spin_dpi = QSpinBox()
        self.spin_dpi.setRange(50, 600)
        self.spin_dpi.setSingleStep(10)
        self.spin_dpi.setValue(COMPRESSION_PRESETS[DEFAULT_PRESET_KEY]["max_dpi"])
        custom_row.addWidget(self.spin_dpi)

        custom_row.addWidget(QLabel("Якість JPEG:"))
        self.spin_quality = QSpinBox()
        self.spin_quality.setRange(10, 95)
        self.spin_quality.setSingleStep(5)
        self.spin_quality.setValue(COMPRESSION_PRESETS[DEFAULT_PRESET_KEY]["jpeg_quality"])
        custom_row.addWidget(self.spin_quality)

        settings_layout.addLayout(custom_row)
        self._set_custom_controls_enabled(False)

        settings_layout.addWidget(QLabel("Що не стискається:"))
        info_label = QLabel("Текст, шрифти й вектори — без втрат.\nСтискаються лише растрові зображення.")
        info_label.setObjectName("MutedLabel")
        info_label.setWordWrap(True)
        settings_layout.addWidget(info_label)

        settings_group.setLayout(settings_layout)
        left_layout.addWidget(settings_group)

        save_options_layout = QHBoxLayout()
        save_options_layout.addWidget(QLabel("Суфікс збереження:"))
        self.txt_suffix = QLineEdit("_compressed")
        self.txt_suffix.setFixedWidth(120)
        save_options_layout.addWidget(self.txt_suffix)
        save_options_layout.addStretch()
        left_layout.addLayout(save_options_layout)
        left_layout.addWidget(self.extras.skip_checkbox)

        left_panel.setLayout(left_layout)

        # ---------------------------------------------------------- right

        right_panel = QWidget()
        right_layout = QVBoxLayout()

        self.preview_label = QLabel("Виберіть файл зі списку\nдля попереднього перегляду")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(320)
        self.preview_label.setObjectName("PagePreview")

        self.info_label = QLabel("")
        self.info_label.setAlignment(Qt.AlignCenter)

        self.results_table = QTableWidget(0, 4)
        self.results_table.setHorizontalHeaderLabels(["Файл", "Було", "Стало", "Економія"])
        self.results_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.results_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.results_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.results_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.results_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.results_table.verticalHeader().setVisible(False)

        bottom_layout = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)

        btn_process_batch = QPushButton("Стиснути файл(и)")
        btn_process_batch.setIcon(self.get_style_icon(QStyle.SP_DialogSaveButton))
        btn_process_batch.setMinimumHeight(35)
        btn_process_batch.setObjectName("BtnPrimary")
        btn_process_batch.clicked.connect(self.process_batch_compress)

        self.runner = BatchRunner(self, btn_process_batch, self.progress_bar)

        bottom_layout.addWidget(self.progress_bar)
        bottom_layout.addWidget(self.extras.open_button)
        bottom_layout.addWidget(self.runner.cancel_button)
        bottom_layout.addWidget(btn_process_batch)

        right_layout.addWidget(self.preview_label)
        right_layout.addWidget(self.info_label)
        right_layout.addWidget(QLabel("Результати:"))
        right_layout.addWidget(self.results_table, stretch=1)
        right_layout.addLayout(bottom_layout)
        right_panel.setLayout(right_layout)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([340, 940])

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(splitter)
        main_layout.setContentsMargins(4, 4, 4, 4)

    def _set_custom_controls_enabled(self, enabled):
        self.spin_dpi.setEnabled(enabled)
        self.spin_quality.setEnabled(enabled)

    # ------------------------------------------------------------- логіка

    def on_level_changed(self, _index):
        key = self.combo_level.currentData()
        if key == "custom":
            self._set_custom_controls_enabled(True)
            return

        self._set_custom_controls_enabled(False)
        preset = COMPRESSION_PRESETS[key]
        self.spin_dpi.setValue(preset["max_dpi"])
        self.spin_quality.setValue(preset["jpeg_quality"])

    def current_settings(self):
        return self.spin_dpi.value(), self.spin_quality.value()

    def append_files(self, files):
        for file_path in files:
            if file_path not in self.file_list_paths:
                self.file_list_paths.append(file_path)
                filename = os.path.basename(file_path)
                size_txt = format_size(os.path.getsize(file_path))
                item = QListWidgetItem(f"{filename}  ({size_txt})")
                self.file_list_widget.addItem(item)
                self.extras.remember([file_path])

        if self.file_list_widget.currentRow() == -1 and self.file_list_paths:
            self.file_list_widget.setCurrentRow(0)

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Виберіть PDF-файли", "", "PDF Files (*.pdf)")
        if files:
            self.append_files(files)

    def clear_file_list(self):
        self.file_list_paths.clear()
        self.file_list_widget.clear()
        self.results_table.setRowCount(0)
        self.preview_label.setText("Виберіть файл зі списку\nдля попереднього перегляду")
        self.preview_label.setPixmap(QPixmap())
        self.info_label.setText("")
        self.progress_bar.setValue(0)

    def remove_selected_files(self):
        rows = sorted({idx.row() for idx in self.file_list_widget.selectedIndexes()}, reverse=True)
        for row in rows:
            if 0 <= row < len(self.file_list_paths):
                del self.file_list_paths[row]
                self.file_list_widget.takeItem(row)

    def on_file_selected(self, index):
        if index < 0 or index >= len(self.file_list_paths):
            return

        file_path = self.file_list_paths[index]
        try:
            doc = pymupdf.open(file_path)
            page = doc[0]
            matrix = pymupdf.Matrix(1.3, 1.3)
            pix = page.get_pixmap(matrix=matrix)
            image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(image)
            self.preview_label.setPixmap(
                pixmap.scaled(self.preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            size_txt = format_size(os.path.getsize(file_path))
            self.info_label.setText(f"Сторінок: {len(doc)}   •   Поточний розмір: {size_txt}")
            doc.close()
        except Exception as e:
            self.preview_label.setText(f"Не вдалося відкрити файл:\n{e}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        pixmap = self.preview_label.pixmap()
        if pixmap and not pixmap.isNull():
            idx = self.file_list_widget.currentRow()
            if idx >= 0:
                self.on_file_selected(idx)

    def process_batch_compress(self):
        if self.runner.running:
            return
        if not self.file_list_paths:
            QMessageBox.warning(self, "Помилка", "Список файлів порожній!")
            return

        output_dir = QFileDialog.getExistingDirectory(self, "Виберіть папку для збереження")
        if not output_dir:
            return

        self.extras.set_output_dir(output_dir)
        max_dpi, jpeg_quality = self.current_settings()
        suffix = self.txt_suffix.text().strip()
        skip_existing = self.extras.skip_existing
        used_out_paths = set()
        paths = list(self.file_list_paths)

        # Рядки таблиці створюємо наперед - у фоні лише оновлюємо значення.
        self.results_table.setRowCount(0)
        for file_path in paths:
            row = self.results_table.rowCount()
            self.results_table.insertRow(row)
            self.results_table.setItem(row, 0, QTableWidgetItem(os.path.basename(file_path)))
            self.results_table.setItem(row, 1, QTableWidgetItem(format_size(os.path.getsize(file_path))))
            self.results_table.setItem(row, 2, QTableWidgetItem("…"))
            self.results_table.setItem(row, 3, QTableWidgetItem("…"))

        def work(file_path):
            """Фоновий потік: ('exists',) або (початковий, новий розмір)."""
            out_path = resolve_output_path(
                output_dir, os.path.basename(file_path), suffix,
                used_out_paths, skip_existing)
            if out_path is None:
                return None
            return compress_pdf_file(
                file_path, out_path, max_dpi=max_dpi, jpeg_quality=jpeg_quality)

        def on_item(index, outcome):
            if outcome.error:
                size_txt, pct_txt = "Помилка", outcome.error[:40]
            elif outcome.value is None:
                size_txt, pct_txt = "Пропущено", "вже є"
            else:
                original_size, new_size = outcome.value
                saved = (1 - new_size / original_size) * 100 if original_size else 0
                size_txt, pct_txt = format_size(new_size), f"{saved:.0f}%"
            self.results_table.setItem(index, 2, QTableWidgetItem(size_txt))
            self.results_table.setItem(index, 3, QTableWidgetItem(pct_txt))

        self.runner.start(
            paths, work, on_item=on_item,
            on_finished=lambda outcomes, cancelled: self._compress_finished(
                outcomes, cancelled, output_dir))

    def _compress_finished(self, outcomes, cancelled, output_dir):
        done = [o.value for o in outcomes if not o.error and o.value is not None]
        skipped_count = sum(1 for o in outcomes if not o.error and o.value is None)
        failed_count = sum(1 for o in outcomes if o.error)
        total_original = sum(d[0] for d in done)
        total_new = sum(d[1] for d in done)

        head = "Обробку скасовано." if cancelled else "Обробку завершено!"
        msg = f"{head}\n\nОброблено файлів: {len(done)}"
        if skipped_count:
            msg += f"\nПропущено (вже є результат): {skipped_count}"
        if failed_count:
            msg += f"\nПомилок: {failed_count}"
        if total_original:
            saved_pct = (1 - total_new / total_original) * 100
            msg += (
                f"\n\nЗагальний розмір: {format_size(total_original)} → {format_size(total_new)}"
                f"\nЕкономія: {saved_pct:.0f}%"
            )
        msg += f"\n\nФайли збережено у:\n{output_dir}"

        QMessageBox.information(
            self, "Скасовано" if cancelled else "Успішно!", msg)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    apply_theme(app)
    window = PDFBatchCompressorWidget()
    window.resize(1280, 800)
    window.show()
    sys.exit(app.exec_())
