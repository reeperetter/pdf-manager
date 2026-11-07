"""Діалог завантаження моделі перекладу NLLB-200 (Qt)."""
import threading

from PyQt5 import QtCore, QtWidgets

from . import nllb


def ensure_translation_model(parent_widget):
    """Перевіряє наявність моделі NLLB; якщо її немає - питає дозволу й
    завантажує у фоновому потоці з прогресом і кнопкою 'Скасувати'.
    Повертає True, якщо можна продовжувати."""
    if nllb.find_model():
        return True

    try:
        target = nllb.download_target()
    except nllb.ModelDownloadError as e:
        QtWidgets.QMessageBox.warning(parent_widget, "Немає куди зберегти", str(e))
        return False

    choice = QtWidgets.QMessageBox.question(
        parent_widget, "Потрібна модель перекладу",
        f"Для офлайн-перекладу потрібна мовна модель NLLB-200 "
        f"(~{nllb.APPROX_SIZE_MB} МБ, потрібен інтернет). Вона завантажується "
        f"один раз у теку:\n{target}\n\nПісля цього переклад працює без "
        "інтернету, текст документів нікуди не надсилається.\n\n"
        "Завантажити зараз?",
        QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel,
        QtWidgets.QMessageBox.Ok)
    if choice != QtWidgets.QMessageBox.Ok:
        return False

    state = {"done": 0, "total": 0, "name": "", "error": None, "finished": False}
    cancel = threading.Event()

    def on_progress(done, total, name):
        state["done"], state["total"], state["name"] = done, total, name

    def work():
        try:
            nllb.download_model(on_progress, cancel)
        except nllb.DownloadCancelled:
            pass
        except Exception as e:  # показуємо користувачу
            state["error"] = str(e)
        finally:
            state["finished"] = True

    dlg = QtWidgets.QProgressDialog(
        "Підготовка...", "Скасувати", 0, 1000, parent_widget)
    dlg.setWindowTitle("Завантаження моделі перекладу")
    dlg.setWindowModality(QtCore.Qt.WindowModal)
    dlg.setMinimumDuration(0)
    dlg.setAutoClose(False)
    dlg.setAutoReset(False)
    dlg.canceled.connect(cancel.set)

    thread = threading.Thread(target=work, daemon=True)
    thread.start()
    dlg.show()

    timer = QtCore.QTimer(dlg)

    def tick():
        total = state["total"]
        if total:
            dlg.setValue(min(1000, int(state["done"] * 1000 / total)))
            dlg.setLabelText(
                f"{state['name']}: {state['done'] / 1048576:.0f} / "
                f"{total / 1048576:.0f} МБ")
        if state["finished"]:
            loop.quit()

    loop = QtCore.QEventLoop()
    timer.timeout.connect(tick)
    timer.start(150)
    loop.exec_()
    timer.stop()
    thread.join()
    dlg.canceled.disconnect(cancel.set)  # close() сам шле 'canceled'
    dlg.close()

    if state["error"]:
        QtWidgets.QMessageBox.warning(
            parent_widget, "Не вдалося завантажити модель", state["error"])
        return False
    return nllb.find_model() is not None
