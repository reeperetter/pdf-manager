"""Діалог завантаження моделі перекладу NLLB-200 (Qt)."""
from PyQt5 import QtWidgets

from modules.common.progress_task import run_with_progress
from . import nllb


def ensure_translation_model(parent_widget):
    """Перевіряє наявність моделі NLLB; якщо її немає - питає дозволу й
    завантажує у фоновому потоці з прогресом і кнопкою 'Скасувати'.
    Повертає True, якщо можна продовжувати."""
    spec = nllb.get_spec()
    if nllb.find_model(spec.id):
        return True

    try:
        target = nllb.download_target(spec.id)
    except nllb.ModelDownloadError as e:
        QtWidgets.QMessageBox.warning(parent_widget, "Немає куди зберегти", str(e))
        return False

    choice = QtWidgets.QMessageBox.question(
        parent_widget, "Потрібна модель перекладу",
        f"Для офлайн-перекладу потрібна мовна модель {spec.title} "
        f"(~{spec.size_mb} МБ, потрібен інтернет). Вона завантажується "
        f"один раз у теку:\n{target}\n\nПісля цього переклад працює без "
        "інтернету, текст документів нікуди не надсилається.\n\n"
        "Іншу модель можна обрати в Налаштуваннях.\n\nЗавантажити зараз?",
        QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel,
        QtWidgets.QMessageBox.Ok)
    if choice != QtWidgets.QMessageBox.Ok:
        return False

    def work(report, cancel):
        def on_progress(done, total, name):
            report(done, total,
                   f"{name}: {done / 1048576:.0f} / {total / 1048576:.0f} МБ")
        nllb.download_model(on_progress, cancel, spec.id)

    _res, error, _cancelled = run_with_progress(
        parent_widget, "Завантаження моделі перекладу", work)
    if error:
        QtWidgets.QMessageBox.warning(
            parent_widget, "Не вдалося завантажити модель", error)
        return False
    return nllb.find_model(spec.id) is not None
