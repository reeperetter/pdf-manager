"""Спільний фоновий виконавець пакетної обробки файлів.

Раніше обрізка/поворот/стиснення крутили цикл у потоці інтерфейсу з
QApplication.processEvents(): вікно "зависало" на великих файлах, а
скасувати обробку було неможливо. BatchRunner виконує функцію для кожного
елемента в окремому потоці, а до інтерфейсу повертається сигналами
(вони доставляються в потік GUI).

    runner = BatchRunner(self, self.btn_process_batch, self.progress_bar)
    bottom_layout.addWidget(runner.cancel_button)   # кнопка "Скасувати"
    runner.start(paths, work, on_item=..., on_finished=...)

work(item) викликається у фоновому потоці й НЕ повинна торкатись віджетів;
повертає будь-яке значення (його отримує on_item/on_finished) або кидає
виняток - тоді Outcome.error містить текст помилки.
"""
import threading
from collections import namedtuple

from PyQt5 import QtCore, QtWidgets

Outcome = namedtuple("Outcome", "item value error")


class BatchRunner(QtCore.QObject):
    item_done = QtCore.pyqtSignal(int, object)   # індекс, Outcome
    finished = QtCore.pyqtSignal(list, bool)     # [Outcome], скасовано?

    def __init__(self, owner, start_button, progress_bar):
        super().__init__(owner)
        self._start_button = start_button
        self._progress = progress_bar
        self._cancel = threading.Event()
        self._thread = None
        self._outcomes = []
        self._on_item = None
        self._on_finished = None

        self.cancel_button = QtWidgets.QPushButton("Скасувати")
        self.cancel_button.setObjectName("BtnSecondary")
        self.cancel_button.setMinimumHeight(35)
        self.cancel_button.setVisible(False)
        self.cancel_button.clicked.connect(self.cancel)

        self.item_done.connect(self._handle_item)
        self.finished.connect(self._handle_finished)

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def cancel(self):
        self._cancel.set()
        self.cancel_button.setEnabled(False)

    def start(self, items, work, on_item=None, on_finished=None):
        if self.running:
            return False
        items = list(items)
        self._on_item, self._on_finished = on_item, on_finished
        self._outcomes = []
        self._cancel.clear()
        self._progress.setMaximum(max(1, len(items)))
        self._progress.setValue(0)
        self._start_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.cancel_button.setVisible(True)

        def run():
            outcomes = []
            for i, item in enumerate(items):
                if self._cancel.is_set():
                    break
                try:
                    out = Outcome(item, work(item), None)
                except Exception as e:  # помилка одного файлу не зупиняє решту
                    out = Outcome(item, None, str(e) or type(e).__name__)
                outcomes.append(out)
                self.item_done.emit(i, out)
            self.finished.emit(outcomes, self._cancel.is_set())

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        return True

    def _handle_item(self, index, outcome):
        self._outcomes.append(outcome)
        self._progress.setValue(len(self._outcomes))
        if self._on_item:
            self._on_item(index, outcome)

    def _handle_finished(self, outcomes, cancelled):
        self._start_button.setEnabled(True)
        self.cancel_button.setVisible(False)
        if self._on_finished:
            self._on_finished(outcomes, cancelled)
