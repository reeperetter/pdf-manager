"""Журнал роботи й аварій.

Збірка Windows запускається без консолі (--windowed), тому, коли процес
"вилітає" через помилку в нативній бібліотеці (CTranslate2, OpenMP, Qt),
користувач не бачить жодного повідомлення. Тут:

  * звичайний журнал у ``<тека даних>/logs/pdfmanager.log`` (ротація);
  * faulthandler пише в ``crash.log`` трасування, якщо процес упав через
    segfault / abort (у тому числі зі всіх потоків);
  * необроблені винятки (головний потік і робочі потоки) теж потрапляють у журнал.
"""
import faulthandler
import logging
import logging.handlers
import os
import sys
import threading

_crash_file = None  # тримаємо відкритим, поки живе процес
logger = logging.getLogger("pdfmanager")


def user_data_dir():
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "PDFManager")


def log_dir():
    return os.path.join(user_data_dir(), "logs")


def setup():
    """Вмикає журнал і перехоплення аварій. Безпечно викликати повторно."""
    global _crash_file
    if _crash_file is not None:
        return log_dir()
    try:
        d = log_dir()
        os.makedirs(d, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            os.path.join(d, "pdfmanager.log"), maxBytes=1_000_000,
            backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(threadName)s] %(levelname)s %(message)s"))
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)

        _crash_file = open(os.path.join(d, "crash.log"), "a", encoding="utf-8")
        _crash_file.write(f"\n=== запуск, pid {os.getpid()} ===\n")
        _crash_file.flush()
        faulthandler.enable(file=_crash_file, all_threads=True)

        def _excepthook(tp, val, tb):
            logger.error("Необроблений виняток", exc_info=(tp, val, tb))
            sys.__excepthook__(tp, val, tb)

        def _thread_hook(args):
            logger.error("Виняток у потоці %s", getattr(args.thread, "name", "?"),
                         exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

        sys.excepthook = _excepthook
        threading.excepthook = _thread_hook
        logger.info("Запуск, Python %s, платформа %s", sys.version.split()[0], sys.platform)
        return d
    except Exception:
        return None  # журнал не критичний - програма працює й без нього
