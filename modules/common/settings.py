"""Єдине місце для налаштувань застосунку (QSettings)."""
from PyQt5 import QtCore

SETTINGS_ORG = "pdf-ocr-translator"
SETTINGS_APP = "PDFManager"


def app_settings():
    """QSettings застосунку (спільні ключі: last_dir, recent_files, window/*,
    ocr/workers, а також ключі з префіксом кожної вкладки)."""
    return QtCore.QSettings(SETTINGS_ORG, SETTINGS_APP)
