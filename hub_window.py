from PyQt5 import QtCore, QtGui, QtWidgets

from ui_icons import create_vector_icon
from modules.pdf_translator.gui import MainWindow as PDFTranslatorWidget
from modules.pdf_cropper.cropper_widget import PDFBatchCropperWidget
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
        self.btn_ocr = self._create_nav_button("OCR та Переклад", "ocr", 1)
        self.btn_crop = self._create_nav_button("Пакетна Обрізка", "crop", 2)
        self.btn_compress = self._create_nav_button("Стиснення PDF", "compress", 3)

        layout.addWidget(self.btn_home)
        layout.addWidget(self.btn_ocr)
        layout.addWidget(self.btn_crop)
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
        btn.setIcon(create_vector_icon(icon_type, "#403831"))
        btn.setIconSize(QtCore.QSize(20, 20))
        btn.setCheckable(True)
        btn.setCursor(QtCore.Qt.PointingHandCursor)
        btn.setObjectName("NavButton")
        self.btn_group.addButton(btn, index)
        btn.clicked.connect(lambda: self.module_changed.emit(index))
        return btn


class ToolCard(QtWidgets.QFrame):
    """Клікабельна картка інструменту на головній сторінці."""
    clicked = QtCore.pyqtSignal()

    def __init__(self, title, description, icon_type, parent=None):
        super().__init__(parent)
        self.setObjectName("ToolCard")
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setMinimumHeight(180)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        icon_label = QtWidgets.QLabel()
        icon_label.setObjectName("ToolCardIcon")
        icon_label.setPixmap(create_vector_icon(icon_type, "#8C4A1B", size=40).pixmap(40, 40))
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

        open_label = QtWidgets.QLabel("Відкрити →")
        open_label.setObjectName("ToolCardOpen")
        layout.addWidget(open_label)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


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

        cards_layout = QtWidgets.QHBoxLayout()
        cards_layout.setSpacing(20)

        cards_info = [
            (1, "OCR та Переклад", "Розпізнавання тексту зі сканів та перекладених PDF, з підтримкою глосарію.", "ocr"),
            (2, "Пакетна Обрізка", "Обрізка полів і поворот сторінок одразу для декількох PDF-файлів.", "crop"),
            (3, "Стиснення PDF", "Зменшення розміру одного чи пакету PDF-файлів без відчутної втрати якості.", "compress"),
        ]

        for index, tool_title, tool_desc, icon_type in cards_info:
            card = ToolCard(tool_title, tool_desc, icon_type)
            card.clicked.connect(lambda idx=index: self.tool_selected.emit(idx))
            cards_layout.addWidget(card)

        outer_layout.addLayout(cards_layout)
        outer_layout.addStretch()


class MainHubWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Manager")
        self.resize(1350, 880)
        self.setMinimumSize(1000, 650)

        self._init_ui()
        self._apply_styles()

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

        self.translator_widget = PDFTranslatorWidget()
        self.cropper_widget = PDFBatchCropperWidget()
        self.compressor_widget = PDFBatchCompressorWidget()

        self.home_page = HomePage()
        self.home_page.tool_selected.connect(self.go_to_module)

        self.stack.addWidget(self.home_page)
        self.stack.addWidget(self.translator_widget)
        self.stack.addWidget(self.cropper_widget)
        self.stack.addWidget(self.compressor_widget)

        main_layout.addWidget(self.stack, stretch=1)

    def switch_module(self, index):
        self.stack.setCurrentIndex(index)

    def go_to_module(self, index):
        """Викликається при кліку на картку на головній сторінці:
        перемикає вміст і синхронізує вигляд бічної панелі."""
        self.stack.setCurrentIndex(index)
        self.sidebar.set_checked_index(index)

    def _apply_styles(self):
        self.setStyleSheet("""
            QMainWindow, QWidget, QDialog {
                background-color: #D9D2C9;
                color: #2C2621;
                font-family: 'Segoe UI', Arial, sans-serif;
            }

            QFrame#Sidebar {
                background-color: #C8C0B5;
                border-right: 1px solid #B0A79A;
            }
            QLabel#SidebarTitle {
                font-size: 20px;
                font-weight: bold;
                color: #8C4A1B;
            }
            QLabel#SidebarSubtitle {
                font-size: 11px;
                color: #5C534A;
            }
            QLabel#VersionLabel {
                font-size: 10px;
                color: #786F66;
            }

            QPushButton#NavButton {
                background-color: transparent;
                color: #403831;
                border: none;
                border-radius: 8px;
                padding: 12px 16px;
                text-align: left;
                font-size: 13px;
                font-weight: 500;
            }
            QPushButton#NavButton:hover {
                background-color: #B8AEA2;
                color: #1A1512;
            }
            QPushButton#NavButton:checked {
                background-color: #A89B8C;
                color: #FFFFFF;
                font-weight: bold;
                border-left: 4px solid #8C4A1B;
            }

            QGroupBox {
                background-color: #E2DBD2;
                border: 1px solid #BEB5A8;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 12px;
                font-weight: bold;
                color: #403831;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 6px;
                left: 10px;
                background-color: #E2DBD2;
                color: #8C4A1B;
            }

            QPushButton {
                background-color: #C8C0B5;
                color: #2C2621;
                border: 1px solid #B0A79A;
                border-radius: 6px;
                padding: 6px 14px;
                font-size: 12px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #B8AEA2;
                border-color: #9E9486;
            }
            QPushButton:pressed {
                background-color: #A89B8C;
                color: #FFFFFF;
                border-color: #8C4A1B;
            }
            QPushButton:disabled {
                background-color: #D9D2C9;
                color: #8C837A;
                border-color: #C8C0B5;
            }

            QPushButton#BtnPrimary {
                background-color: #2E7D32;
                color: #FFFFFF;
                font-weight: bold;
                font-size: 13px;
                padding: 10px;
                border: 1px solid #1B5E20;
                border-radius: 6px;
            }
            QPushButton#BtnPrimary:hover {
                background-color: #388E3C;
            }
            QPushButton#BtnPrimary:pressed {
                background-color: #1B5E20;
            }
            QPushButton#BtnPrimary:disabled {
                background-color: #A5D6A7;
                color: #E8F5E9;
                border-color: #81C784;
            }

            QPushButton#BtnDanger {
                background-color: #B85C5C;
                color: #FFFFFF;
                font-weight: 500;
                padding: 8px;
                border: 1px solid #A04B4B;
            }
            QPushButton#BtnDanger:hover {
                background-color: #C76B6B;
            }

            QPushButton#BtnSecondary {
                background-color: #6E6359;
                color: #FFFFFF;
                font-weight: 500;
                padding: 8px;
                border: 1px solid #5A5148;
            }
            QPushButton#BtnSecondary:hover {
                background-color: #7E7267;
            }

            QListWidget, QGraphicsView, QLineEdit, QComboBox, QTextEdit, QPlainTextEdit, QTableWidget {
                background-color: #EAE4DC;
                color: #1A1512;
                border: 1px solid #BEB5A8;
                border-radius: 6px;
                padding: 4px;
                selection-background-color: #A89B8C;
                selection-color: #FFFFFF;
            }

            /* ---- Явній стиль для CheckBox ---- */
            QCheckBox {
                color: #2C2621;
                background-color: transparent;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                background-color: #EAE4DC;
                border: 1px solid #8C7B70;
                border-radius: 3px;
            }
            QCheckBox::indicator:hover {
                border-color: #8C4A1B;
                background-color: #F5F0EB;
            }
            QCheckBox::indicator:checked {
                background-color: #8C4A1B;
                border-color: #6E3813;
                image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'><path fill='none' stroke='white' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' d='M2 6l3 3 5-5'/></svg>");
            }
            QCheckBox::indicator:disabled {
                background-color: #D9D2C9;
                border-color: #BEB5A8;
            }

            QRadioButton {
                color: #2C2621;
                background-color: transparent;
                spacing: 6px;
            }

            QProgressBar {
                border: 1px solid #BEB5A8;
                border-radius: 4px;
                text-align: center;
                background-color: #EAE4DC;
            }
            QProgressBar::chunk {
                background-color: #B08259;
            }

            /* ---- Головна сторінка ---- */
            QLabel#HomeTitle {
                font-size: 26px;
                font-weight: bold;
                color: #8C4A1B;
                background: transparent;
            }
            QLabel#HomeSubtitle {
                font-size: 13px;
                color: #5C534A;
                background: transparent;
            }

            QFrame#ToolCard {
                background-color: #E2DBD2;
                border: 1px solid #BEB5A8;
                border-radius: 12px;
            }
            QFrame#ToolCard:hover {
                background-color: #EAE4DC;
                border: 1px solid #8C4A1B;
            }
            QLabel#ToolCardIcon {
                background: transparent;
            }
            QLabel#ToolCardTitle {
                font-size: 15px;
                font-weight: bold;
                color: #403831;
                background: transparent;
            }
            QLabel#ToolCardDesc {
                font-size: 12px;
                color: #6E6359;
                background: transparent;
            }
            QLabel#ToolCardOpen {
                font-size: 12px;
                font-weight: bold;
                color: #8C4A1B;
                background: transparent;
            }
        """)