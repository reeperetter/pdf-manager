import sys
import importlib.util

# Автоматична перевірка необхідних залежностей
_REQUIRED = {
    "pymupdf": "fitz",
    "pillow": "PIL",
    "pytesseract": "pytesseract",
    "deep-translator": "deep_translator",
    "python-docx": "docx",
    "PyQt5": "PyQt5",
}

_missing = [
    pip_name for pip_name, import_name in _REQUIRED.items()
    if importlib.util.find_spec(import_name) is None
]
if _missing:
    print("❌ Не вистачає необхідних бібліотек. Встановіть їх командою:")
    print(f"    pip install {' '.join(_missing)}")
    sys.exit(1)

from PyQt5 import QtCore, QtWidgets
from hub_window import MainHubWindow
from modules.pdf_translator.gui import _build_app_icon


def apply_forced_light_theme(app: QtWidgets.QApplication):
    """Примусовий QSS стиль для пробиття GTK-тем Linux Mint."""
    app.setStyle("Fusion")

    global_stylesheet = """
        QWidget {
            background-color: #f5f5f5;
            color: #000000;
        }
        QMainWindow, QDialog, QTabWidget, QTabBar::tab {
            background-color: #f5f5f5;
            color: #000000;
        }
        QListWidget, QGraphicsView, QLineEdit, QComboBox, QTextEdit {
            background-color: #ffffff;
            color: #000000;
            border: 1px solid #cccccc;
        }
        QPushButton {
            background-color: #e1e1e1;
            color: #000000;
            border: 1px solid #adadad;
            padding: 4px 8px;
            border-radius: 2px;
        }
        QPushButton:hover {
            background-color: #e5f1fb;
            border-color: #0078d7;
        }
        QSplitter::handle {
            background-color: #dcdcdc;
        }
    """
    app.setStyleSheet(global_stylesheet)


def main():
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
    app = QtWidgets.QApplication(sys.argv)

    apply_forced_light_theme(app)

    # Встановлюємо динамічну іконку
    try:
        app.setWindowIcon(_build_app_icon())
    except Exception:
        pass

    window = MainHubWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()