"""
Спільні "додаткові" елементи пакетних вкладок (обрізка, поворот, стиснення,
картинки -> PDF): кнопка "Нещодавні", прапорець "Пропускати файли, для яких
уже є результат" і кнопка "Відкрити папку результатів".

Однакові за виглядом і поведінкою з вкладками OCR та перекладу. Список
нещодавніх файлів (ключ "recent_files" у QSettings) спільний для всіх вкладок.
"""
import os

from PyQt5 import QtCore, QtGui, QtWidgets

# Ті самі значення, що й у modules/pdf_translator/base_widget.py, щоб
# налаштування (нещодавні файли) були спільними для всього застосунку.
SETTINGS_ORG = "pdf-ocr-translator"
SETTINGS_APP = "PDFManager"
RECENT_LIMIT = 10


class BatchExtras(QtCore.QObject):
    """Створює три елементи та підключає їхню поведінку.

    owner          - віджет-власник (для діалогів);
    key_prefix     - префікс ключів QSettings вкладки (наприклад "crop");
    add_files_cb   - функція, що приймає список шляхів і додає їх у список;
    extensions     - допустимі розширення "нещодавніх" файлів.
    """

    def __init__(self, owner, key_prefix, add_files_cb,
                 extensions=(".pdf",), parent=None):
        super().__init__(parent or owner)
        self._owner = owner
        self._prefix = key_prefix
        self._add_files_cb = add_files_cb
        self._extensions = tuple(e.lower() for e in extensions)
        self.settings = QtCore.QSettings(SETTINGS_ORG, SETTINGS_APP)
        self.output_dir = None

        self.recent_button = QtWidgets.QPushButton("Нещодавні")
        self._menu = QtWidgets.QMenu(self.recent_button)
        self._menu.aboutToShow.connect(self._populate_menu)
        self.recent_button.setMenu(self._menu)

        self.skip_checkbox = QtWidgets.QCheckBox(
            "Пропускати файли, для яких уже є результат")
        self.skip_checkbox.setChecked(self.settings.value(
            f"{key_prefix}/skip_existing", True, type=bool))
        self.skip_checkbox.toggled.connect(
            lambda v: self.settings.setValue(f"{key_prefix}/skip_existing", v))

        self.open_button = QtWidgets.QPushButton("Відкрити папку результатів")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self.open_output_folder)

    # ------------------------------------------------------- нещодавні --
    def _populate_menu(self):
        self._menu.clear()
        recent = self.settings.value("recent_files", [], type=list) or []
        recent = [p for p in recent if p.lower().endswith(self._extensions)]
        if not recent:
            self._menu.addAction("(порожньо)").setEnabled(False)
            return
        for path in recent:
            action = self._menu.addAction(path)
            action.triggered.connect(
                lambda checked=False, p=path: self._pick_recent(p))

    def _pick_recent(self, path):
        if os.path.isfile(path):
            self._add_files_cb([path])
        else:
            QtWidgets.QMessageBox.warning(
                self._owner, "Файл не знайдено", f"Файла більше немає:\n{path}")

    def remember(self, paths):
        """Запам'ятати додані файли у списку нещодавніх."""
        recent = self.settings.value("recent_files", [], type=list) or []
        for path in paths:
            recent = [p for p in recent if p != path]
            recent.insert(0, path)
        self.settings.setValue("recent_files", recent[:RECENT_LIMIT])

    # --------------------------------------------------- папка результатів --
    def set_output_dir(self, path):
        self.output_dir = path
        self.open_button.setEnabled(bool(path and os.path.isdir(path)))

    def open_output_folder(self):
        if self.output_dir and os.path.isdir(self.output_dir):
            QtGui.QDesktopServices.openUrl(
                QtCore.QUrl.fromLocalFile(self.output_dir))

    @property
    def skip_existing(self):
        return self.skip_checkbox.isChecked()
