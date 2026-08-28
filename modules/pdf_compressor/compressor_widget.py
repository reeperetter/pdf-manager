import os
import sys

import pymupdf as fitz
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


class CompressorDropListWidget(QListWidget):
    """Список файлів з підтримкою Drag-and-Drop для модуля стиснення."""

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.owner = owner
        self.setAcceptDrops(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)

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
            files = [
                url.toLocalFile() for url in event.mimeData().urls()
                if url.toLocalFile().lower().endswith(".pdf")
            ]
            if files:
                self.owner.append_files(files)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


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
        self.setStyleSheet("""
            QPushButton { padding: 4px 6px; }
        """)

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

        self.file_list_widget = CompressorDropListWidget(self, self)
        self.file_list_widget.currentRowChanged.connect(self.on_file_selected)

        btn_remove_selected = QPushButton("Прибрати виділені")
        btn_remove_selected.setIcon(self.get_style_icon(QStyle.SP_DialogDiscardButton))
        btn_remove_selected.clicked.connect(self.remove_selected_files)

        left_layout.addWidget(btn_add_files)
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
        info_label.setStyleSheet("color: #6E6359; font-size: 11px;")
        info_label.setWordWrap(True)
        settings_layout.addWidget(info_label)

        settings_group.setLayout(settings_layout)
        left_layout.addWidget(settings_group)

        save_options_layout = QHBoxLayout()
        save_options_layout.addWidget(QLabel("Префікс збереження:"))
        self.txt_prefix = QLineEdit("compressed_")
        self.txt_prefix.setFixedWidth(120)
        save_options_layout.addWidget(self.txt_prefix)
        save_options_layout.addStretch()
        left_layout.addLayout(save_options_layout)

        left_panel.setLayout(left_layout)

        # ---------------------------------------------------------- right

        right_panel = QWidget()
        right_layout = QVBoxLayout()

        self.preview_label = QLabel("Виберіть файл зі списку\nдля попереднього перегляду")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(320)
        self.preview_label.setStyleSheet(
            "background-color: #d0d0d0; border: 1px solid #cccccc; color: #5C534A;"
        )

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

        bottom_layout.addWidget(self.progress_bar)
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
            doc = fitz.open(file_path)
            page = doc[0]
            matrix = fitz.Matrix(1.3, 1.3)
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
        if not self.file_list_paths:
            QMessageBox.warning(self, "Помилка", "Список файлів порожній!")
            return

        output_dir = QFileDialog.getExistingDirectory(self, "Виберіть папку для збереження")
        if not output_dir:
            return

        max_dpi, jpeg_quality = self.current_settings()
        prefix = self.txt_prefix.text().strip()

        total_files = len(self.file_list_paths)
        self.progress_bar.setMaximum(total_files)
        self.progress_bar.setValue(0)
        self.results_table.setRowCount(0)

        total_original = 0
        total_new = 0
        processed_count = 0
        failed_count = 0

        for idx, file_path in enumerate(self.file_list_paths):
            filename = os.path.basename(file_path)
            out_path = os.path.join(output_dir, f"{prefix}{filename}")

            row = self.results_table.rowCount()
            self.results_table.insertRow(row)
            self.results_table.setItem(row, 0, QTableWidgetItem(filename))
            self.results_table.setItem(row, 1, QTableWidgetItem(format_size(os.path.getsize(file_path))))
            self.results_table.setItem(row, 2, QTableWidgetItem("…"))
            self.results_table.setItem(row, 3, QTableWidgetItem("…"))
            QApplication.processEvents()

            try:
                original_size, new_size = compress_pdf_file(
                    file_path, out_path, max_dpi=max_dpi, jpeg_quality=jpeg_quality
                )
                total_original += original_size
                total_new += new_size
                processed_count += 1

                saved_pct = (1 - new_size / original_size) * 100 if original_size else 0
                self.results_table.setItem(row, 2, QTableWidgetItem(format_size(new_size)))
                self.results_table.setItem(row, 3, QTableWidgetItem(f"{saved_pct:.0f}%"))
            except Exception as e:
                failed_count += 1
                self.results_table.setItem(row, 2, QTableWidgetItem("Помилка"))
                self.results_table.setItem(row, 3, QTableWidgetItem(str(e)[:40]))

            self.progress_bar.setValue(idx + 1)
            QApplication.processEvents()

        msg = f"Обробку завершено!\n\nОброблено файлів: {processed_count}"
        if failed_count:
            msg += f"\nПомилок: {failed_count}"
        if total_original:
            saved_pct = (1 - total_new / total_original) * 100
            msg += (
                f"\n\nЗагальний розмір: {format_size(total_original)} → {format_size(total_new)}"
                f"\nЕкономія: {saved_pct:.0f}%"
            )
        msg += f"\n\nФайли збережено у:\n{output_dir}"

        QMessageBox.information(self, "Успішно!", msg)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = PDFBatchCompressorWidget()
    window.resize(1280, 800)
    window.show()
    sys.exit(app.exec_())
