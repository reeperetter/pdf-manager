"""Вкладка "OCR": розпізнавання тексту у PDF-сканах (пакетно)."""
import os

from PyQt5 import QtWidgets

from .base_widget import PdfBatchToolBase


class PDFOcrWidget(PdfBatchToolBase):
    """Робить з відсканованих PDF розпізнані (з виділюваним текстом) та/або
    витягує текст у DOCX/TXT. Переклад - окрема вкладка."""

    SETTINGS_PREFIX = "ocr"
    COMMON_GROUP_TITLE = "Розпізнавання (OCR)"
    EXPORT_ORIGINAL_TEXT = True

    def build_task_group(self, bold):
        grp = QtWidgets.QGroupBox("Що створити")
        grp.setFont(bold)
        layout = QtWidgets.QVBoxLayout(grp)
        layout.setSpacing(3)
        self.chk_searchable = QtWidgets.QCheckBox(
            "Розпізнаваний PDF (виділюваний текст)")
        self.chk_searchable.setChecked(True)
        layout.addWidget(self.chk_searchable)
        hint = QtWidgets.QLabel(
            "Текст можна також зберегти окремим файлом - блок "
            "«Текст окремо від PDF» зліва.")
        hint.setObjectName("MutedLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return grp

    def collect_task_options(self):
        if not (self.chk_searchable.isChecked()
                or self.chk_text_docx.isChecked()
                or self.chk_text_txt.isChecked()):
            QtWidgets.QMessageBox.warning(
                self, "Нічого робити",
                "Виберіть, що створити: розпізнаваний PDF і/або текстовий "
                "файл (DOCX чи TXT).")
            return None
        return {
            "make_searchable": self.chk_searchable.isChecked(),
            "translate_targets": [],
        }

    def combined_default_name(self, first_path):
        return os.path.splitext(os.path.basename(first_path))[0] + "_searchable.pdf"

    def load_task_settings(self, s):
        self.chk_searchable.setChecked(
            s.value(self._key("searchable"), True, type=bool))

    def save_task_settings(self, s):
        s.setValue(self._key("searchable"), self.chk_searchable.isChecked())
