"""Довга операція у фоновому потоці з діалогом прогресу і скасуванням."""
import threading

from PyQt5 import QtCore, QtWidgets


def run_with_progress(parent, title, work):
    """Виконує work(report, cancel_event) у потоці, показуючи модальний
    QProgressDialog із кнопкою 'Скасувати'.

    report(done, total, text): прогрес (total=0 - невизначений);
    cancel_event: threading.Event, виставляється кнопкою.
    Повертає (результат, текст_помилки | None, скасовано)."""
    state = {"done": 0, "total": 0, "text": "Підготовка...",
             "result": None, "error": None, "finished": False}
    cancel = threading.Event()

    def report(done, total, text=""):
        state["done"], state["total"] = done, total
        if text:
            state["text"] = text

    def target():
        try:
            state["result"] = work(report, cancel)
        except Exception as e:  # показуємо користувачу, не губимо
            if not cancel.is_set():
                state["error"] = str(e) or type(e).__name__
        finally:
            state["finished"] = True

    dlg = QtWidgets.QProgressDialog(state["text"], "Скасувати", 0, 1000, parent)
    dlg.setWindowTitle(title)
    dlg.setWindowModality(QtCore.Qt.WindowModal)
    dlg.setMinimumDuration(0)
    dlg.setAutoClose(False)
    dlg.setAutoReset(False)
    dlg.canceled.connect(cancel.set)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    dlg.show()

    loop = QtCore.QEventLoop()
    timer = QtCore.QTimer(dlg)

    def tick():
        total = state["total"]
        if total:
            dlg.setMaximum(1000)
            dlg.setValue(min(1000, int(state["done"] * 1000 / total)))
        else:
            dlg.setMaximum(0)  # невизначений індикатор
        dlg.setLabelText(state["text"])
        if state["finished"]:
            loop.quit()

    timer.timeout.connect(tick)
    timer.start(120)
    loop.exec_()
    timer.stop()
    thread.join()
    dlg.canceled.disconnect(cancel.set)  # close() сам шле 'canceled'
    dlg.close()
    return state["result"], state["error"], cancel.is_set()
