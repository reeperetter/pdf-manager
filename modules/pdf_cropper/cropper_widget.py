import os
import sys
import pymupdf as fitz
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QFileDialog,
    QMessageBox, QLabel, QProgressBar, QSplitter, QComboBox,
    QLineEdit, QShortcut, QGraphicsScene, QGraphicsView,
    QGraphicsRectItem, QGraphicsItem, QGraphicsTextItem,
    QGraphicsPixmapItem, QListWidget, QListWidgetItem, QStyle
)
from PyQt5.QtCore import Qt, QRectF, QPointF
from PyQt5.QtGui import (
    QPen, QBrush, QColor, QCursor, QPixmap, QImage,
    QKeySequence, QTransform
)


class HandleItem(QGraphicsRectItem):
    """Маркерна точка для зміни розмірів рамки."""
    def __init__(self, position_flags, parent=None):
        super().__init__(-5, -5, 10, 10, parent)
        self.position_flags = position_flags
        self.setPen(QPen(QColor(0, 120, 215), 1.5))
        self.setBrush(QBrush(QColor(255, 255, 255)))
        self.setFlags(
            QGraphicsRectItem.ItemIsSelectable |
            QGraphicsRectItem.ItemIsMovable |
            QGraphicsRectItem.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.set_cursor()

    def set_cursor(self):
        flags = self.position_flags
        if flags in ("top_left", "bottom_right"):
            self.setCursor(QCursor(Qt.SizeFDiagCursor))
        elif flags in ("top_right", "bottom_left"):
            self.setCursor(QCursor(Qt.SizeBDiagCursor))
        elif flags in ("top", "bottom"):
            self.setCursor(QCursor(Qt.SizeVerCursor))
        elif flags in ("left", "right"):
            self.setCursor(QCursor(Qt.SizeHorCursor))

    def itemChange(self, change, value):
        if change == QGraphicsRectItem.ItemPositionChange and self.parentItem():
            self.parentItem().handle_moved(self, value)
        return super().itemChange(change, value)


class CropRectItem(QGraphicsRectItem):
    """Інтерактивна рамка з обмеженням межами сторінки."""
    def __init__(self, rect, parent=None):
        super().__init__(rect, parent)
        self.setFlags(
            QGraphicsRectItem.ItemIsSelectable |
            QGraphicsRectItem.ItemIsMovable |
            QGraphicsRectItem.ItemSendsGeometryChanges
        )
        pen = QPen(QColor(0, 120, 215), 2, Qt.DashLine)
        self.setPen(pen)
        brush = QBrush(QColor(0, 120, 215, 30))
        self.setBrush(brush)

        self.handles = {}
        self.create_handles()
        self.update_handles_positions()

    def create_handles(self):
        positions = ["top_left", "top", "top_right", "right", "bottom_right", "bottom", "bottom_left", "left"]
        for pos in positions:
            handle = HandleItem(pos, self)
            self.handles[pos] = handle

    def update_handles_positions(self):
        r = self.rect()
        positions = {
            "top_left": QPointF(r.left(), r.top()),
            "top": QPointF(r.center().x(), r.top()),
            "top_right": QPointF(r.right(), r.top()),
            "right": QPointF(r.right(), r.center().y()),
            "bottom_right": QPointF(r.right(), r.bottom()),
            "bottom": QPointF(r.center().x(), r.bottom()),
            "bottom_left": QPointF(r.left(), r.bottom()),
            "left": QPointF(r.left(), r.center().y())
        }
        for pos_flag, handle in self.handles.items():
            handle.setFlag(QGraphicsRectItem.ItemSendsGeometryChanges, False)
            handle.setPos(positions[pos_flag])
            handle.setFlag(QGraphicsRectItem.ItemSendsGeometryChanges, True)

    def setRect(self, rect):
        super().setRect(rect)
        self.update_handles_positions()

    def handle_moved(self, handle, new_pos):
        r = self.rect()
        pos_flag = handle.position_flags
        left, top, right, bottom = r.left(), r.top(), r.right(), r.bottom()

        bounds = self.scene().sceneRect() if self.scene() else QRectF(0, 0, 99999, 99999)

        if "left" in pos_flag:
            left = min(max(bounds.left(), new_pos.x()), right - 10)
        if "right" in pos_flag:
            right = max(min(bounds.right(), new_pos.x()), left + 10)
        if "top" in pos_flag:
            top = min(max(bounds.top(), new_pos.y()), bottom - 10)
        if "bottom" in pos_flag:
            bottom = max(min(bounds.bottom(), new_pos.y()), top + 10)

        new_rect = QRectF(QPointF(left, top), QPointF(right, bottom)).normalized()
        self.setRect(new_rect)


class PDFCropView(QGraphicsView):
    """Область перегляду."""
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.start_pos = None
        self.is_drawing = False

        self.setRenderHints(self.renderHints())
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)

        # Перекриваємо стиль переглядача та його viewport
        self.setStyleSheet("QGraphicsView { background-color: #d0d0d0; border: 1px solid #cccccc; }")
        self.setBackgroundBrush(QBrush(QColor(208, 208, 208)))

    def _get_cropper_widget(self):
        """Шукає батьківський віджет PDFBatchCropperWidget."""
        parent = self.parent()
        while parent and not isinstance(parent, PDFBatchCropperWidget):
            parent = parent.parent()
        return parent

    def wheelEvent(self, event):
        zoom_factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(zoom_factor, zoom_factor)

    def mousePressEvent(self, event):
        cropper = self._get_cropper_widget()

        if event.button() == Qt.MiddleButton:
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            fake_event = type(event)(
                event.type(), event.localPos(), event.windowPos(),
                event.screenPos(), Qt.LeftButton, event.buttons(), event.modifiers()
            )
            super().mousePressEvent(fake_event)
            return

        if event.button() == Qt.LeftButton:
            scene_pos = self.mapToScene(event.pos())
            bounds = self.scene().sceneRect()

            scene_pos.setX(min(max(bounds.left(), scene_pos.x()), bounds.right()))
            scene_pos.setY(min(max(bounds.top(), scene_pos.y()), bounds.bottom()))

            item = self.scene().itemAt(scene_pos, self.transform())

            if isinstance(item, (CropRectItem, HandleItem)):
                super().mousePressEvent(event)
            else:
                if cropper and cropper.crop_item:
                    self.scene().removeItem(cropper.crop_item)
                    cropper.crop_item = None

                self.start_pos = scene_pos
                crop_item = CropRectItem(QRectF(self.start_pos, self.start_pos))
                if cropper:
                    cropper.crop_item = crop_item
                self.scene().addItem(crop_item)
                self.is_drawing = True
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        cropper = self._get_cropper_widget()
        if self.is_drawing and cropper and cropper.crop_item:
            current_pos = self.mapToScene(event.pos())
            bounds = self.scene().sceneRect()

            cur_x = min(max(bounds.left(), current_pos.x()), bounds.right())
            cur_y = min(max(bounds.top(), current_pos.y()), bounds.bottom())

            rect = QRectF(self.start_pos, QPointF(cur_x, cur_y)).normalized()
            cropper.crop_item.setRect(rect)
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        cropper = self._get_cropper_widget()
        if event.button() == Qt.MiddleButton:
            fake_event = type(event)(
                event.type(), event.localPos(), event.windowPos(),
                event.screenPos(), Qt.LeftButton, event.buttons(), event.modifiers()
            )
            super().mouseReleaseEvent(fake_event)
            self.setDragMode(QGraphicsView.NoDrag)
            return

        if event.button() == Qt.LeftButton:
            if self.is_drawing:
                self.is_drawing = False
            if cropper:
                cropper.save_current_file_crop()

        super().mouseReleaseEvent(event)


class DropListWidget(QListWidget):
    """Список файлів з підтримкою Drag-and-Drop."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def _get_cropper_widget(self):
        parent = self.parent()
        while parent and not isinstance(parent, PDFBatchCropperWidget):
            parent = parent.parent()
        return parent

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
            files = [url.toLocalFile() for url in event.mimeData().urls() if url.toLocalFile().lower().endswith('.pdf')]
            cropper = self._get_cropper_widget()
            if files and cropper:
                cropper.append_files(files)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


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

    def init_ui(self):
        left_panel = QWidget()
        left_layout = QVBoxLayout()

        btn_add_files = QPushButton("➕ Додати PDF (Ctrl+O)")
        btn_add_files.clicked.connect(self.add_files)

        btn_clear_list = QPushButton("🗑 Очистити список")
        btn_clear_list.clicked.connect(self.clear_file_list)

        self.file_list_widget = DropListWidget(self)
        self.file_list_widget.currentRowChanged.connect(self.on_file_selected)

        btn_apply_to_all = QPushButton("🌐 Застосувати рамку до ВСІХ")
        btn_apply_to_all.clicked.connect(self.apply_crop_to_all_files)

        left_layout.addWidget(btn_add_files)
        left_layout.addWidget(btn_clear_list)
        left_layout.addWidget(QLabel("Файли (перетягніть PDF сюди):"))
        left_layout.addWidget(self.file_list_widget)
        left_layout.addWidget(btn_apply_to_all)
        left_panel.setLayout(left_layout)

        right_panel = QWidget()
        right_layout = QVBoxLayout()

        nav_layout = QHBoxLayout()
        self.btn_prev = QPushButton("< Назад (←)")
        self.btn_prev.clicked.connect(self.prev_page)
        self.btn_prev.setEnabled(False)

        self.btn_next = QPushButton("Вперед (→)")
        self.btn_next.clicked.connect(self.next_page)
        self.btn_next.setEnabled(False)

        self.page_label = QLabel("Сторінка: 0 / 0")

        btn_rot_left = QPushButton("⟲ 90°")
        btn_rot_left.clicked.connect(lambda: self.rotate_page(-90))
        btn_rot_right = QPushButton("⟳ 90°")
        btn_rot_right.clicked.connect(lambda: self.rotate_page(90))

        self.combo_preset = QComboBox()
        self.combo_preset.addItems(["Власна рамка", "Пропорція A4", "Пропорція 16:9", "Пропорція 4:3", "Квадрат (1:1)"])
        self.combo_preset.currentIndexChanged.connect(self.apply_preset)

        btn_reset_zoom = QPushButton("🔍 Показати повністю")
        btn_reset_zoom.clicked.connect(self.reset_zoom)

        btn_clear_crop = QPushButton("❌ Видалити рамку (Del)")
        btn_clear_crop.clicked.connect(self.reset_crop_rect_for_current)

        nav_layout.addWidget(self.btn_prev)
        nav_layout.addWidget(self.page_label)
        nav_layout.addWidget(self.btn_next)
        nav_layout.addWidget(btn_rot_left)
        nav_layout.addWidget(btn_rot_right)
        nav_layout.addWidget(QLabel("Шаблон:"))
        nav_layout.addWidget(self.combo_preset)
        nav_layout.addWidget(btn_reset_zoom)
        nav_layout.addWidget(btn_clear_crop)
        nav_layout.addStretch()

        self.scene = QGraphicsScene(self)
        self.view = PDFCropView(self.scene, self)

        save_options_layout = QHBoxLayout()
        save_options_layout.addWidget(QLabel("Префікс збереження:"))
        self.txt_prefix = QLineEdit("cropped_")
        self.txt_prefix.setFixedWidth(120)
        save_options_layout.addWidget(self.txt_prefix)
        save_options_layout.addStretch()

        bottom_layout = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)

        btn_process_batch = QPushButton("⚙ Пакетна обрізка всіх файлів")
        btn_process_batch.setStyleSheet("background-color: #0078D7; color: white; font-weight: bold; padding: 8px;")
        btn_process_batch.clicked.connect(self.process_batch_crop)

        bottom_layout.addWidget(self.progress_bar)
        bottom_layout.addWidget(btn_process_batch)

        right_layout.addLayout(nav_layout)
        right_layout.addWidget(self.view)
        right_layout.addLayout(save_options_layout)
        right_layout.addLayout(bottom_layout)
        right_panel.setLayout(right_layout)

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([350, 930])

        main_layout = QVBoxLayout(self)
        main_layout.addWidget(splitter)
        main_layout.setContentsMargins(0, 0, 0, 0)

    def init_shortcuts(self):
        QShortcut(QKeySequence(Qt.Key_Left), self, self.prev_page)
        QShortcut(QKeySequence(Qt.Key_Right), self, self.next_page)
        QShortcut(QKeySequence(Qt.Key_Delete), self, self.reset_crop_rect_for_current)
        QShortcut(QKeySequence("Ctrl+O"), self, self.add_files)

    def update_list_item_text(self, index):
        file_path = self.file_list_paths[index]
        filename = os.path.basename(file_path)
        has_crop = index in self.file_crop_rects

        status_icon = "[ ✂ ]" if has_crop else "[   ]"
        self.file_list_widget.item(index).setText(f"{status_icon} {filename}")

    def save_current_file_crop(self):
        idx = self.file_list_widget.currentRow()
        if idx < 0 or not self.crop_item:
            return

        rect = self.crop_item.rect()
        pos = self.crop_item.pos()

        x1 = (rect.x() + pos.x()) / self.scale_factor
        y1 = (rect.y() + pos.y()) / self.scale_factor
        x2 = x1 + (rect.width() / self.scale_factor)
        y2 = y1 + (rect.height() / self.scale_factor)

        self.file_crop_rects[idx] = fitz.Rect(x1, y1, x2, y2)
        self.update_list_item_text(idx)

    def restore_crop_item_for_current(self):
        idx = self.file_list_widget.currentRow()
        if idx not in self.file_crop_rects:
            return

        saved_rect = self.file_crop_rects[idx]
        x1 = saved_rect.x0 * self.scale_factor
        y1 = saved_rect.y0 * self.scale_factor
        width = (saved_rect.x1 - saved_rect.x0) * self.scale_factor
        height = (saved_rect.y1 - saved_rect.y0) * self.scale_factor

        self.crop_item = CropRectItem(QRectF(x1, y1, width, height))
        self.scene.addItem(self.crop_item)

    def apply_crop_to_all_files(self):
        idx = self.file_list_widget.currentRow()
        if idx not in self.file_crop_rects:
            QMessageBox.warning(self, "Увага", "Спочатку намалюйте рамку для поточного документа!")
            return

        current_rect = self.file_crop_rects[idx]
        for i in range(len(self.file_list_paths)):
            self.file_crop_rects[i] = fitz.Rect(current_rect)
            self.update_list_item_text(i)

        QMessageBox.information(self, "Успішно", "Параметри рамки застосовано до всіх файлів у списку!")

    def rotate_page(self, angle):
        if not self.doc:
            return
        page = self.doc[self.current_page_idx]
        page.set_rotation((page.rotation + angle) % 360)
        self.show_page(self.current_page_idx)

    def apply_preset(self, index):
        if not self.scene or self.scene.sceneRect().isEmpty() or index == 0:
            return

        bounds = self.scene.sceneRect()
        bw, bh = bounds.width(), bounds.height()

        ratios = {1: 1 / 1.414, 2: 16 / 9, 3: 4 / 3, 4: 1.0}
        target_ratio = ratios.get(index)

        if not target_ratio:
            return

        new_w = bw * 0.8
        new_h = new_w / target_ratio

        if new_h > bh:
            new_h = bh * 0.8
            new_w = new_h * target_ratio

        x = (bw - new_w) / 2
        y = (bh - new_h) / 2

        if self.crop_item:
            self.scene.removeItem(self.crop_item)

        self.crop_item = CropRectItem(QRectF(x, y, new_w, new_h))
        self.scene.addItem(self.crop_item)
        self.save_current_file_crop()

    def reset_crop_rect_for_current(self):
        idx = self.file_list_widget.currentRow()
        if idx in self.file_crop_rects:
            del self.file_crop_rects[idx]
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
        self.doc = fitz.open(file_path)
        self.current_page_idx = 0
        self.show_page(self.current_page_idx)

    def show_page(self, page_num):
        if not self.doc:
            return

        self.scene.clear()
        # Повторно задаємо колір після clear(), щоб запобігти злітанню в системний темний
        self.scene.setBackgroundBrush(QBrush(QColor(230, 230, 230)))
        self.crop_item = None

        page = self.doc[page_num]

        matrix = fitz.Matrix(self.scale_factor, self.scale_factor)
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
        if not self.file_list_paths:
            QMessageBox.warning(self, "Помилка", "Список файлів порожній!")
            return

        if self.crop_item:
            self.save_current_file_crop()

        if not self.file_crop_rects:
            QMessageBox.warning(self, "Помилка", "Ви не задали рамку обрізки жодному файлу!")
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
        skipped_count = 0

        for idx, file_path in enumerate(self.file_list_paths):
            crop_rect_view = self.file_crop_rects.get(idx)

            if not crop_rect_view:
                skipped_count += 1
                self.progress_bar.setValue(idx + 1)
                continue

            try:
                src_doc = fitz.open(file_path)

                for page in src_doc:
                    derot = page.derotation_matrix
                    real_crop_rect = crop_rect_view * derot
                    page.set_cropbox(real_crop_rect)

                filename = os.path.basename(file_path)
                out_path = os.path.join(output_dir, f"{prefix}{filename}")

                src_doc.save(out_path, garbage=4, deflate=True)
                src_doc.close()

                processed_count += 1
            except Exception as e:
                print(f"Помилка обробки {file_path}: {e}")

            self.progress_bar.setValue(idx + 1)
            QApplication.processEvents()

        current_idx = self.file_list_widget.currentRow()
        if current_idx >= 0:
            self.on_file_selected(current_idx)

        msg = f"Обробку завершено!\n\nОброблено файлів: {processed_count}"
        if skipped_count > 0:
            msg += f"\nПропущено: {skipped_count}"
        msg += f"\n\nФайли збережено у:\n{output_dir}"

        QMessageBox.information(self, "Успішно!", msg)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = PDFBatchCropperWidget()
    window.resize(1280, 800)
    window.show()
    sys.exit(app.exec_())