"""Вкладка "OCR": розпізнавання тексту у PDF-сканах (пакетно)."""
import os

from .base_widget import PdfBatchToolBase


class PDFOcrWidget(PdfBatchToolBase):
    """Робить з відсканованих PDF розпізнані (з виділюваним текстом) і за
    бажанням додатково витягує текст у DOCX/TXT. Переклад - окрема вкладка."""

    SETTINGS_PREFIX = "ocr"
    COMMON_GROUP_TITLE = "Розпізнавання (OCR)"
    EXPORT_ORIGINAL_TEXT = True

    def collect_task_options(self):
        # OCR завжди створює розпізнаний PDF; текст у DOCX/TXT - додатково.
        return {"make_searchable": True, "translate_targets": []}

    def combined_default_name(self, first_path):
        return os.path.splitext(os.path.basename(first_path))[0] + "_searchable.pdf"
