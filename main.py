import os
import sys

from PyQt5 import QtGui, QtWidgets

from hub_window import MainHubWindow
from ui_icons import create_vector_icon
from theme import apply_theme, COLORS

# Шлях до файлу береться відносно __file__ цього модуля (а не поточної
# робочої теки) - такий самий підхід, що й у pdf_pipeline.py для
# DejaVuSans.ttf. PyInstaller у режимі --onedir відтворює цю ж структуру
# файлів усередині dist/PDFManager/_internal/, тож шлях лишається
# правильним і в зібраному додатку (за умови, що PDFManager.ico
# додається через --add-data у build.yml - це вже зроблено).
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
APP_ICON_PATH = os.path.join(SCRIPT_DIR, "PDFManager.ico")


def load_app_icon():
    """
    Іконка самого додатка (та, що видно у провіднику/на панелі задач/на
    стільниці) - береться з PDFManager.ico в корені проєкту. Якщо файл
    раптом відсутній (наприклад, хтось випадково прибрав його локально
    або забув --add-data у build.yml), не падаємо, а повертаємось до
    попередньої векторної іконки, щоб застосунок все одно запускався.
    """
    if os.path.isfile(APP_ICON_PATH):
        icon = QtGui.QIcon(APP_ICON_PATH)
        if not icon.isNull():
            return icon
    return create_vector_icon("ocr", color=COLORS["accent"], size=64)


def main():
    app = QtWidgets.QApplication(sys.argv)
    apply_theme(app)

    app_icon = load_app_icon()
    app.setWindowIcon(app_icon)

    window = MainHubWindow()
    # Іконку також виставляємо напряму головному вікну - на Windows саме
    # іконка топлевел-вікна (а не лише QApplication) використовується
    # для кнопки на панелі задач.
    window.setWindowIcon(app_icon)
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
