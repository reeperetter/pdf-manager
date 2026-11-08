import os
import sys
import pymupdf
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QFileDialog,
    QMessageBox, QLabel, QProgressBar, QSplitter,
    QLineEdit, QShortcut, QGraphicsScene, QGraphicsPixmapItem, QStyle
)
from PyQt5.QtCore import Qt, QRectF
from PyQt5.QtGui import (
    QBrush, QColor, QPixmap, QImage,
    QKeySequence, QTransform
)

from theme import COLORS
from modules.common.batch_runner import BatchRunner
from modules.common.file_list import DropFileList
from modules.common.outputs import resolve_output_path
from modules.pdf_cropper.crop_view import CropRectItem, PDFCropView
from ui_batch_extras import BatchExtras

# Цей модуль відповідає ЛИШЕ за обрізку (рамку). Поворот сторінок - окремий
# інструмент, modules/pdf_rotator/rotator_widget.py: раніше обидві функції
# жили в одному вікні, і через це поворот не можна було зберегти без того,
# щоб спочатку намалювати рамку обрізки (process_batch_crop вимагав
# file_crop_rects для будь-якого запису у вихідний файл). Розділення на дві
# окремі вкладки прибирає цю штучну залежність.


class PDFBatchCropperWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.doc = None
        self.current_page_idx = 0
        self.scale_factor = 2.0

        self.file_list_paths = []
        self.file_crop_rects = {}
        self.crop_item = None

        self.init_ui()
        self.init_shortcuts()

    def get_style_icon(self, standard_pixmap):
        return self.style().standardIcon(standard_pixmap)

    def init_ui(self):
        left_panel = QWidget()
        left_layout = QVBoxLayout()
        left_layout.setSpacing(6)

        btn_add_files = QPushButton("Додати PDF (Ctrl+O)")
        btn_add_files.setIcon(self.get_style_icon(QStyle.SP_DialogOpenButton))
        btn_add_files.setMinimumHeight(32)
        btn_add_files.clicked.connect(self.add_files)

        btn_clear_list = QPushButton("Очистити список")
        btn_clear_list.setIcon(self.get_style_icon(QStyle.SP_TrashIcon))
        btn_clear_list.setMinimumHeight(30)
        btn_clear_list.clicked.connect(self.clear_file_list)

        self.file_list_widget = DropFileList(self)
        self.file_list_widget.currentRowChanged.connect(self.on_file_selected)

        btn_apply_crop = QPushButton(" Застосувати рамку до всіх файлів")
        btn_apply_crop.setIcon(self.get_style_icon(QStyle.SP_FileDialogListView))
        btn_apply_crop.setMinimumHeight(32)
        btn_apply_crop.clicked.connect(self.apply_crop_to_all_files)

        self.extras = BatchExtras(self, "crop", self.append_files)

        left_layout.addWidget(btn_add_files)
        left_layout.addWidget(self.extras.recent_button)
        left_layout.addWidget(btn_clear_list)
        left_layout.addWidget(QLabel("Файли (перетягніть PDF сюди):"))
        left_layout.addWidget(self.file_list_widget)
        left_layout.addWidget(btn_apply_crop)
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

        btn_reset_zoom = QPushButton("Показати повністю")
        btn_reset_zoom.setIcon(self.get_style_icon(QStyle.SP_FileDialogDetailedView))
        btn_reset_zoom.clicked.connect(self.reset_zoom)

        btn_clear_crop = QPushButton("Видалити рамку")
        btn_clear_crop.setIcon(self.get_style_icon(QStyle.SP_DialogDiscardButton))
        btn_clear_crop.clicked.connect(self.reset_crop_rect_for_current)

        nav_layout.addWidget(self.btn_prev)
        nav_layout.addWidget(self.page_label)
        nav_layout.addWidget(self.btn_next)
        nav_layout.addWidget(btn_reset_zoom)
        nav_layout.addWidget(btn_clear_crop)
        nav_layout.addStretch()

        self.scene = QGraphicsScene(self)
        self.view = PDFCropView(self.scene, self)

        save_options_layout = QHBoxLayout()
        save_options_layout.addWidget(QLabel("Суфікс збереження:"))
        self.txt_suffix = QLineEdit("_cropped")
        self.txt_suffix.setFixedWidth(120)
        save_options_layout.addWidget(self.txt_suffix)
        save_options_layout.addSpacing(16)
        save_options_layout.addWidget(self.extras.skip_checkbox)
        save_options_layout.addStretch()

        bottom_layout = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)

        self.btn_process_batch = QPushButton("Пакетна обрізка всіх файлів")
        btn_process_batch = self.btn_process_batch
        btn_process_batch.setIcon(self.get_style_icon(QStyle.SP_DialogSaveButton))
        btn_process_batch.setMinimumHeight(35)
        btn_process_batch.setObjectName("BtnPrimary")
        btn_process_batch.clicked.connect(self.process_batch_crop)

        self.runner = BatchRunner(self, self.btn_process_batch, self.progress_bar)

        bottom_layout.addWidget(self.progress_bar)
        bottom_layout.addWidget(self.extras.open_button)
        bottom_layout.addWidget(self.runner.cancel_button)
        bottom_layout.addWidget(btn_process_batch)

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

    def init_shortcuts(self):
        QShortcut(QKeySequence(Qt.Key_Left), self, self.prev_page)
        QShortcut(QKeySequence(Qt.Key_Right), self, self.next_page)
        QShortcut(QKeySequence(Qt.Key_Delete), self, self.reset_crop_rect_for_current)
        QShortcut(QKeySequence("Ctrl+O"), self, self.add_files)

    def update_list_item_text(self, index):
        if index < 0 or index >= len(self.file_list_paths):
            return
        file_path = self.file_list_paths[index]
        filename = os.path.basename(file_path)
        has_crop = file_path in self.file_crop_rects

        status_icon = "[✂]" if has_crop else "[  ]"
        self.file_list_widget.item(index).setText(f"{status_icon} {filename}")

    def save_current_file_crop(self):
        idx = self.file_list_widget.currentRow()
        if idx < 0 or not self.crop_item or idx >= len(self.file_list_paths):
            return

        file_path = self.file_list_paths[idx]
        rect = self.crop_item.rect()
        pos = self.crop_item.pos()

        x1 = (rect.x() + pos.x()) / self.scale_factor
        y1 = (rect.y() + pos.y()) / self.scale_factor
        x2 = x1 + (rect.width() / self.scale_factor)
        y2 = y1 + (rect.height() / self.scale_factor)

        self.file_crop_rects[file_path] = pymupdf.Rect(x1, y1, x2, y2)
        self.update_list_item_text(idx)

    def restore_crop_item_for_current(self):
        idx = self.file_list_widget.currentRow()
        if idx < 0 or idx >= len(self.file_list_paths):
            return

        file_path = self.file_list_paths[idx]
        if file_path not in self.file_crop_rects:
            return

        saved_rect = self.file_crop_rects[file_path]
        x1 = saved_rect.x0 * self.scale_factor
        y1 = saved_rect.y0 * self.scale_factor
        width = (saved_rect.x1 - saved_rect.x0) * self.scale_factor
        height = (saved_rect.y1 - saved_rect.y0) * self.scale_factor

        self.crop_item = CropRectItem(QRectF(x1, y1, width, height))
        self.scene.addItem(self.crop_item)

    def apply_crop_to_all_files(self):
        """Застосовує поточну рамку обрізки до всіх файлів у списку."""
        idx = self.file_list_widget.currentRow()
        if idx < 0 or idx >= len(self.file_list_paths):
            QMessageBox.warning(self, "Увага", "Виберіть документ!")
            return

        curr_path = self.file_list_paths[idx]
        if curr_path not in self.file_crop_rects:
            QMessageBox.warning(self, "Увага", "Спочатку намалюйте рамку для поточного документа!")
            return

        current_rect = self.file_crop_rects[curr_path]
        for i, path in enumerate(self.file_list_paths):
            self.file_crop_rects[path] = pymupdf.Rect(current_rect)
            self.update_list_item_text(i)

        QMessageBox.information(self, "Успішно", "Рамку обрізки застосовано до всіх файлів у списку!")

    def reset_crop_rect_for_current(self):
        idx = self.file_list_widget.currentRow()
        if idx >= 0 and idx < len(self.file_list_paths):
            file_path = self.file_list_paths[idx]
            if file_path in self.file_crop_rects:
                del self.file_crop_rects[file_path]
                self.update_list_item_text(idx)

        if self.crop_item:
            self.scene.removeItem(self.crop_item)
            self.crop_item = None

    def append_files(self, files):
        for file_path in files:
            if file_path not in self.file_list_paths:
                self.file_list_paths.append(file_path)
                self.file_list_widget.addItem("")
                self.update_list_item_text(len(self.file_list_paths) - 1)
                self.extras.remember([file_path])

        if self.file_list_widget.currentRow() == -1 and self.file_list_paths:
            self.file_list_widget.setCurrentRow(0)

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Виберіть PDF-файли", "", "PDF Files (*.pdf)")
        if files:
            self.append_files(files)

    def clear_file_list(self):
        self.file_list_paths.clear()
        self.file_crop_rects.clear()
        self.file_list_widget.clear()
        self.scene.clear()
        self.crop_item = None
        if self.doc:
            self.doc.close()
            self.doc = None
        self.page_label.setText("Сторінка: 0 / 0")
        self.btn_prev.setEnabled(False)
        self.btn_next.setEnabled(False)

    def on_file_selected(self, index):
        if index < 0 or index >= len(self.file_list_paths):
            return

        if self.doc:
            self.doc.close()

        file_path = self.file_list_paths[index]
        self.doc = pymupdf.open(file_path)
        self.current_page_idx = 0
        self.show_page(self.current_page_idx)

    def show_page(self, page_num):
        if not self.doc:
            return

        self.scene.clear()
        self.scene.setBackgroundBrush(QBrush(QColor(COLORS["preview_bg"])))
        self.crop_item = None

        page = self.doc[page_num]

        matrix = pymupdf.Matrix(self.scale_factor, self.scale_factor)
        pix = page.get_pixmap(matrix=matrix)

        image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(image)

        pixmap_item = QGraphicsPixmapItem(pixmap)
        self.scene.addItem(pixmap_item)
        self.scene.setSceneRect(QRectF(pixmap.rect()))

        self.restore_crop_item_for_current()

        self.page_label.setText(f"Сторінка: {page_num + 1} / {len(self.doc)}")
        self.btn_prev.setEnabled(page_num > 0)
        self.btn_next.setEnabled(page_num < len(self.doc) - 1)

        self.reset_zoom()

    def reset_zoom(self):
        if not self.scene.sceneRect().isEmpty():
            self.view.setTransform(QTransform())
            self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)

    def prev_page(self):
        if self.doc and self.current_page_idx > 0:
            if self.crop_item:
                self.save_current_file_crop()
            self.current_page_idx -= 1
            self.show_page(self.current_page_idx)

    def next_page(self):
        if self.doc and self.current_page_idx < len(self.doc) - 1:
            if self.crop_item:
                self.save_current_file_crop()
            self.current_page_idx += 1
            self.show_page(self.current_page_idx)

    def process_batch_crop(self):
        if self.runner.running:
            return
        self._process_batch_crop_impl()

    def _process_batch_crop_impl(self):
        if not self.file_list_paths:
            QMessageBox.warning(self, "Помилка", "Список файлів порожній!")
            return

        if self.crop_item:
            self.save_current_file_crop()

        if not self.file_crop_rects:
            QMessageBox.warning(self, "Помилка", "Ви не задали рамку обрізки жодному файлу!")
            return

        # Раніше тут була лише перевірка "словник НЕ ПОРОЖНІЙ" - вона
        # проходила, навіть якщо рамку намальовано лише на ОДНОМУ файлі
        # (а після додавання файлів автоматично вибирається перший). Решта
        # файлів без рамки потім мовчки пропускались у циклі нижче, і єдина
        # згадка про це - рядок "Пропущено: N" у фінальному вікні з
        # заголовком "Успішно!", який легко не помітити. Звідси й
        # враження "обробляється тільки перший файл, без жодної
        # закономірності" - насправді все залежало від того, чи встигли
        # задати рамку кожному файлу, просто про це ніхто не попереджав.
        missing_paths = [p for p in self.file_list_paths if p not in self.file_crop_rects]

        if missing_paths:
            idx = self.file_list_widget.currentRow()
            curr_path = self.file_list_paths[idx] if idx >= 0 else None
            source_rect = self.file_crop_rects.get(curr_path) if curr_path else None
            if source_rect is None:
                for p in self.file_list_paths:
                    if p in self.file_crop_rects:
                        source_rect = self.file_crop_rects[p]
                        break

            shown = [os.path.basename(p) for p in missing_paths[:10]]
            names_text = "\n".join(f"  • {n}" for n in shown)
            if len(missing_paths) > 10:
                names_text += f"\n  … і ще {len(missing_paths) - 10}"

            box = QMessageBox(self)
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("Не всім файлам задано рамку")
            box.setText(
                f"{len(missing_paths)} з {len(self.file_list_paths)} файлів ще не мають "
                f"рамки обрізки:\n\n{names_text}\n\n"
                "Застосувати до них ту саму рамку, що й у поточного файлу, "
                "чи пропустити ці файли при обробці?"
            )
            btn_apply = box.addButton("Застосувати рамку до них", QMessageBox.AcceptRole)
            btn_skip = box.addButton("Пропустити ці файли", QMessageBox.DestructiveRole)
            btn_cancel = box.addButton("Скасувати", QMessageBox.RejectRole)
            btn_apply.setEnabled(source_rect is not None)
            box.setDefaultButton(btn_apply if source_rect is not None else btn_skip)
            box.exec_()

            clicked = box.clickedButton()
            if clicked is btn_cancel:
                return
            if clicked is btn_apply and source_rect is not None:
                for p in missing_paths:
                    self.file_crop_rects[p] = pymupdf.Rect(source_rect)
                    self.update_list_item_text(self.file_list_paths.index(p))

        output_dir = QFileDialog.getExistingDirectory(self, "Виберіть папку для збереження")
        if not output_dir:
            return

        self.extras.set_output_dir(output_dir)
        suffix = self.txt_suffix.text().strip()
        skip_existing = self.extras.skip_existing
        crop_rects = {p: pymupdf.Rect(r) for p, r in self.file_crop_rects.items()}
        # Імена виходу беруться з basename(file_path): файли з однаковою
        # назвою з різних тек не повинні перезаписувати один одного -
        # resolve_output_path додає "_1", "_2", ... при колізії.
        used_out_paths = set()

        if self.doc:
            self.doc.close()
            self.doc = None

        def work(file_path):
            """Фоновий потік: 'nocrop' / 'exists' / 'saved'."""
            crop_rect_view = crop_rects.get(file_path)
            if not crop_rect_view:
                return "nocrop"
            src_doc = pymupdf.open(file_path)
            try:
                for page in src_doc:
                    # Рамка, збережена через save_current_file_crop(), задана
                    # в системі координат ВІДОБРАЖЕННЯ сторінки - тобто тій,
                    # яку показує get_pixmap() і яка відповідає page.rect.
                    # Якщо сторінка вже має власний поворот (/Rotate !=0) -
                    # наприклад, файл перед цим пройшов через інструмент
                    # "Поворот сторінок", або це скан, що спочатку збережений
                    # повернутим, - page.rect відрізняється від page.mediabox
                    # (може бути навіть з переставленими шириною/висотою).
                    # set_cropbox() натомість завжди очікує прямокутник саме
                    # в системі координат НЕПОВЕРНУТОЇ page.mediabox.
                    # page.derotation_matrix - це перетворення "з екрана назад
                    # у mediabox": для файлів без повороту це одинична
                    # матриця (нічого не змінює - звідси й нормальна робота
                    # на неперевернутих файлах), а для вже повернутих файлів
                    # коректно компенсує поворот ПЕРЕД обрізкою. Без цього
                    # кроку рамка на повернутому файлі накладалась як є на
                    # mediabox іншої форми/орієнтації і відрізала забагато -
                    # так само, як і попередній баг із page.rect, лише тепер
                    # з протилежного боку перетворення.
                    real_crop_rect = pymupdf.Rect(crop_rect_view) * page.derotation_matrix

                    # Та сама (числова) рамка, намальована чи застосована
                    # по ОДНОМУ файлу, у іншого файлу може трохи виходити
                    # за межі його фактичної сторінки (інший розмір скану,
                    # інша орієнтація тощо) - PyMuPDF у такому разі кидає
                    # ValueError "CropBox not in MediaBox" і файл просто
                    # не зберігався. Обрізаємо рамку до меж сторінки, щоб
                    # такий файл усе одно оброблявся; якщо після цього
                    # рамка не лишає жодної площі - це вже справжня
                    # помилка, і про неї повідомляємо користувачу.
                    real_crop_rect &= page.mediabox
                    if real_crop_rect.is_empty or real_crop_rect.is_infinite:
                        raise ValueError(
                            "рамка обрізки повністю поза межами сторінки цього файлу"
                        )

                    page.set_cropbox(real_crop_rect)

                out_path = resolve_output_path(
                    output_dir, os.path.basename(file_path), suffix,
                    used_out_paths, skip_existing)
                if out_path is None:
                    return "exists"
                src_doc.save(out_path, garbage=4, deflate=True)
                return "saved"
            finally:
                src_doc.close()

        self.runner.start(
            self.file_list_paths, work,
            on_finished=lambda outcomes, cancelled: self._crop_finished(
                outcomes, cancelled, output_dir))

    def _crop_finished(self, outcomes, cancelled, output_dir):
        processed_count = sum(1 for o in outcomes if o.value == "saved")
        skipped_count = sum(1 for o in outcomes if o.value == "nocrop")
        existing_count = sum(1 for o in outcomes if o.value == "exists")
        # Помилки показуємо користувачу (в --windowed збірці консолі немає).
        failed_files = [(os.path.basename(o.item), o.error)
                        for o in outcomes if o.error]

        current_idx = self.file_list_widget.currentRow()
        if current_idx >= 0:
            self.on_file_selected(current_idx)

        head = "Обробку скасовано." if cancelled else "Обробку завершено!"
        msg = f"{head}\n\nОброблено файлів: {processed_count}"
        if skipped_count > 0:
            msg += f"\nПропущено (без рамки): {skipped_count}"
        if existing_count:
            msg += f"\nПропущено (вже є результат): {existing_count}"
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

        has_problems = skipped_count > 0 or bool(failed_files) or cancelled
        title = "Є пропущені або помилкові файли" if has_problems else "Успішно!"
        if has_problems:
            QMessageBox.warning(self, title, msg)
        else:
            QMessageBox.information(self, title, msg)


if __name__ == "__main__":
    from theme import apply_theme
    app = QApplication(sys.argv)
    apply_theme(app)
    window = PDFBatchCropperWidget()
    window.resize(1280, 800)
    window.show()
    sys.exit(app.exec_())
