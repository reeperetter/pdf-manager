from PyQt5 import QtCore, QtGui, QtWidgets

from ui_icons import create_vector_icon
from theme import COLORS
from ui_tiles import TileGrid, ToolCard
from modules.pdf_translator.ocr_widget import PDFOcrWidget
from modules.pdf_translator.translate_widget import PDFTranslateWidget
from modules.pdf_convert.convert_hub import ConvertHubWidget
from modules.pdf_cropper.cropper_widget import PDFBatchCropperWidget
from modules.pdf_rotator.rotator_widget import PDFBatchRotatorWidget
from modules.pdf_compressor.compressor_widget import PDFBatchCompressorWidget


class ModernSidebar(QtWidgets.QFrame):
    module_changed = QtCore.pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(240)
        self.setObjectName("Sidebar")
        self._init_ui()

    def _init_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 20, 12, 20)
        layout.setSpacing(10)

        logo_label = QtWidgets.QLabel("PDF Manager")
        logo_label.setObjectName("SidebarTitle")
        logo_label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(logo_label)

        sub_logo = QtWidgets.QLabel("Універсальний інструментарій")
        sub_logo.setObjectName("SidebarSubtitle")
        sub_logo.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(sub_logo)

        layout.addSpacing(25)

        self.btn_group = QtWidgets.QButtonGroup(self)
        self.btn_group.setExclusive(True)

        self.btn_home = self._create_nav_button("Головна", "home", 0)
        self.btn_ocr = self._create_nav_button("OCR (розпізнавання)", "ocr", 1)
        self.btn_translate = self._create_nav_button("Переклад PDF", "translate", 2)
        self.btn_convert = self._create_nav_button("Конвертація", "convert", 3)
        self.btn_crop = self._create_nav_button("Пакетна Обрізка", "crop", 4)
        self.btn_rotate = self._create_nav_button("Поворот сторінок", "rotate", 5)
        self.btn_compress = self._create_nav_button("Стиснення PDF", "compress", 6)

        layout.addWidget(self.btn_home)
        layout.addWidget(self.btn_ocr)
        layout.addWidget(self.btn_translate)
        layout.addWidget(self.btn_convert)
        layout.addWidget(self.btn_crop)
        layout.addWidget(self.btn_rotate)
        layout.addWidget(self.btn_compress)

        layout.addStretch()

        version_label = QtWidgets.QLabel("reeperetter")
        version_label.setObjectName("VersionLabel")
        version_label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(version_label)

        self.btn_home.setChecked(True)

    def set_checked_index(self, index):
        """Дозволяє зовнішньому коду (наприклад, картці на головній сторінці)
        візуально позначити відповідну кнопку в бічній панелі як активну."""
        btn = self.btn_group.button(index)
        if btn:
            btn.setChecked(True)

    def _create_nav_button(self, text, icon_type, index):
        btn = QtWidgets.QPushButton(text)
        btn.setIcon(create_vector_icon(icon_type, COLORS["text_heading"]))
        btn.setIconSize(QtCore.QSize(20, 20))
        btn.setCheckable(True)
        btn.setCursor(QtCore.Qt.PointingHandCursor)
        btn.setObjectName("NavButton")
        self.btn_group.addButton(btn, index)
        btn.clicked.connect(lambda: self.module_changed.emit(index))
        return btn


class HomePage(QtWidgets.QWidget):
    """Головна сторінка - вибір інструменту у вигляді карток."""
    tool_selected = QtCore.pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        outer_layout = QtWidgets.QVBoxLayout(self)
        outer_layout.setContentsMargins(40, 40, 40, 40)
        outer_layout.setSpacing(20)

        title = QtWidgets.QLabel("PDF Manager")
        title.setObjectName("HomeTitle")
        outer_layout.addWidget(title)

        subtitle = QtWidgets.QLabel("Оберіть інструмент, з яким хочете працювати")
        subtitle.setObjectName("HomeSubtitle")
        outer_layout.addWidget(subtitle)

        outer_layout.addSpacing(10)

        cards_info = [
            (1, "OCR (розпізнавання)", "Розпізнавання тексту у відсканованих PDF: PDF з виділюваним текстом та/або DOCX/TXT.", "ocr"),
            (2, "Переклад PDF", "Переклад PDF українською, російською чи англійською зі збереженням макета.", "translate"),
            (3, "Конвертація", "Зображення, Word, Excel, PowerPoint, текст у PDF і назад.", "convert"),
            (4, "Пакетна Обрізка", "Обрізка полів для декількох PDF-файлів одразу, за рамкою, яку ви задаєте.", "crop"),
            (5, "Поворот сторінок", "Пакетний поворот сторінок PDF-файлів на 90°/180°/270° без обрізки.", "rotate"),
            (6, "Стиснення PDF", "Зменшення розміру одного чи пакету PDF-файлів без відчутної втрати якості.", "compress"),
        ]

        cards = []
        for index, tool_title, tool_desc, icon_type in cards_info:
            card = ToolCard(tool_title, tool_desc, icon_type)
            card.clicked.connect(lambda idx=index: self.tool_selected.emit(idx))
            cards.append(card)

        # Картки розкладаються сіткою, рівномірно заповнюють екран і
        # перебудовуються при зміні розміру вікна.
        outer_layout.addWidget(TileGrid(cards, min_tile_width=300), 1)


class MainHubWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Manager")
        self.resize(1350, 880)
        self.setMinimumSize(1000, 650)

        self._init_ui()

    def _init_ui(self):
        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QtWidgets.QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.sidebar = ModernSidebar()
        self.sidebar.module_changed.connect(self.switch_module)
        main_layout.addWidget(self.sidebar)

        self.stack = QtWidgets.QStackedWidget()
        self.stack.setObjectName("ContentArea")

        self.ocr_widget = PDFOcrWidget()
        self.translate_widget = PDFTranslateWidget()
        self.convert_widget = ConvertHubWidget()
        self.cropper_widget = PDFBatchCropperWidget()
        self.rotator_widget = PDFBatchRotatorWidget()
        self.compressor_widget = PDFBatchCompressorWidget()

        self.home_page = HomePage()
        self.home_page.tool_selected.connect(self.go_to_module)

        self.stack.addWidget(self.home_page)
        self.stack.addWidget(self.ocr_widget)
        self.stack.addWidget(self.translate_widget)
        self.stack.addWidget(self.convert_widget)
        self.stack.addWidget(self.cropper_widget)
        self.stack.addWidget(self.rotator_widget)
        self.stack.addWidget(self.compressor_widget)

        main_layout.addWidget(self.stack, stretch=1)

    def switch_module(self, index):
        # Повторний клік на "Конвертація" у бічній панелі повертає до
        # каталогу конвертацій (так само, як "Головна" - на головну).
        if index == 3 and self.stack.currentIndex() == 3:
            self.convert_widget.show_home()
        self.stack.setCurrentIndex(index)

    def go_to_module(self, index):
        """Викликається при кліку на картку на головній сторінці:
        перемикає вміст і синхронізує вигляд бічної панелі."""
        self.stack.setCurrentIndex(index)
        self.sidebar.set_checked_index(index)

