"""
Точка входу: PDF-manager (OCR + переклад).

Перевіряє наявність усіх залежностей ДО імпорту решти модулів - якщо
чогось не вистачає, користувач бачить зрозуміле повідомлення замість
трасування помилки імпорту з середини випадкового файлу.
"""
import sys
import importlib.util

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
    print("Не вистачає пакетів. Встановіть їх командою:")
    print(f"    pip install {' '.join(_missing)}")
    print("або просто:  pip install -r requirements.txt")
    sys.exit(1)

from PyQt5 import QtCore, QtWidgets  # noqa: E402

from gui import MainWindow, _build_app_icon  # noqa: E402


def main():
    QtWidgets.QApplication.setAttribute(
        QtCore.Qt.AA_EnableHighDpiScaling, True)
    app = QtWidgets.QApplication(sys.argv)
    app.setWindowIcon(_build_app_icon())
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
