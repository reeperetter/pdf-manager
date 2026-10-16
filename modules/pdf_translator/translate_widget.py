"""Вкладка "Переклад PDF": переклад тексту у PDF з збереженням макета."""
import os

from PyQt5 import QtWidgets

from .base_widget import PdfBatchToolBase


class PDFTranslateWidget(PdfBatchToolBase):
    """Перекладає PDF (текстовий шар або розпізнаний скан) українською,
    російською та/або англійською. Просте розпізнавання без перекладу -
    окрема вкладка "OCR"."""

    SETTINGS_PREFIX = "translate"
    COMMON_GROUP_TITLE = "Мова та шрифт"
    EXPORT_ORIGINAL_TEXT = False
    # DPI і розпрямлення впливають на якість розпізнавання сканів, а не на
    # переклад, тому тут приховані (DPI завжди 300, без розпрямлення).
    SHOW_RENDER_OPTIONS = False

    def build_task_group(self, bold):
        grp = QtWidgets.QGroupBox("Перекласти на")
        grp.setFont(bold)
        layout = QtWidgets.QVBoxLayout(grp)
        layout.setSpacing(3)
        self.chk_uk = QtWidgets.QCheckBox("Українську")
        self.chk_ru = QtWidgets.QCheckBox("Російську")
        self.chk_en = QtWidgets.QCheckBox("Англійську")
        self.chk_uk.setChecked(True)
        for c in (self.chk_uk, self.chk_ru, self.chk_en):
            layout.addWidget(c)
        layout.addSpacing(4)
        btn_glossary = QtWidgets.QPushButton("Глосарій (не перекладати)...")
        btn_glossary.clicked.connect(self.edit_glossary)
        layout.addWidget(btn_glossary)
        return grp

    def collect_task_options(self):
        targets = []
        if self.chk_uk.isChecked():
            targets.append("uk")
        if self.chk_ru.isChecked():
            targets.append("ru")
        if self.chk_en.isChecked():
            targets.append("en")
        if not targets:
            QtWidgets.QMessageBox.warning(
                self, "Нічого робити", "Виберіть хоча б одну мову перекладу.")
            return None
        return {"make_searchable": False, "translate_targets": targets}

    def combined_default_name(self, first_path):
        return os.path.splitext(os.path.basename(first_path))[0] + "_translated.pdf"

    def glossary_for_run(self):
        return set(self.glossary_terms)

    def edit_glossary(self):
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("Глосарій - терміни, які не перекладати")
        layout = QtWidgets.QVBoxLayout(dlg)
        layout.addWidget(QtWidgets.QLabel(
            "По одному терміну на рядок (без урахування регістру)."))
        edit = QtWidgets.QPlainTextEdit()
        edit.setPlainText("\n".join(sorted(self.glossary_terms)))
        layout.addWidget(edit)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        dlg.resize(400, 300)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            self.glossary_terms = {
                line.strip().lower()
                for line in edit.toPlainText().splitlines() if line.strip()
            }
            self.settings.setValue(
                "glossary_terms", "\n".join(sorted(self.glossary_terms)))

    def load_task_settings(self, s):
        self.chk_uk.setChecked(s.value(self._key("uk"), True, type=bool))
        self.chk_ru.setChecked(s.value(self._key("ru"), False, type=bool))
        self.chk_en.setChecked(s.value(self._key("en"), False, type=bool))
        terms_str = str(s.value("glossary_terms", ""))
        self.glossary_terms = {
            t.strip().lower() for t in terms_str.splitlines() if t.strip()
        }

    def save_task_settings(self, s):
        s.setValue(self._key("uk"), self.chk_uk.isChecked())
        s.setValue(self._key("ru"), self.chk_ru.isChecked())
        s.setValue(self._key("en"), self.chk_en.isChecked())
