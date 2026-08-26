from PyQt5 import QtCore, QtGui

def create_vector_icon(icon_type: str, color: str = "#8C4A1B", size: int = 32) -> QtGui.QIcon:
    """Генерує векторні іконки через QPainter для стабільного відображення на всіх ОС."""
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