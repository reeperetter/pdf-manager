"""Сторінка "Налаштування": OCR, моделі, гарячі клавіші, вікно."""
import os
import shutil

from PyQt5 import QtCore, QtGui, QtWidgets

from modules.common.settings import app_settings
from modules.pdf_translator import nllb, tesseract_setup
from modules.common.progress_task import run_with_progress
from modules.pdf_translator.nllb_installer import ensure_translation_model


def _dir_size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def _open_dir(path):
    os.makedirs(path, exist_ok=True)
    QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))


class SettingsPage(QtWidgets.QWidget):
    def __init__(self, shortcuts=(), parent=None):
        super().__init__(parent)
        self._shortcuts = list(shortcuts)
        self._init_ui()
        self.refresh()

    # --------------------------------------------------------- UI --
    def _section(self, layout, title):
        box = QtWidgets.QGroupBox(title)
        inner = QtWidgets.QVBoxLayout(box)
        inner.setSpacing(10)
        layout.addWidget(box)
        return inner

    @staticmethod
    def _muted(text):
        label = QtWidgets.QLabel(text)
        label.setObjectName("MutedLabel")
        label.setWordWrap(True)
        return label

    def _init_ui(self):
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(40, 40, 40, 40)
        outer.setSpacing(16)

        title = QtWidgets.QLabel("Налаштування")
        title.setObjectName("HomeTitle")
        outer.addWidget(title)
        subtitle = QtWidgets.QLabel("Розпізнавання, мовні моделі та гарячі клавіші")
        subtitle.setObjectName("HomeSubtitle")
        outer.addWidget(subtitle)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        outer.addWidget(scroll, 1)
        body = QtWidgets.QWidget()
        scroll.setWidget(body)
        body.setStyleSheet("QLabel { background: transparent; }")
        lay = QtWidgets.QVBoxLayout(body)
        lay.setContentsMargins(0, 0, 10, 0)
        lay.setSpacing(16)

        # --- OCR ---
        sec = self._section(lay, "Розпізнавання (OCR)")
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Сторінок одночасно:"))
        self.workers_combo = QtWidgets.QComboBox()
        auto = max(1, min(4, (os.cpu_count() or 2) // 2))
        self.workers_combo.addItem(f"Авто ({auto})", 0)
        for n in range(1, 9):
            self.workers_combo.addItem(str(n), n)
        row.addWidget(self.workers_combo)
        row.addStretch()
        sec.addLayout(row)
        sec.addWidget(self._muted(
            "Скільки сторінок розпізнається паралельно. Більше - швидше, але "
            "більше пам'яті й навантаження на процесор. На слабкому комп'ютері "
            "залиште «Авто» або 1."))
        self.workers_combo.currentIndexChanged.connect(self._save_workers)

        # --- NLLB ---
        sec = self._section(lay, "Модель перекладу NLLB-200")
        self.nllb_status = QtWidgets.QLabel()
        self.nllb_status.setWordWrap(True)
        self.nllb_status.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        sec.addWidget(self.nllb_status)
        row = QtWidgets.QHBoxLayout()
        self.btn_nllb_download = QtWidgets.QPushButton("Завантажити модель")
        self.btn_nllb_download.setObjectName("BtnPrimary")
        self.btn_nllb_download.clicked.connect(self._download_nllb)
        btn_open = QtWidgets.QPushButton("Відкрити теку")
        btn_open.setObjectName("BtnSecondary")
        btn_open.clicked.connect(self._open_nllb_dir)
        self.btn_nllb_test = QtWidgets.QPushButton("Перевірити переклад")
        self.btn_nllb_test.setObjectName("BtnSecondary")
        self.btn_nllb_test.clicked.connect(self._test_nllb)
        self.btn_nllb_delete = QtWidgets.QPushButton("Видалити модель")
        self.btn_nllb_delete.setObjectName("BtnDanger")
        self.btn_nllb_delete.clicked.connect(self._delete_nllb)
        for b in (self.btn_nllb_download, self.btn_nllb_test, btn_open, self.btn_nllb_delete):
            row.addWidget(b)
        row.addStretch()
        sec.addLayout(row)
        sec.addWidget(self._muted(
            "Модель (~600 МБ) завантажується один раз і лежить поруч зі збіркою "
            "(тека models), а якщо туди не можна писати - у теці даних користувача. "
            "Ліцензія ваг NLLB-200: CC-BY-NC 4.0 (некомерційна)."))

        # --- Tesseract ---
        sec = self._section(lay, "Мовні моделі Tesseract")
        self.tess_status = QtWidgets.QLabel()
        self.tess_status.setWordWrap(True)
        self.tess_status.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        sec.addWidget(self.tess_status)
        row = QtWidgets.QHBoxLayout()
        btn = QtWidgets.QPushButton("Відкрити теку")
        btn.setObjectName("BtnSecondary")
        btn.clicked.connect(
            lambda: _open_dir(os.path.join(tesseract_setup.USER_TESSDATA_ROOT, "tessdata")))
        row.addWidget(btn)
        row.addStretch()
        sec.addLayout(row)
        sec.addWidget(self._muted(
            "Додаткові мови розпізнавання докачуються автоматично, коли ви "
            "обираєте мову, якої ще немає."))

        # --- гарячі клавіші ---
        sec = self._section(lay, "Гарячі клавіші")
        grid = QtWidgets.QGridLayout()
        for r, (keys, text) in enumerate(self._shortcuts):
            key_label = QtWidgets.QLabel(f"<b>{keys}</b>")
            grid.addWidget(key_label, r, 0)
            grid.addWidget(QtWidgets.QLabel(text), r, 1)
        grid.setColumnStretch(1, 1)
        sec.addLayout(grid)

        # --- вікно ---
        sec = self._section(lay, "Вікно")
        row = QtWidgets.QHBoxLayout()
        btn = QtWidgets.QPushButton("Скинути розмір і позицію вікна")
        btn.setObjectName("BtnSecondary")
        btn.clicked.connect(self._reset_window)
        row.addWidget(btn)
        row.addStretch()
        sec.addLayout(row)
        sec.addWidget(self._muted("Застосується при наступному запуску."))

        lay.addStretch()

    # ------------------------------------------------------ логіка --
    def showEvent(self, event):
        self.refresh()
        super().showEvent(event)

    def refresh(self):
        forced = int(app_settings().value("ocr/workers", 0) or 0)
        self.workers_combo.blockSignals(True)
        self.workers_combo.setCurrentIndex(
            max(0, self.workers_combo.findData(forced)))
        self.workers_combo.blockSignals(False)

        path = nllb.find_model()
        if path:
            mb = _dir_size(path) / 1048576
            self.nllb_status.setText(f"✔ Завантажена ({mb:.0f} МБ)\n{path}")
        else:
            self.nllb_status.setText(
                "Не завантажена. Буде запропоновано при першому перекладі.\n"
                f"Куди: {nllb.download_target_hint()}")
        self.btn_nllb_download.setEnabled(path is None)
        self.btn_nllb_delete.setEnabled(path is not None)
        self.btn_nllb_test.setEnabled(path is not None)

        tess_dir = os.path.join(tesseract_setup.USER_TESSDATA_ROOT, "tessdata")
        langs = sorted(f[:-len(".traineddata")] for f in os.listdir(tess_dir)
                       if f.endswith(".traineddata")) if os.path.isdir(tess_dir) else []
        cmd = tesseract_setup.TESSERACT_CMD or "не знайдено"
        extra = f"Завантажені мови: {', '.join(langs)}" if langs else "Додаткових мов не завантажено."
        self.tess_status.setText(f"Tesseract: {cmd}\n{extra}\n{tess_dir}")

    def _save_workers(self):
        app_settings().setValue("ocr/workers", int(self.workers_combo.currentData() or 0))

    def _download_nllb(self):
        ensure_translation_model(self)
        self.refresh()

    TEST_SAMPLES = [
        ("ukr_Cyrl", "eng_Latn", "Доброго дня! Як у вас справи? Сьогодні гарна погода."),
        ("eng_Latn", "ukr_Cyrl", "The weather is nice today, and we are going to the park."),
        ("rus_Cyrl", "ukr_Cyrl", "Это простой пример текста для проверки перевода."),
    ]

    def _test_nllb(self):
        """Переклад кількох контрольних речень: показує, чи модель працює,
        незалежно від OCR, мови оригіналу та розбиття на рядки."""
        import time

        def work(report, cancel):
            report(0, 0, "Завантаження моделі в пам'ять...")
            tr = nllb.get_translator()
            results = []
            for src, tgt, text in self.TEST_SAMPLES:
                t0 = time.time()
                out = tr.translate([text], src, tgt)[0]
                results.append((src, tgt, text, out, time.time() - t0))
            return results

        results, error, cancelled = run_with_progress(self, "Перевірка перекладу", work)
        if cancelled:
            return
        if error:
            QtWidgets.QMessageBox.warning(self, "Помилка перекладу", error)
            return
        lines = []
        for src, tgt, text, out, secs in results:
            lines.append(f"{src} → {tgt} ({secs:.1f} с)\n  {text}\n  ⇒ {out}")
        QtWidgets.QMessageBox.information(
            self, "Результат перевірки", "\n\n".join(lines))

    def _open_nllb_dir(self):
        path = nllb.find_model()
        _open_dir(path if path else os.path.dirname(nllb.download_target()))

    def _delete_nllb(self):
        path = nllb.find_model()
        if not path:
            return
        ans = QtWidgets.QMessageBox.question(
            self, "Видалити модель?",
            f"Буде видалено теку:\n{path}\n\nЗавантажити її знову можна "
            "будь-коли (потрібен інтернет).",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel,
            QtWidgets.QMessageBox.Cancel)
        if ans != QtWidgets.QMessageBox.Yes:
            return
        nllb.unload()
        try:
            shutil.rmtree(path)
        except OSError as e:
            QtWidgets.QMessageBox.warning(self, "Не вдалося видалити", str(e))
        self.refresh()

    def _reset_window(self):
        app_settings().remove("window/geometry")
        QtWidgets.QMessageBox.information(
            self, "Готово", "Розмір вікна буде скинуто при наступному запуску.")
