"""Графічні елементи рамки обрізки: ручки, прямокутник і перегляд сторінки."""
from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QBrush, QColor, QCursor, QPen
from PyQt5.QtWidgets import QGraphicsRectItem, QGraphicsView

from theme import COLORS, accent_qcolor


class HandleItem(QGraphicsRectItem):
    """Маркерна точка для зміни розмірів рамки."""
    def __init__(self, position_flags, parent=None):
        super().__init__(-5, -5, 10, 10, parent)
        self.position_flags = position_flags
        self.setPen(QPen(accent_qcolor(), 1.5))
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
        pen = QPen(accent_qcolor(), 2, Qt.DashLine)
        self.setPen(pen)
        brush = QBrush(accent_qcolor(30))
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

        self.setObjectName("PagePreview")
        self.setBackgroundBrush(QBrush(QColor(COLORS["preview_bg"])))

    def _get_cropper_widget(self):
        parent = self.parent()
        # Шукаємо вікно інструмента за ознакою (без імпорту - уникаємо циклу).
        while parent and not hasattr(parent, "process_batch_crop"):
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
