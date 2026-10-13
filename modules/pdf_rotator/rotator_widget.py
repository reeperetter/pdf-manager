"""
Окремий інструмент "Поворот PDF" - пакетний поворот сторінок БЕЗ обрізки.

Раніше поворот жив усередині модуля обрізки (pdf_cropper) і ділив з ним
одну кнопку збереження - через це зберегти просто повернутий (без рамки
обрізки) файл було неможливо: процес обробки вимагав, щоб хоча б одному
файлу була задана рамка обрізки, інакше одразу показував помилку "Ви не
задали рамку обрізки жодному файлу!" і зупинявся, навіть якщо
користувачу потрібен був лише поворот. Цей модуль - самостійний
інструмент зі своєю вкладкою: кожен файл просто зберігається з тим
кутом повороту, який для нього виставлено (за замовчуванням 0° -
тобто без змін), без жодної залежності від рамки обрізки.
"""
import os
import sys

import pymupdf as fitz
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QFileDialog,
    QMessageBox, QLabel, QProgressBar, QSplitter, QLineEdit, QListWidget,
    QGraphicsScene, QGraphicsView, QGraphicsPixmapItem, QStyle
)
from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import QBrush, QColor, QPixmap, QImage, QTransform

from theme import COLORS


class RotatorDropListWidget(QListWidget):
    """Список файлів з підтримкою Drag-and-Drop для модуля повороту."""

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.owner = owner
        self.setAcceptDrops(True)

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


class PDFBatchRotatorWidget(QWidget):
    """Пакетний поворот сторінок PDF-файлів на 90°/180°/270°."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.doc = None
        self.current_page_idx = 0
        self.scale_factor = 2.0

        self.file_list_paths = []
        self.file_rotations = {}

        self.init_ui()

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

        self.file_list_widget = RotatorDropListWidget(self)
        self.file_list_widget.currentRowChanged.connect(self.on_file_selected)

        btn_apply_all = QPushButton(" Застосувати поворот до всіх файлів")
        btn_apply_all.setIcon(self.get_style_icon(QStyle.SP_DialogApplyButton))
        btn_apply_all.setMinimumHeight(32)
        btn_apply_all.clicked.connect(self.apply_rotation_to_all_files)

        left_layout.addWidget(btn_add_files)
        left_layout.addWidget(btn_clear_list)
        left_layout.addWidget(QLabel("Файли (перетягніть PDF сюди):"))
        left_layout.addWidget(self.file_list_widget)
        left_layout.addWidget(btn_apply_all)
        left_panel.setLayout(left_layout)

        right_panel = QWidget()
        right_layout = QVBoxLayout()

        nav_layout = QHBoxLayout()
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(6)

        self.btn_prev = QPushButton("Назад")
        self.btn_prev.setIcon(self.get_style_icon(QStyle.SP_ArrowLeft))
        self.btn_prev.clicked.connect(self.prev_page)
        self.btn_prev.setEnabled(False)

        self.btn_next = QPushButton("Вперед")
        self.btn_next.setIcon(self.get_style_icon(QStyle.SP_ArrowRight))
        self.btn_next.clicked.connect(self.next_page)
        self.btn_next.setEnabled(False)

        self.page_label = QLabel("Сторінка: 0 / 0")

        btn_rot_left = QPushButton("-90°")
        btn_rot_left.setIcon(self.get_style_icon(QStyle.SP_ArrowBack))
        btn_rot_left.clicked.connect(lambda: self.rotate_current(-90))

        btn_rot_right = QPushButton("+90°")
        btn_rot_right.setIcon(self.get_style_icon(QStyle.SP_ArrowForward))
        btn_rot_right.clicked.connect(lambda: self.rotate_current(90))

        btn_rot_reset = QPushButton("Скинути поворот")
        btn_rot_reset.setIcon(self.get_style_icon(QStyle.SP_DialogDiscardButton))
        btn_rot_reset.clicked.connect(self.reset_rotation_for_current)

        self.rotation_label = QLabel("Поворот: 0°")
        self.rotation_label.setObjectName("MutedLabel")

        nav_layout.addWidget(self.btn_prev)
        nav_layout.addWidget(self.page_label)
        nav_layout.addWidget(self.btn_next)
        nav_layout.addWidget(btn_rot_left)
        nav_layout.addWidget(btn_rot_right)
        nav_layout.addWidget(btn_rot_reset)
        nav_layout.addWidget(self.rotation_label)
        nav_layout.addStretch()

        self.scene = QGraphicsScene(self)
        self.view = QGraphicsView(self.scene, self)
        self.view.setObjectName("PagePreview")
        self.view.setBackgroundBrush(QBrush(QColor(COLORS["preview_bg"])))

        save_options_layout = QHBoxLayout()
        save_options_layout.addWidget(QLabel("Префікс збереження:"))
        self.txt_prefix = QLineEdit("rotated_")
        self.txt_prefix.setFixedWidth(120)
        save_options_layout.addWidget(self.txt_prefix)
        save_options_layout.addStretch()

        bottom_layout = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)

        self.btn_process_batch = QPushButton("Пакетний поворот усіх файлів")
        self.btn_process_batch.setIcon(self.get_style_icon(QStyle.SP_DialogSaveButton))
        self.btn_process_batch.setMinimumHeight(35)
        self.btn_process_batch.setObjectName("BtnPrimary")
        self.btn_process_batch.clicked.connect(self.process_batch_rotate)

        bottom_layout.addWidget(self.progress_bar)
        bottom_layout.addWidget(self.btn_process_batch)

        right_layout.addLayout(nav_layout)
        right_layout.addWidget(self.view)
        right_layout.addLayout(save_options_layout)
        right_layout.addLayout(bottom_layout)
        right_panel.setLayout(right_layout)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([320, 960])

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(splitter)
        main_layout.setContentsMargins(4, 4, 4, 4)

    def update_list_item_text(self, index):
        if index < 0 or index >= len(self.file_list_paths):
            return
        file_path = self.file_list_paths[index]
        filename = os.path.basename(file_path)
        rot = self.file_rotations.get(file_path, 0)
        suffix = f" [{rot}°]" if rot else ""
        self.file_list_widget.item(index).setText(f"{filename}{suffix}")

    def append_files(self, files):
        for file_path in files:
            if file_path not in self.file_list_paths:
                self.file_list_paths.append(file_path)
                self.file_list_widget.addItem("")
                self.update_list_item_text(len(self.file_list_paths) - 1)

        if self.file_list_widget.currentRow() == -1 and self.file_list_paths:
            self.file_list_widget.setCurrentRow(0)

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Виберіть PDF-файли", "", "PDF Files (*.pdf)")
        if files:
            self.append_files(files)

    def clear_file_list(self):
        self.file_list_paths.clear()
        self.file_rotations.clear()
        self.file_list_widget.clear()
        self.scene.clear()
        if self.doc:
            self.doc.close()
            self.doc = None
        self.page_label.setText("Сторінка: 0 / 0")
        self.rotation_label.setText("Поворот: 0°")
        self.btn_prev.setEnabled(False)
        self.btn_next.setEnabled(False)

    def on_file_selected(self, index):
        if index < 0 or index >= len(self.file_list_paths):
            return

        if self.doc:
            self.doc.close()

        file_path = self.file_list_paths[index]
        self.doc = fitz.open(file_path)
        self.current_page_idx = 0
        self.show_page(self.current_page_idx)

    def show_page(self, page_num):
        if not self.doc:
            return

        idx = self.file_list_widget.currentRow()
        file_path = self.file_list_paths[idx] if idx >= 0 else None

        self.scene.clear()
        self.scene.setBackgroundBrush(QBrush(QColor(COLORS["preview_bg"])))

        page = self.doc[page_num]

        # file_rotations зберігає ВІДНОСНИЙ зсув (те, на скільки градусів
        # користувач докрутив кнопками -90°/+90°), а не абсолютний кут.
        # native_rotation - це /Rotate, який уже був у самому PDF (типово
        # 0, але деякі скани приходять із власним поворотом). Якщо брати
        # лише offset як абсолютне значення (page.set_rotation(offset)),
        # для файлу з ненульовим native_rotation кнопка "+90°" могла б
        # візуально нічого не змінити (чи навіть "повернути назад") -
        # адже встановила б абсолютний кут замість повороту від поточного
        # вигляду. Складаємо обидва значення, щоб кнопки завжди крутили
        # ВІД того, що зараз показано на екрані.
        native_rotation = page.rotation
        offset = self.file_rotations.get(file_path, 0) if file_path else 0
        effective_rotation = (native_rotation + offset) % 360
        if offset:
            page.set_rotation(effective_rotation)

        matrix = fitz.Matrix(self.scale_factor, self.scale_factor)
        pix = page.get_pixmap(matrix=matrix)

        image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(image)

        pixmap_item = QGraphicsPixmapItem(pixmap)
        self.scene.addItem(pixmap_item)
        self.scene.setSceneRect(QRectF(pixmap.rect()))

        self.page_label.setText(f"Сторінка: {page_num + 1} / {len(self.doc)}")
        self.rotation_label.setText(f"Поворот: {offset}°")
        self.btn_prev.setEnabled(page_num > 0)
        self.btn_next.setEnabled(page_num < len(self.doc) - 1)

        if not self.scene.sceneRect().isEmpty():
            self.view.setTransform(QTransform())
            self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)

    def prev_page(self):
        if self.doc and self.current_page_idx > 0:
            self.current_page_idx -= 1
            self.show_page(self.current_page_idx)

    def next_page(self):
        if self.doc and self.current_page_idx < len(self.doc) - 1:
            self.current_page_idx += 1
            self.show_page(self.current_page_idx)

    def rotate_current(self, angle):
        idx = self.file_list_widget.currentRow()
        if idx < 0 or idx >= len(self.file_list_paths):
            QMessageBox.warning(self, "Увага", "Спочатку виберіть документ зі списку!")
            return

        file_path = self.file_list_paths[idx]
        curr_rot = self.file_rotations.get(file_path, 0)
        new_rot = (curr_rot + angle) % 360
        self.file_rotations[file_path] = new_rot
        self.update_list_item_text(idx)
        self.show_page(self.current_page_idx)

    def reset_rotation_for_current(self):
        idx = self.file_list_widget.currentRow()
        if idx < 0 or idx >= len(self.file_list_paths):
            return
        file_path = self.file_list_paths[idx]
        self.file_rotations.pop(file_path, None)
        self.update_list_item_text(idx)
        self.show_page(self.current_page_idx)

    def apply_rotation_to_all_files(self):
        idx = self.file_list_widget.currentRow()
        if idx < 0 or idx >= len(self.file_list_paths):
            QMessageBox.warning(self, "Увага", "Виберіть документ!")
            return

        curr_path = self.file_list_paths[idx]
        current_rot = self.file_rotations.get(curr_path, 0)

        for i, path in enumerate(self.file_list_paths):
            self.file_rotations[path] = current_rot
            self.update_list_item_text(i)

        QMessageBox.information(self, "Успішно", "Кут повороту застосовано до всіх файлів у списку!")

    def process_batch_rotate(self):
        self.btn_process_batch.setEnabled(False)
        try:
            self._process_batch_rotate_impl()
        finally:
            self.btn_process_batch.setEnabled(True)

    def _process_batch_rotate_impl(self):
        if not self.file_list_paths:
            QMessageBox.warning(self, "Помилка", "Список файлів порожній!")
            return

        # На відміну від модуля обрізки, тут НЕМАЄ вимоги "хоча б один
        # файл повинен мати явно заданий поворот" - якщо жоден файл не
        # повернуто, це просто означає "зберегти файли без змін", що є
        # цілком legitimate результатом цього інструмента (наприклад,
        # користувач повернув лише частину файлів зі списку, а решту
        # свідомо лишив як є). Попереджаємо про це лише інформативно,
        # не блокуючи обробку.
        if not any(self.file_rotations.get(p, 0) for p in self.file_list_paths):
            choice = QMessageBox.question(
                self, "Жоден файл не повернуто",
                "Жодному файлу зі списку не задано кут повороту - усі файли "
                "будуть збережені без змін орієнтації.\n\nПродовжити?",
                QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Yes,
            )
            if choice != QMessageBox.Yes:
                return

        output_dir = QFileDialog.getExistingDirectory(self, "Виберіть папку для збереження")
        if not output_dir:
            return

        prefix = self.txt_prefix.text().strip()
        total_files = len(self.file_list_paths)
        self.progress_bar.setMaximum(total_files)
        self.progress_bar.setValue(0)

        if self.doc:
            self.doc.close()
            self.doc = None

        processed_count = 0
        failed_files = []
        used_out_paths = set()

        for idx, file_path in enumerate(self.file_list_paths):
            rotation = self.file_rotations.get(file_path, 0)

            try:
                src_doc = fitz.open(file_path)
                if rotation:
                    for page in src_doc:
                        page.set_rotation((page.rotation + rotation) % 360)

                filename = os.path.basename(file_path)
                stem, ext = os.path.splitext(filename)
                out_path = os.path.join(output_dir, f"{prefix}{stem}{ext}")

                dup_counter = 1
                while out_path in used_out_paths or os.path.exists(out_path):
                    out_path = os.path.join(output_dir, f"{prefix}{stem}_{dup_counter}{ext}")
                    dup_counter += 1
                used_out_paths.add(out_path)

                src_doc.save(out_path, garbage=4, deflate=True)
                src_doc.close()

                processed_count += 1
            except Exception as e:
                failed_files.append((os.path.basename(file_path), str(e)))

            self.progress_bar.setValue(idx + 1)
            QApplication.processEvents()

        current_idx = self.file_list_widget.currentRow()
        if current_idx >= 0:
            self.on_file_selected(current_idx)

        msg = f"Обробку завершено!\n\nЗбережено файлів: {processed_count}"
        if failed_files:
            msg += f"\nПомилка обробки: {len(failed_files)}"
        msg += f"\n\nФайли збережено у:\n{output_dir}"

        if failed_files:
            shown = failed_files[:10]
            msg += "\n\nФайли з помилкою:\n" + "\n".join(
                f"  • {name}: {reason}" for name, reason in shown
            )
            if len(failed_files) > 10:
                msg += f"\n  … і ще {len(failed_files) - 10}"
            QMessageBox.warning(self, "Є файли з помилкою", msg)
        else:
            QMessageBox.information(self, "Успішно!", msg)


if __name__ == "__main__":
    from theme import apply_theme
    app = QApplication(sys.argv)
    apply_theme(app)
    window = PDFBatchRotatorWidget()
    window.resize(1280, 800)
    window.show()
    sys.exit(app.exec_())
