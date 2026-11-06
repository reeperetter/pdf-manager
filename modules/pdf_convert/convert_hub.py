"""
Вкладка "Конвертація": екран-каталог конвертацій (такий самий плитковий, як
головний екран програми). Кожна плитка відкриває свій інструмент усередині
цієї ж вкладки, а кнопка "← Усі конвертації" повертає до каталогу.

Усі конвертації реалізовано. Щоб додати нову: описати ConvertSpec (логіка -
у converters.py) і додати рядок у CONVERSIONS; None замість фабрики
залишає плитку-заглушку "Незабаром".
"""
from PyQt5 import QtCore, QtWidgets

from ui_tiles import TileGrid, ToolCard
from modules.pdf_image2pdf.image2pdf_widget import PDFImageToPdfWidget
from modules.pdf_convert import converters as cv
from modules.pdf_convert.convert_tool import ConvertSpec, ConvertToolWidget


def _tool(spec):
    """Фабрика віджета для ConvertSpec."""
    return lambda: ConvertToolWidget(spec)


_PDF = (".pdf",)
_Q_DPI = [(100, "100 (чернетка)"), (150, "150"), (200, "200"),
          (300, "300 (друк)"), (600, "600 (максимум)")]

SPEC_PDF2IMG = ConvertSpec(
    "pdf2img", "PDF → Зображення", _PDF, "png", cv.pdf_to_images,
    in_label="PDF-файли", multi_output=True,
    options=[("fmt", "Формат:", [("png", "PNG (без втрат)"), ("jpg", "JPG (менший розмір)")], "png"),
             ("dpi", "Роздільність (DPI):", _Q_DPI, 200)])
SPEC_DOCX2PDF = ConvertSpec(
    "docx2pdf", "Word → PDF", (".docx", ".doc", ".odt", ".rtf"), "pdf",
    cv.office_to_pdf, in_label="Документи Word")
SPEC_PDF2DOCX = ConvertSpec(
    "pdf2docx", "PDF → Word", _PDF, "docx", cv.pdf_to_docx, in_label="PDF-файли")
SPEC_XLSX2PDF = ConvertSpec(
    "xlsx2pdf", "Excel → PDF", (".xlsx", ".xls", ".ods", ".csv"), "pdf",
    cv.office_to_pdf, in_label="Таблиці Excel")
SPEC_PDF2XLSX = ConvertSpec(
    "pdf2xlsx", "PDF → Excel", _PDF, "xlsx", cv.pdf_to_xlsx, in_label="PDF-файли")
SPEC_PPTX2PDF = ConvertSpec(
    "pptx2pdf", "PowerPoint → PDF", (".pptx", ".ppt", ".odp"), "pdf",
    cv.office_to_pdf, in_label="Презентації")
SPEC_PDF2PPTX = ConvertSpec(
    "pdf2pptx", "PDF → PowerPoint", _PDF, "pptx", cv.pdf_to_pptx,
    in_label="PDF-файли",
    options=[("dpi", "Якість слайдів (DPI):", _Q_DPI[1:4], 150)])
SPEC_TXT2PDF = ConvertSpec(
    "txt2pdf", "Текст → PDF", (".txt",), "pdf", cv.txt_to_pdf,
    in_label="Текстові файли",
    options=[("fontsize", "Розмір шрифту:", [(10, "10"), (11, "11"), (12, "12"), (14, "14")], 11)])
SPEC_PDF2TXT = ConvertSpec(
    "pdf2txt", "PDF → Текст", _PDF, "txt", cv.pdf_to_txt, in_label="PDF-файли")


# (ключ, назва, опис, іконка, фабрика віджета або None для заглушки)
CONVERSIONS = [
    ("img2pdf", "Зображення → PDF",
     "JPG, PNG, BMP, TIFF, WEBP в один PDF чи окремий PDF на кожне зображення.",
     "image", PDFImageToPdfWidget),
    ("pdf2img", "PDF → Зображення",
     "Кожна сторінка PDF окремим зображенням (PNG чи JPG).", "image", _tool(SPEC_PDF2IMG)),
    ("docx2pdf", "Word → PDF",
     "Документи DOCX у PDF зі збереженням оформлення.", "doc", _tool(SPEC_DOCX2PDF)),
    ("pdf2docx", "PDF → Word",
     "PDF у редагований документ DOCX.", "doc", _tool(SPEC_PDF2DOCX)),
    ("xlsx2pdf", "Excel → PDF",
     "Таблиці XLSX у PDF.", "sheet", _tool(SPEC_XLSX2PDF)),
    ("pdf2xlsx", "PDF → Excel",
     "Таблиці з PDF у файл XLSX.", "sheet", _tool(SPEC_PDF2XLSX)),
    ("pptx2pdf", "PowerPoint → PDF",
     "Презентації PPTX у PDF.", "slides", _tool(SPEC_PPTX2PDF)),
    ("pdf2pptx", "PDF → PowerPoint",
     "Сторінки PDF у слайди презентації PPTX.", "slides", _tool(SPEC_PDF2PPTX)),
    ("txt2pdf", "Текст → PDF",
     "Звичайні текстові файли TXT у PDF.", "text", _tool(SPEC_TXT2PDF)),
    ("pdf2txt", "PDF → Текст",
     "Текст із PDF у файл TXT.", "text", _tool(SPEC_PDF2TXT)),
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
