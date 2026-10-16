"""
Вкладка "Конвертація": екран-каталог конвертацій (такий самий плитковий, як
головний екран програми). Кожна плитка відкриває свій інструмент усередині
цієї ж вкладки, а кнопка "← Усі конвертації" повертає до каталогу.

Реалізовано поки що "Зображення → PDF"; решта плиток - заглушки (сторінка
"Незабаром"), щоб потім реалізовувати їх по одній: достатньо замінити
`None` у списку CONVERSIONS на функцію, що повертає віджет інструмента.
"""
from PyQt5 import QtCore, QtWidgets

from ui_tiles import TileGrid, ToolCard
from modules.pdf_image2pdf.image2pdf_widget import PDFImageToPdfWidget


# (ключ, назва, опис, іконка, фабрика віджета або None для заглушки)
CONVERSIONS = [
    ("img2pdf", "Зображення → PDF",
     "JPG, PNG, BMP, TIFF, WEBP в один PDF чи окремий PDF на кожне зображення.",
     "image", PDFImageToPdfWidget),
    ("pdf2img", "PDF → Зображення",
     "Кожна сторінка PDF окремим зображенням (PNG чи JPG).", "image", None),
    ("docx2pdf", "Word → PDF",
     "Документи DOCX у PDF зі збереженням оформлення.", "doc", None),
    ("pdf2docx", "PDF → Word",
     "PDF у редагований документ DOCX.", "doc", None),
    ("xlsx2pdf", "Excel → PDF",
     "Таблиці XLSX у PDF.", "sheet", None),
    ("pdf2xlsx", "PDF → Excel",
     "Таблиці з PDF у файл XLSX.", "sheet", None),
    ("pptx2pdf", "PowerPoint → PDF",
     "Презентації PPTX у PDF.", "slides", None),
    ("pdf2pptx", "PDF → PowerPoint",
     "Сторінки PDF у слайди презентації PPTX.", "slides", None),
    ("txt2pdf", "Текст → PDF",
     "Звичайні текстові файли TXT у PDF.", "text", None),
    ("pdf2txt", "PDF → Текст",
     "Текст із PDF у файл TXT.", "text", None),
]


class StubPage(QtWidgets.QWidget):
    """Сторінка-заглушка для конвертації, яка ще не реалізована."""

    def __init__(self, title, description, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setAlignment(QtCore.Qt.AlignCenter)
        heading = QtWidgets.QLabel(title)
        heading.setObjectName("HomeTitle")
        heading.setAlignment(QtCore.Qt.AlignCenter)
        text = QtWidgets.QLabel(description + "\n\nЦя конвертація ще в розробці.")
        text.setObjectName("HomeSubtitle")
        text.setAlignment(QtCore.Qt.AlignCenter)
        text.setWordWrap(True)
        layout.addWidget(heading)
        layout.addWidget(text)


class ToolPageFrame(QtWidgets.QWidget):
    """Обгортка сторінки інструмента: зверху кнопка "назад" і назва."""

    def __init__(self, title, content, on_back, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 0)
        layout.setSpacing(4)
        header = QtWidgets.QHBoxLayout()
        back = QtWidgets.QPushButton("← Усі конвертації")
        back.setObjectName("BtnSecondary")
        back.setCursor(QtCore.Qt.PointingHandCursor)
        back.clicked.connect(on_back)
        header.addWidget(back)
        label = QtWidgets.QLabel(title)
        label.setObjectName("ToolCardTitle")
        header.addWidget(label)
        header.addStretch(1)
        layout.addLayout(header)
        layout.addWidget(content, 1)


class ConvertHubWidget(QtWidgets.QWidget):
    """Вкладка "Конвертація": каталог плиток + сторінки інструментів."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.stack = QtWidgets.QStackedWidget()
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.stack)

        # ---- Каталог ----
        home = QtWidgets.QWidget()
        home_layout = QtWidgets.QVBoxLayout(home)
        home_layout.setContentsMargins(40, 40, 40, 40)
        home_layout.setSpacing(20)
        title = QtWidgets.QLabel("Конвертація")
        title.setObjectName("HomeTitle")
        home_layout.addWidget(title)
        subtitle = QtWidgets.QLabel("Оберіть, що у що потрібно перетворити")
        subtitle.setObjectName("HomeSubtitle")
        home_layout.addWidget(subtitle)
        home_layout.addSpacing(10)

        self.stack.addWidget(home)

        self.pages = {}
        cards = []
        for key, name, desc, icon, factory in CONVERSIONS:
            content = factory() if factory else StubPage(name, desc)
            page = ToolPageFrame(name, content, self.show_home)
            self.stack.addWidget(page)
            self.pages[key] = page

            card = ToolCard(name, desc, icon, stub=factory is None)
            card.clicked.connect(lambda k=key: self.open_tool(k))
            cards.append(card)

        home_layout.addWidget(TileGrid(cards, min_tile_width=250), 1)

    def open_tool(self, key):
        self.stack.setCurrentWidget(self.pages[key])

    def show_home(self):
        self.stack.setCurrentIndex(0)
