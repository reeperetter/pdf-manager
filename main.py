import sys
from PyQt5 import QtWidgets

from hub_window import MainHubWindow
from ui_icons import create_vector_icon


def main():
    app = QtWidgets.QApplication(sys.argv)

    # Встановлюємо кросплатформову векторну іконку для всього додатка
    app_icon = create_vector_icon("ocr", color="#8C4A1B", size=64)
    app.setWindowIcon(app_icon)

    window = MainHubWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()