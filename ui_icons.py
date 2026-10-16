from PyQt5 import QtCore, QtGui
from theme import COLORS

def create_vector_icon(icon_type: str, color: str = None, size: int = 32) -> QtGui.QIcon:
    """Генерує векторні іконки через QPainter для стабільного відображення на всіх ОС.

    Якщо color не задано - використовується фірмовий акцентний колір
    із theme.py (єдине джерело кольорів застосунку)."""
    if color is None:
        color = COLORS["accent"]

    pix = QtGui.QPixmap(size, size)
    pix.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pix)
    p.setRenderHint(QtGui.QPainter.Antialiasing)

    main_color = QtGui.QColor(color)
    pen = QtGui.QPen(main_color, 2.5, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin)
    p.setPen(pen)

    if icon_type == "ocr":
        p.drawRoundedRect(6, 4, 20, 24, 3, 3)
        p.drawLine(10, 10, 22, 10)
        p.drawLine(16, 10, 16, 22)

    elif icon_type == "crop":
        p.drawLine(6, 6, 26, 26)
        p.drawLine(26, 6, 6, 26)
        p.drawEllipse(4, 4, 6, 6)
        p.drawEllipse(22, 4, 6, 6)

    elif icon_type == "play":
        path = QtGui.QPainterPath()
        path.moveTo(10, 6)
        path.lineTo(24, 16)
        path.lineTo(10, 26)
        path.closeSubpath()
        p.setBrush(main_color)
        p.drawPath(path)

    elif icon_type == "stop":
        p.setBrush(main_color)
        p.drawRoundedRect(7, 7, 18, 18, 4, 4)

    elif icon_type == "home":
        path = QtGui.QPainterPath()
        path.moveTo(4, 15)
        path.lineTo(16, 5)
        path.lineTo(28, 15)
        p.drawPath(path)
        p.drawRect(8, 15, 16, 12)
        p.drawRect(13, 20, 6, 7)

    elif icon_type == "compress":
        # Дві стрілки, що "стискають" вміст до центру, як символ архівації
        p.drawLine(6, 10, 6, 22)
        p.drawLine(26, 10, 26, 22)
        path_left = QtGui.QPainterPath()
        path_left.moveTo(6, 16)
        path_left.lineTo(13, 12)
        path_left.lineTo(13, 20)
        path_left.closeSubpath()
        p.setBrush(main_color)
        p.drawPath(path_left)

        path_right = QtGui.QPainterPath()
        path_right.moveTo(26, 16)
        path_right.lineTo(19, 12)
        path_right.lineTo(19, 20)
        path_right.closeSubpath()
        p.drawPath(path_right)

    elif icon_type == "rotate":
        # Дугова стрілка навколо прямокутника сторінки - символ повороту.
        p.drawRoundedRect(10, 10, 12, 16, 2, 2)
        rect = QtCore.QRectF(4, 4, 22, 22)
        p.drawArc(rect, 20 * 16, 280 * 16)
        arrow = QtGui.QPainterPath()
        arrow.moveTo(23, 5)
        arrow.lineTo(27, 8)
        arrow.lineTo(22, 11)
        arrow.closeSubpath()
        p.setBrush(main_color)
        p.drawPath(arrow)

    elif icon_type == "convert":
        # Дві протилежні стрілки - "конвертація туди й назад".
        p.drawLine(6, 11, 25, 11)
        p.drawLine(25, 11, 20, 6)
        p.drawLine(25, 11, 20, 16)
        p.drawLine(26, 21, 7, 21)
        p.drawLine(7, 21, 12, 16)
        p.drawLine(7, 21, 12, 26)

    elif icon_type == "doc":
        # Аркуш із загнутим кутом і рядками тексту.
        path = QtGui.QPainterPath()
        path.moveTo(8, 4)
        path.lineTo(20, 4)
        path.lineTo(26, 10)
        path.lineTo(26, 28)
        path.lineTo(8, 28)
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(20, 4, 20, 10)
        p.drawLine(20, 10, 26, 10)
        p.drawLine(12, 16, 22, 16)
        p.drawLine(12, 20, 22, 20)
        p.drawLine(12, 24, 18, 24)

    elif icon_type == "text":
        p.drawRoundedRect(7, 4, 18, 24, 2, 2)
        p.drawLine(11, 10, 21, 10)
        p.drawLine(16, 10, 16, 22)

    elif icon_type == "sheet":
        p.drawRoundedRect(5, 6, 22, 20, 2, 2)
        p.drawLine(5, 13, 27, 13)
        p.drawLine(5, 20, 27, 20)
        p.drawLine(13, 6, 13, 26)

    elif icon_type == "slides":
        p.drawRoundedRect(4, 6, 24, 15, 2, 2)
        p.drawLine(16, 21, 16, 26)
        p.drawLine(10, 26, 22, 26)
        p.drawLine(9, 17, 9, 14)
        p.drawLine(14, 17, 14, 11)
        p.drawLine(19, 17, 19, 13)

    elif icon_type == "translate":
        # Дві "бульбашки" з літерами - символ перекладу між мовами.
        p.drawRoundedRect(4, 5, 15, 13, 2, 2)
        p.drawLine(8, 9, 15, 9)
        p.drawLine(11, 9, 11, 14)
        p.drawLine(8, 14, 14, 14)
        p.drawRoundedRect(13, 14, 15, 13, 2, 2)
        p.drawLine(17, 23, 20, 17)
        p.drawLine(20, 17, 23, 23)
        p.drawLine(18, 21, 22, 21)

    elif icon_type == "image":
        # Рамка "фото" з гірським пейзажем і сонцем - типова іконка
        # зображення/галереї.
        p.drawRoundedRect(4, 6, 24, 20, 3, 3)
        p.setBrush(main_color)
        p.drawEllipse(9, 11, 5, 5)
        p.setBrush(QtCore.Qt.NoBrush)
        path = QtGui.QPainterPath()
        path.moveTo(6, 23)
        path.lineTo(13, 15)
        path.lineTo(18, 20)
        path.lineTo(22, 16)
        path.lineTo(26, 21)
        p.drawPath(path)

    elif icon_type == "folder":
        path = QtGui.QPainterPath()
        path.moveTo(4, 8)
        path.lineTo(12, 8)
        path.lineTo(15, 11)
        path.lineTo(28, 11)
        path.lineTo(28, 24)
        path.lineTo(4, 24)
        path.closeSubpath()
        p.drawPath(path)

    p.end()
    return QtGui.QIcon(pix)