"""
Автоматичне виявлення та встановлення Tesseract OCR.

Логіка узгоджена з ocr.find_tesseract_cmd(): спочатку перевіряємо, чи
Tesseract вже є (бандлений бінарник / системний PATH / типові шляхи
Windows). Якщо немає - НЕ показуємо простирадло інструкцій, а
пропонуємо користувачу встановити одним коротким підтвердженням; якщо
той погоджується, самі запускаємо встановлення через системний
пакетний менеджер (Linux: apt/dnf/pacman/zypper, з підняттям прав через
pkexec), winget (Windows) або Homebrew (macOS) - кожен у власному
окремому скрипті в installers/.

Головна точка входу - ensure_tesseract_available(parent_widget):
викликати перед початком OCR-обробки замість прямої перевірки
TESSERACT_CMD.
"""
import os
import platform
import shutil

from PyQt5 import QtCore, QtWidgets

from . import ocr

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INSTALLERS_DIR = os.path.join(SCRIPT_DIR, "installers")

# (бінарник пакетного менеджера для виявлення -> відповідний скрипт)
_LINUX_PACKAGE_MANAGERS = [
    ("apt-get", "install_apt.sh"),
    ("dnf", "install_dnf.sh"),
    ("pacman", "install_pacman.sh"),
    ("zypper", "install_zypper.sh"),
]


def _detect_linux_installer_script():
    """Повертає шлях до скрипта встановлення під виявлений пакетний
    менеджер дистрибутива, або None, якщо жодного з відомих не знайдено."""
    for pm_binary, script_name in _LINUX_PACKAGE_MANAGERS:
        if shutil.which(pm_binary):
            return os.path.join(INSTALLERS_DIR, script_name)
    return None


def _run_command_responsively(program, args, timeout_ms=600_000):
    """Запускає зовнішню команду через QProcess і чекає завершення в
    локальному циклі подій: інтерфейс лишається відповідним (вікно не
    "зависає"), поки, наприклад, система показує власний графічний
    запит пароля (pkexec/polkit) або UAC (winget).

    Повертає (успіх: bool, повідомлення_про_помилку: str).
    """
    process = QtCore.QProcess()
    loop = QtCore.QEventLoop()
    process.finished.connect(loop.quit)
    process.errorOccurred.connect(loop.quit)

    process.start(program, args)
    if not process.waitForStarted(5000):
        return False, "Не вдалося запустити процес встановлення."

    timed_out = {"value": False}

    def _on_timeout():
        timed_out["value"] = True
        loop.quit()

    timer = QtCore.QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(_on_timeout)
    timer.start(timeout_ms)

    loop.exec_()
    timer.stop()

    if timed_out["value"] or process.state() != QtCore.QProcess.NotRunning:
        process.kill()
        process.waitForFinished(3000)
        return False, "Перевищено час очікування встановлення."

    exit_code = process.exitCode()
    stderr = bytes(process.readAllStandardError()).decode("utf-8", errors="ignore").strip()

    if exit_code == 0:
        return True, ""
    return False, stderr[-500:] if stderr else f"Код завершення: {exit_code}"


def _install_linux(parent_widget):
    pkexec = shutil.which("pkexec")
    if not pkexec:
        return False, "Не знайдено pkexec для запиту прав адміністратора."

    script = _detect_linux_installer_script()
    if not script:
        return False, "Не вдалося визначити пакетний менеджер цього дистрибутива."

    return _run_command_responsively(pkexec, ["sh", script])


def _install_windows(parent_widget):
    if not shutil.which("winget"):
        return False, "winget не знайдено в системі."

    script = os.path.join(INSTALLERS_DIR, "install_windows.ps1")
    powershell = shutil.which("powershell") or "powershell"
    return _run_command_responsively(
        powershell, ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script]
    )


def _install_macos(parent_widget):
    if not shutil.which("brew"):
        return False, "Homebrew не знайдено в системі."

    script = os.path.join(INSTALLERS_DIR, "install_macos.sh")
    return _run_command_responsively("sh", [script])


_INSTALLERS_BY_SYSTEM = {
    "Linux": _install_linux,
    "Windows": _install_windows,
    "Darwin": _install_macos,
}


def ensure_tesseract_available(parent_widget=None):
    """
    Перевіряє наявність Tesseract OCR.

    Якщо знайдено - одразу повертає шлях до нього.
    Якщо ні - показує коротке підтвердження (без інструкцій) і, за
    згодою користувача, встановлює сам через системний пакетний
    менеджер. Повертає шлях до щойно встановленого бінарника, або
    None, якщо користувач відмовився чи встановлення не вдалося.
    """
    cmd = ocr.find_tesseract_cmd()
    if cmd:
        ocr.set_tesseract_cmd(cmd)
        return cmd

    choice = QtWidgets.QMessageBox.question(
        parent_widget,
        "Tesseract OCR не знайдено",
        "Для розпізнавання тексту потрібен Tesseract OCR.\nВстановити зараз?",
        QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel,
        QtWidgets.QMessageBox.Ok,
    )
    if choice != QtWidgets.QMessageBox.Ok:
        return None

    installer = _INSTALLERS_BY_SYSTEM.get(platform.system())
    if installer is None:
        QtWidgets.QMessageBox.warning(
            parent_widget, "Не вдалося встановити",
            "Автоматичне встановлення недоступне на цій ОС.",
        )
        return None

    progress = QtWidgets.QProgressDialog(
        "Встановлення Tesseract OCR...", None, 0, 0, parent_widget
    )
    progress.setWindowTitle("Зачекайте")
    progress.setCancelButton(None)
    progress.setWindowModality(QtCore.Qt.WindowModal)
    progress.setMinimumDuration(0)
    progress.show()
    QtWidgets.QApplication.processEvents()

    try:
        ok, err = installer(parent_widget)
    finally:
        progress.close()

    if not ok:
        QtWidgets.QMessageBox.warning(
            parent_widget, "Не вдалося встановити",
            "Встановлення Tesseract OCR не вдалося.\n" + err,
        )
        return None

    new_cmd = ocr.find_tesseract_cmd()
    if new_cmd:
        ocr.set_tesseract_cmd(new_cmd)
        QtWidgets.QMessageBox.information(
            parent_widget, "Готово", "Tesseract OCR успішно встановлено."
        )
        return new_cmd

    QtWidgets.QMessageBox.warning(
        parent_widget, "Не вдалося встановити",
        "Встановлення завершилось, але Tesseract OCR досі не знайдено.\n"
        "Можливо, варто перезапустити програму.",
    )
    return None
