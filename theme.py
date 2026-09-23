"""
theme.py
========
Єдине джерело правди для кольорової схеми та стилів усього застосунку
PDF Manager. Мета - щоб усі вікна (хаб, OCR/Переклад, Обрізка,
Стиснення, і будь-який новий модуль у майбутньому) виглядали
однаково, без "розповзання" кольорів по файлах.

ПРАВИЛА ДЛЯ БУДЬ-ЯКОГО НОВОГО МОДУЛЯ/ВІКНА
--------------------------------------------
1. НЕ хардкодь кольори (background-color: #xxxxxx, QColor(r, g, b))
   у файлах окремих модулів. Замість цього:

     - Для кнопок - став готовий objectName, стиль підтягнеться сам:
         btn.setObjectName("BtnPrimary")    - головна дія (зелений)
         btn.setObjectName("BtnDanger")     - деструктивна дія (червоний)
         btn.setObjectName("BtnSecondary")  - другорядна дія (сіро-брунатний)
       Звичайний QPushButton без objectName вже стилізований базово -
       додаткового setStyleSheet на кнопку не потрібно.

     - Для приглушеного дрібного тексту (підказки, примітки) -
         label.setObjectName("MutedLabel")

     - Для областей попереднього перегляду сторінки PDF
       (QGraphicsView / QLabel з рендером сторінки) -
         view.setObjectName("PagePreview")

     - Якщо потрібен колір для ручного малювання (QPainter,
       QGraphicsScene, рамки виділення тощо) - бери його з COLORS
       нижче або через accent_qcolor(), а не пиши новий hex.

2. Іконки - лише через ui_icons.create_vector_icon(...). Не малюй
   нових пікторграм вручну всередині окремого модуля.

3. apply_theme(app) викликається ОДИН РАЗ на рівні QApplication -
   у main.py, одразу після створення додатка, і (для можливості
   окремого запуску модуля під час розробки) у блоці
   `if __name__ == "__main__":` кожного модуля. Самі вікна/віджети
   НЕ повинні викликати self.setStyleSheet(...) з власною палітрою.

Якщо додаєш новий модуль - подивись на modules/pdf_compressor як на
приклад "чистого" модуля: жодного власного кольору, усе бере
глобальний стиль звідси.
"""

from PyQt5.QtGui import QColor

# ---------------------------------------------------------------------
# Палітра. Тепла бежево-коричнева схема з акцентом на цеглясто-брунатний.
# ---------------------------------------------------------------------
COLORS = {
    "bg": "#D9D2C9",
    "sidebar_bg": "#C8C0B5",
    "sidebar_border": "#B0A79A",
    "sidebar_hover": "#B8AEA2",
    "sidebar_active": "#A89B8C",

    "panel_bg": "#E2DBD2",
    "panel_border": "#BEB5A8",

    "input_bg": "#EAE4DC",
    "input_text": "#1A1512",

    "text": "#2C2621",
    "text_strong": "#1A1512",
    "text_heading": "#403831",
    "text_muted": "#5C534A",
    "text_faint": "#786F66",
    "text_on_accent": "#FFFFFF",

    "accent": "#8C4A1B",
    "accent_dark": "#6E3813",

    "success": "#2E7D32",
    "success_hover": "#388E3C",
    "success_pressed": "#1B5E20",
    "success_disabled_bg": "#A5D6A7",
    "success_disabled_text": "#E8F5E9",
    "success_disabled_border": "#81C784",

    "danger": "#B85C5C",
    "danger_hover": "#C76B6B",
    "danger_border": "#A04B4B",

    "secondary": "#6E6359",
    "secondary_hover": "#7E7267",
    "secondary_border": "#5A5148",

    "progress_chunk": "#B08259",

    "preview_bg": "#d0d0d0",
    "preview_border": "#cccccc",
}


def accent_qcolor(alpha=255):
    """QColor фірмового акцентного кольору - для ручного малювання
    (QPainter, QGraphicsScene, рамки виділення тощо), щоб модулі не
    хардкодили власний RGB."""
    c = QColor(COLORS["accent"])
    c.setAlpha(alpha)
    return c


STYLESHEET = f"""
    QMainWindow, QWidget, QDialog {{
        background-color: {COLORS['bg']};
        color: {COLORS['text']};
        font-family: 'Segoe UI', Arial, sans-serif;
    }}

    /* ---- Бічна панель ---- */
    QFrame#Sidebar {{
        background-color: {COLORS['sidebar_bg']};
        border-right: 1px solid {COLORS['sidebar_border']};
    }}
    QLabel#SidebarTitle {{
        font-size: 20px;
        font-weight: bold;
        color: {COLORS['accent']};
        background: transparent;
    }}
    QLabel#SidebarSubtitle {{
        font-size: 11px;
        color: {COLORS['text_muted']};
        background: transparent;
    }}
    QLabel#VersionLabel {{
        font-size: 10px;
        color: {COLORS['text_faint']};
        background: transparent;
    }}

    QPushButton#NavButton {{
        background-color: transparent;
        color: {COLORS['text_heading']};
        border: none;
        border-radius: 8px;
        padding: 12px 16px;
        text-align: left;
        font-size: 13px;
        font-weight: 500;
    }}
    QPushButton#NavButton:hover {{
        background-color: {COLORS['sidebar_hover']};
        color: {COLORS['text_strong']};
    }}
    QPushButton#NavButton:checked {{
        background-color: {COLORS['sidebar_active']};
        color: #FFFFFF;
        font-weight: bold;
        border-left: 4px solid {COLORS['accent']};
    }}

    /* ---- Групування ---- */
    QGroupBox {{
        background-color: {COLORS['panel_bg']};
        border: 1px solid {COLORS['panel_border']};
        border-radius: 8px;
        margin-top: 10px;
        padding-top: 12px;
        font-weight: bold;
        color: {COLORS['text_heading']};
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        padding: 0 6px;
        left: 10px;
        background-color: {COLORS['panel_bg']};
        color: {COLORS['accent']};
    }}

    /* ---- Звичайні кнопки ---- */
    QPushButton {{
        background-color: {COLORS['sidebar_bg']};
        color: {COLORS['text']};
        border: 1px solid {COLORS['sidebar_border']};
        border-radius: 6px;
        padding: 6px 12px;
        font-size: 12px;
        font-weight: 500;
    }}
    QPushButton:hover {{
        background-color: {COLORS['sidebar_hover']};
        border-color: #9E9486;
    }}
    QPushButton:pressed {{
        background-color: {COLORS['sidebar_active']};
        color: #FFFFFF;
        border-color: {COLORS['accent']};
    }}
    QPushButton:disabled {{
        background-color: {COLORS['bg']};
        color: #8C837A;
        border-color: {COLORS['sidebar_bg']};
    }}

    QPushButton#BtnPrimary {{
        background-color: {COLORS['success']};
        color: {COLORS['text_on_accent']};
        font-weight: bold;
        font-size: 13px;
        padding: 10px;
        border: 1px solid {COLORS['success_pressed']};
        border-radius: 6px;
    }}
    QPushButton#BtnPrimary:hover {{
        background-color: {COLORS['success_hover']};
    }}
    QPushButton#BtnPrimary:pressed {{
        background-color: {COLORS['success_pressed']};
    }}
    QPushButton#BtnPrimary:disabled {{
        background-color: {COLORS['success_disabled_bg']};
        color: {COLORS['success_disabled_text']};
        border-color: {COLORS['success_disabled_border']};
    }}

    QPushButton#BtnDanger {{
        background-color: {COLORS['danger']};
        color: {COLORS['text_on_accent']};
        font-weight: 500;
        padding: 8px;
        border: 1px solid {COLORS['danger_border']};
    }}
    QPushButton#BtnDanger:hover {{
        background-color: {COLORS['danger_hover']};
    }}

    QPushButton#BtnSecondary {{
        background-color: {COLORS['secondary']};
        color: {COLORS['text_on_accent']};
        font-weight: 500;
        padding: 8px;
        border: 1px solid {COLORS['secondary_border']};
    }}
    QPushButton#BtnSecondary:hover {{
        background-color: {COLORS['secondary_hover']};
    }}

    /* ---- Поля вводу / списки / таблиці ---- */
    QListWidget, QGraphicsView, QLineEdit, QComboBox, QTextEdit,
    QPlainTextEdit, QTableWidget, QTextBrowser, QSpinBox {{
        background-color: {COLORS['input_bg']};
        color: {COLORS['input_text']};
        border: 1px solid {COLORS['panel_border']};
        border-radius: 6px;
        padding: 4px;
        selection-background-color: {COLORS['sidebar_active']};
        selection-color: #FFFFFF;
    }}

    QTableWidget {{
        gridline-color: {COLORS['panel_border']};
    }}
    QHeaderView::section {{
        background-color: {COLORS['panel_bg']};
        color: {COLORS['text']};
        border: none;
        border-bottom: 1px solid {COLORS['panel_border']};
        padding: 4px;
        font-weight: bold;
    }}

    QMenuBar {{
        background-color: {COLORS['sidebar_bg']};
        color: {COLORS['text']};
    }}
    QMenuBar::item:selected {{
        background-color: {COLORS['sidebar_hover']};
    }}
    QMenu {{
        background-color: {COLORS['input_bg']};
        color: {COLORS['text']};
        border: 1px solid {COLORS['panel_border']};
    }}
    QMenu::item:selected {{
        background-color: {COLORS['sidebar_active']};
        color: #FFFFFF;
    }}

    /* ---- CheckBox ---- */
    QCheckBox {{
        color: {COLORS['text']};
        background-color: transparent;
        spacing: 8px;
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        background-color: {COLORS['input_bg']};
        border: 1px solid #8C7B70;
        border-radius: 3px;
    }}
    QCheckBox::indicator:hover {{
        border-color: {COLORS['accent']};
        background-color: #F5F0EB;
    }}
    QCheckBox::indicator:checked {{
        background-color: {COLORS['accent']};
        border-color: {COLORS['accent_dark']};
        image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'><path fill='none' stroke='white' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' d='M2 6l3 3 5-5'/></svg>");
    }}
    QCheckBox::indicator:disabled {{
        background-color: {COLORS['bg']};
        border-color: {COLORS['panel_border']};
    }}

    QRadioButton {{
        color: {COLORS['text']};
        background-color: transparent;
        spacing: 6px;
    }}

    QProgressBar {{
        border: 1px solid {COLORS['panel_border']};
        border-radius: 4px;
        text-align: center;
        background-color: {COLORS['input_bg']};
    }}
    QProgressBar::chunk {{
        background-color: {COLORS['progress_chunk']};
    }}

    QToolTip {{
        background-color: {COLORS['text_heading']};
        color: #FFFFFF;
        border: 1px solid {COLORS['accent']};
        padding: 4px;
    }}

    /* ---- Приглушений дрібний текст (підказки, примітки) ---- */
    QLabel#MutedLabel {{
        color: {COLORS['text_muted']};
        background: transparent;
        font-size: 11px;
    }}

    /* ---- Головна сторінка ---- */
    QLabel#HomeTitle {{
        font-size: 26px;
        font-weight: bold;
        color: {COLORS['accent']};
        background: transparent;
    }}
    QLabel#HomeSubtitle {{
        font-size: 13px;
        color: {COLORS['text_muted']};
        background: transparent;
    }}

    QFrame#ToolCard {{
        background-color: {COLORS['panel_bg']};
        border: 1px solid {COLORS['panel_border']};
        border-radius: 12px;
    }}
    QFrame#ToolCard:hover {{
        background-color: {COLORS['input_bg']};
        border: 1px solid {COLORS['accent']};
    }}
    QLabel#ToolCardIcon {{
        background: transparent;
    }}
    QLabel#ToolCardTitle {{
        font-size: 15px;
        font-weight: bold;
        color: {COLORS['text_heading']};
        background: transparent;
    }}
    QLabel#ToolCardDesc {{
        font-size: 12px;
        color: {COLORS['secondary']};
        background: transparent;
    }}
    QLabel#ToolCardOpen {{
        font-size: 12px;
        font-weight: bold;
        color: {COLORS['accent']};
        background: transparent;
    }}

    /* ---- Прев'ю сторінки PDF (Обрізка / Стиснення тощо) ---- */
    #PagePreview {{
        background-color: {COLORS['preview_bg']};
        border: 1px solid {COLORS['preview_border']};
        color: {COLORS['text_muted']};
    }}
"""


def apply_theme(app):
    """Застосовує єдиний стиль до всього застосунку.

    Викликається ОДИН РАЗ, одразу після створення QApplication -
    у main.py (весь застосунок) і в блоці `if __name__ == "__main__":`
    кожного модуля (для окремого запуску під час розробки).
    """
    app.setStyleSheet(STYLESHEET)
