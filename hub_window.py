# === hub_window.py ===
import sys
from PyQt5 import QtCore, QtGui, QtWidgets

# Імпортуємо віджети модулів
from modules.pdf_translator.gui import MainWindow as PDFTranslatorWidget
from modules.pdf_cropper.cropper_widget import PDFBatchCropperWidget


class ModernSidebar(QtWidgets.QFrame):
    """Ліва панель навігації."""
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

        # Логотип / Заголовок
        logo_label = QtWidgets.QLabel("PDF Studio")
        logo_label.setObjectName("SidebarTitle")
        logo_label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(logo_label)

        sub_logo = QtWidgets.QLabel("Універсальний інструментарій")
        sub_logo.setObjectName("SidebarSubtitle")
        sub_logo.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(sub_logo)

        layout.addSpacing(25)

        # Група кнопок перемикання
        self.btn_group = QtWidgets.QButtonGroup(self)
        self.btn_group.setExclusive(True)

        self.btn_ocr = self._create_nav_button("📄 OCR та Переклад", 0)
        self.btn_crop = self._create_nav_button("✂️ Пакетна Обрізка", 1)

        layout.addWidget(self.btn_ocr)
        layout.addWidget(self.btn_crop)

        layout.addStretch()

        # Версія / Інфо внизу
        version_label = QtWidgets.QLabel("v2.0 • PyQt5")
        version_label.setObjectName("VersionLabel")
        version_label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(version_label)

        # Початковий вибір
        self.btn_ocr.setChecked(True)

    def _create_nav_button(self, text, index):
        btn = QtWidgets.QPushButton(text)
        btn.setCheckable(True)
        btn.setCursor(QtCore.Qt.PointingHandCursor)
        btn.setObjectName("NavButton")
        self.btn_group.addButton(btn, index)
        btn.clicked.connect(lambda: self.module_changed.emit(index))
        return btn


class MainHubWindow(QtWidgets.QMainWindow):
    """Головне уніфіковане вікно програми."""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF Studio & Toolbox")
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

        # 1. Ліва панель (Sidebar)
        self.sidebar = ModernSidebar()
        self.sidebar.module_changed.connect(self.switch_module)
        main_layout.addWidget(self.sidebar)

        # 2. Основна зона вмісту (Stacked Widget)
        self.stack = QtWidgets.QStackedWidget()
        self.stack.setObjectName("ContentArea")

        # Ініціалізація віджетів-модулів
        self.translator_widget = PDFTranslatorWidget()
        self.cropper_widget = PDFBatchCropperWidget()

        self.stack.addWidget(self.translator_widget)  # Index 0
        self.stack.addWidget(self.cropper_widget)     # Index 1

        main_layout.addWidget(self.stack, stretch=1)

    def switch_module(self, index):
        self.stack.setCurrentIndex(index)

    def _apply_styles(self):
        """Сучасна темна/професійна тема (QSS)."""
        self.setStyleSheet("""
            /* Загальні налаштування */
            QMainWindow, QWidget#ContentArea {
                background-color: #1E1E2E;
                color: #CDD6F4;
                font-family: 'Segoe UI', Arial, sans-serif;
            }

            /* Sidebar */
            QFrame#Sidebar {
                background-color: #181825;
                border-right: 1px solid #313244;
            }
            QLabel#SidebarTitle {
                font-size: 20px;
                font-weight: bold;
                color: #89B4FA;
            }
            QLabel#SidebarSubtitle {
                font-size: 11px;
                color: #A6ADC8;
            }
            QLabel#VersionLabel {
                font-size: 10px;
                color: #6C7086;
            }

            /* Кнопки Навігації в Sidebar */
            QPushButton#NavButton {
                background-color: transparent;
                color: #A6ADC8;
                border: none;
                border-radius: 8px;
                padding: 12px 16px;
                text-align: left;
                font-size: 13px;
                font-weight: 500;
            }
            QPushButton#NavButton:hover {
                background-color: #313244;
                color: #CDD6F4;
            }
            QPushButton#NavButton:checked {
                background-color: #89B4FA;
                color: #11111B;
                font-weight: bold;
            }

            /* Уніфіковані стилі елементів всередині модулів */
            QPushButton {
                background-color: #313244;
                color: #CDD6F4;
                border: 1px solid #45475A;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
            }
            QPushButton:hover {
                background-color: #45475A;
                border-color: #585B70;
            }
            QPushButton:pressed {
                background-color: #585B70;
            }

            QListWidget, QGraphicsView, QLineEdit, QComboBox, QTextEdit {
                background-color: #181825;
                color: #CDD6F4;
                border: 1px solid #313244;
                border-radius: 6px;
            }

            QProgressBar {
                border: 1px solid #313244;
                border-radius: 4px;
                text-align: center;
                background-color: #181825;
                color: #CDD6F4;
            }
            QProgressBar::chunk {
                background-color: #89B4FA;
                border-radius: 3px;
            }

            QSplitter::handle {
                background-color: #313244;
            }
        """)