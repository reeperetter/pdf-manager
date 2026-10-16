"""
Спільні елементи "плиткового" екрана: картка інструменту (ToolCard) і
адаптивна сітка карток (TileGrid).

Використовуються і головним екраном (hub_window.py), і екраном вкладки
"Конвертація" (modules/pdf_convert/convert_hub.py) - обидва виглядають і
поводяться однаково: картки розкладаються сіткою, рівномірно заповнюють
вільне місце й перебудовуються при зміні розміру вікна (більше колонок на
широкому екрані, менше - на вузькому; якщо не вміщаються - з'являється
прокрутка).
"""
from PyQt5 import QtCore, QtWidgets

from theme import COLORS
from ui_icons import create_vector_icon


class ToolCard(QtWidgets.QFrame):
    """Клікабельна картка інструменту."""
    clicked = QtCore.pyqtSignal()

    def __init__(self, title, description, icon_type, stub=False, parent=None):
        super().__init__(parent)
        self.setObjectName("ToolCard")
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setMinimumHeight(170)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                           QtWidgets.QSizePolicy.Expanding)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        icon_label = QtWidgets.QLabel()
        icon_label.setObjectName("ToolCardIcon")
        icon_label.setPixmap(
            create_vector_icon(icon_type, COLORS["accent"], size=40).pixmap(40, 40))
        layout.addWidget(icon_label)

        title_label = QtWidgets.QLabel(title)
        title_label.setObjectName("ToolCardTitle")
        title_label.setWordWrap(True)
        layout.addWidget(title_label)

        desc_label = QtWidgets.QLabel(description)
        desc_label.setObjectName("ToolCardDesc")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        layout.addStretch()

        # Для ще не реалізованих інструментів замість "Відкрити" показуємо
        # приглушений напис - щоб було видно, що це заглушка.
        open_label = QtWidgets.QLabel("Незабаром" if stub else "Відкрити →")
        open_label.setObjectName("MutedLabel" if stub else "ToolCardOpen")
        layout.addWidget(open_label)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class TileGrid(QtWidgets.QScrollArea):
    """Адаптивна сітка карток.

    Кількість колонок залежить від ширини: стільки, скільки вміщається при
    мінімальній ширині картки (min_tile_width). Усі колонки й рядки
    однакові та розтягуються на весь доступний простір. Якщо картки не
    вміщаються по висоті - з'являється вертикальна прокрутка.
    """

    def __init__(self, cards, min_tile_width=280, spacing=20, parent=None):
        super().__init__(parent)
        self._cards = list(cards)
        self._min_tile_width = min_tile_width
        self._spacing = spacing
        self._cols = 0

        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.viewport().setAutoFillBackground(False)

        self._inner = QtWidgets.QWidget()
        self._inner.setObjectName("TileGridInner")
        self._inner.setAttribute(QtCore.Qt.WA_StyledBackground, False)
        self._grid = QtWidgets.QGridLayout(self._inner)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(spacing)
        self.setWidget(self._inner)

        for card in self._cards:
            card.setParent(self._inner)
        self._relayout(self._columns_for_width(self.viewport().width() or 1000))

    def _columns_for_width(self, width):
        cols = (width + self._spacing) // (self._min_tile_width + self._spacing)
        return max(1, min(len(self._cards), cols))

    def _relayout(self, cols):
        if cols == self._cols:
            return
        self._cols = cols
        while self._grid.count():
            self._grid.takeAt(0)
        rows = -(-len(self._cards) // cols)
        for i, card in enumerate(self._cards):
            self._grid.addWidget(card, i // cols, i % cols)
        # Рівномірне розтягування: усі використані колонки й рядки мають
        # однаковий коефіцієнт, невикористані (від попередньої розкладки) - 0.
        for c in range(max(cols, self._grid.columnCount())):
            self._grid.setColumnStretch(c, 1 if c < cols else 0)
        for r in range(max(rows, self._grid.rowCount())):
            self._grid.setRowStretch(r, 1 if r < rows else 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout(self._columns_for_width(self.viewport().width()))
