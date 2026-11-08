"""
Пошук і налаштування Tesseract: виконуваний файл, мовні моделі, їх
завантаження.

Стан (TESSERACT_CMD, USER_TESSDATA_ROOT) живе в цьому модулі; решта коду
читає його як tesseract_setup.TESSERACT_CMD, щоб бачити оновлення після
автовстановлення (set_tesseract_cmd).
"""
import contextlib
import glob
import os
import shutil
import sys
import threading

import pytesseract

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))


def _refresh_path_from_registry():
    """Windows-only: дочитує актуальний PATH напряму з реєстру (і
    системний, і користувацький).

    os.environ["PATH"] успадковується ОДИН РАЗ при старті процесу -
    якщо після запуску PDFManager.exe winget дописав Tesseract у PATH
    (системний чи користувацький), поточний процес цього не побачить,
    доки його не перезапустять. shutil.which("tesseract") у такому разі
    мовчки не знаходить щойно встановлений бінарник, і find_tesseract_cmd()
    щоразу скочується до "не знайдено" - навіть якщо встановлення
    насправді пройшло успішно. Читаємо PATH напряму з реєстру (так само,
    як це робить сам Провідник після "Варіант застосувати зміни PATH")
    і домішуємо до os.environ["PATH"] поточного процесу."""
    if os.name != "nt":
        return
    try:
        import winreg
    except ImportError:
        return

    pieces = []
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
        ) as key:
            pieces.append(winreg.QueryValueEx(key, "Path")[0])
    except OSError:
        pass
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            pieces.append(winreg.QueryValueEx(key, "Path")[0])
    except OSError:
        pass

    if not pieces:
        return
    fresh_path = ";".join(p for p in pieces if p)
    os.environ["PATH"] = fresh_path + ";" + os.environ.get("PATH", "")


_ENV_LOCK = threading.Lock()
_ENV_DEPTH = 0
_ENV_SAVED = {}


@contextlib.contextmanager
def _external_tesseract_env():
    """
    Захист від класичної проблеми PyInstaller на Linux/macOS: бандлер
    підміняє LD_LIBRARY_PATH (macOS: DYLD_LIBRARY_PATH) на шлях до
    власних забандлених .so-бібліотек, щоб рідні розширення програми
    (cv2, PyQt5 тощо) коректно завантажувались. Але БУДЬ-ЯКИЙ зовнішній
    процес, який ми запускаємо як subprocess (системний tesseract),
    успадковує це ж середовище - і якщо версії системних бібліотек
    tesseract (libpng/libjpeg/liblept тощо) відрізняються від
    забандлених нами, зовнішній бінарник падає з "exit status 1" при
    найпершому ж запуску ("tesseract --version").

    PyInstaller зберігає оригінальне (дофреймворкове) значення під
    тим самим ім'ям зі суфіксом "_ORIG" - тимчасово повертаємо його на
    час виклику pytesseract, а одразу після виклику відновлюємо назад
    (щоб не зламати подальше лінивe довантаження власних забандлених
    бібліотек, напр. cv2 для випрямлення сторінки).

    Поза frozen-збіркою (звичайний запуск через `uv run main.py`) ці
    змінні відсутні, і цей менеджер контексту нічого не робить.

    ВАЖЛИВО: перевіряємо наявність самого LD_LIBRARY_PATH, а НЕ
    LD_LIBRARY_PATH_ORIG! За документацією PyInstaller, "_ORIG"
    з'являється, лише якщо LD_LIBRARY_PATH вже існував У КОРИСТУВАЧА
    до запуску програми. У типового користувача, який ніколи вручну не
    виставляв цю змінну (переважна більшість), "_ORIG" не з'явиться
    взагалі - і якщо перевіряти саме її, фікс не спрацює в
    найпоширенішому випадку. Коли "_ORIG" немає, правильна "оригінальна"
    поведінка - просто прибрати LD_LIBRARY_PATH повністю (бо PyInstaller
    сам створив її з нуля)."""
    # Лічильник входів + замок: OCR сторінок іде паралельно в кількох
    # потоках, і без цього перший потік, що вийшов, повернув би змінні
    # в середовище, поки інший ще запускає tesseract.
    global _ENV_DEPTH, _ENV_SAVED
    keys = ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH")
    with _ENV_LOCK:
        if _ENV_DEPTH == 0:
            _ENV_SAVED = {}
            for key in keys:
                if key not in os.environ:
                    continue
                _ENV_SAVED[key] = os.environ.get(key)
                orig_value = os.environ.get(key + "_ORIG")
                if orig_value:
                    os.environ[key] = orig_value
                else:
                    os.environ.pop(key, None)
        _ENV_DEPTH += 1
    try:
        yield
    finally:
        with _ENV_LOCK:
            _ENV_DEPTH -= 1
            if _ENV_DEPTH == 0:
                for key, value in _ENV_SAVED.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value
                _ENV_SAVED = {}


def find_tesseract_cmd():
    """Шукає бінарник tesseract.

    Порядок пошуку: 1) портативний Tesseract у теці "tesseract" поруч з
    PDFManager.exe (його кладе збірка - користувачам нічого не треба
    встановлювати); 2) системний tesseract з PATH (типовий сценарій під час
    розробки на Linux: `sudo apt install tesseract-ocr tesseract-ocr-ukr
    tesseract-ocr-rus`); 3) типові шляхи встановлення на Windows, де
    інсталятор не завжди дописує програму в PATH."""
    exe_name = "tesseract.exe" if os.name == "nt" else "tesseract"
    # Портативна збірка: тека "tesseract" ПОРЯД з PDFManager.exe (її кладе
    # build.yml), а також (для сумісності) поруч зі скриптом.
    exe_dir = (os.path.dirname(os.path.abspath(sys.executable))
               if getattr(sys, "frozen", False) else _PROJECT_ROOT)
    for bundled_dir in (os.path.join(exe_dir, "tesseract"),
                        os.path.join(SCRIPT_DIR, "tesseract")):
        bundled_bin = os.path.join(bundled_dir, exe_name)
        if os.path.isfile(bundled_bin):
            tessdata = os.path.join(bundled_dir, "tessdata")
            if os.path.isdir(tessdata):
                os.environ["TESSDATA_PREFIX"] = tessdata
            return bundled_bin

    if os.name == "nt":
        # winget міг дописати PATH ПІСЛЯ старту цього процесу - без цього
        # щойно встановлений tesseract не знайдеться через PATH, доки
        # програму не перезапустять вручну.
        _refresh_path_from_registry()

    system_bin = shutil.which("tesseract")
    if system_bin:
        return system_bin

    if os.name == "nt":
        local_appdata = os.environ.get("LOCALAPPDATA", "")
        candidates = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]
        if local_appdata:
            # winget install --silent БЕЗ підвищення прав типово ставить
            # пакет у профіль користувача, а не в Program Files - раніше
            # ці шляхи взагалі не перевірялись, тож find_tesseract_cmd()
            # мовчки не знаходив щойно встановлений Tesseract, і при
            # кожному наступному запуску програма знову пропонувала
            # "встановити", хоча він уже стояв.
            candidates.append(
                os.path.join(local_appdata, "Programs", "Tesseract-OCR", "tesseract.exe")
            )
            candidates.extend(
                glob.glob(os.path.join(
                    local_appdata, "Microsoft", "WinGet", "Packages",
                    "UB-Mannheim.TesseractOCR_*", "tesseract.exe",
                ))
            )
        for var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
            base = os.environ.get(var)
            if base:
                candidates.append(os.path.join(
                    base, "Tesseract-OCR", "tesseract.exe"))
        candidates.extend(_windows_registry_tesseract_candidates())
        for p in candidates:
            if os.path.isfile(p):
                return p
    return None


def _windows_registry_tesseract_candidates():
    """Windows-only: шляхи tesseract.exe з реєстру. Інсталятор UB Mannheim
    записує теку встановлення в HKLM\\SOFTWARE\\Tesseract-OCR (ключ
    InstallDir) і в розділ Uninstall - це знаходить Tesseract навіть тоді,
    коли його встановлено в нестандартну теку чи на інший диск."""
    try:
        import winreg
    except ImportError:
        return []
    found = []
    views = (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY)
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for view in views:
            try:
                with winreg.OpenKey(root, r"SOFTWARE\Tesseract-OCR", 0,
                                    winreg.KEY_READ | view) as key:
                    found.append(os.path.join(
                        winreg.QueryValueEx(key, "InstallDir")[0],
                        "tesseract.exe"))
            except OSError:
                pass
            try:
                with winreg.OpenKey(
                        root,
                        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                        0, winreg.KEY_READ | view) as uninstall:
                    i = 0
                    while True:
                        try:
                            sub = winreg.EnumKey(uninstall, i)
                        except OSError:
                            break
                        i += 1
                        if "tesseract" not in sub.lower():
                            continue
                        try:
                            with winreg.OpenKey(uninstall, sub) as k:
                                loc = winreg.QueryValueEx(k, "InstallLocation")[0]
                                if loc:
                                    found.append(os.path.join(loc, "tesseract.exe"))
                        except OSError:
                            pass
            except OSError:
                pass
    return found


TESSERACT_CMD = find_tesseract_cmd()

# --------------------------------------------------------------------
# Мовні моделі (*.traineddata). winget/інсталятор Tesseract ставить лише
# eng та osd, тому українську/російську програма докачує сама в
# користувацьку теку (вона не потребує прав адміністратора).
# Структура: <USER_TESSDATA_ROOT>/tessdata/*.traineddata і КОПІЇ тих самих
# файлів просто в <USER_TESSDATA_ROOT>/ - різні версії Tesseract по-різному
# тлумачать TESSDATA_PREFIX (4.x: батьківська тека, 5.x: сама тека з
# моделями), тому лежать обидва варіанти.
def _user_tessdata_root():
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(
            os.path.expanduser("~"), ".local", "share")
    return os.path.join(base, "PDFManager", "tesseract-data")


USER_TESSDATA_ROOT = _user_tessdata_root()
_TESSDATA_FAST_URL = (
    "https://github.com/tesseract-ocr/tessdata_fast/raw/main/{lang}.traineddata")


def required_languages(source_lang):
    """Мови, потрібні для запуску з обраною мовою оригіналу (+ osd для
    визначення орієнтації сторінки)."""
    if source_lang == "auto":
        langs = ["eng", "ukr", "rus"]
    else:
        langs = [p for p in (source_lang or "eng").split("+") if p]
    return langs + ["osd"]


def _tessdata_dirs():
    """Теки, де Tesseract може шукати моделі."""
    dirs = []
    prefix = os.environ.get("TESSDATA_PREFIX")
    if prefix:
        dirs += [prefix, os.path.join(prefix, "tessdata")]
    if TESSERACT_CMD:
        dirs.append(os.path.join(os.path.dirname(TESSERACT_CMD), "tessdata"))
    dirs += [os.path.join(USER_TESSDATA_ROOT, "tessdata"), USER_TESSDATA_ROOT]
    for d in ("/usr/share/tesseract-ocr/5/tessdata",
              "/usr/share/tesseract-ocr/4.00/tessdata",
              "/usr/share/tessdata", "/usr/share/tesseract/tessdata"):
        dirs.append(d)
    return dirs


def _find_traineddata(lang):
    for d in _tessdata_dirs():
        p = os.path.join(d, f"{lang}.traineddata")
        if os.path.isfile(p):
            return p
    return None


def missing_languages(source_lang):
    """Список потрібних мов, для яких немає .traineddata."""
    return [l for l in required_languages(source_lang)
            if not _find_traineddata(l)]


def use_user_tessdata():
    """Якщо в користувацькій теці є повний набір моделей - спрямовуємо
    Tesseract на неї (TESSDATA_PREFIX), інакше нічого не міняємо."""
    if os.path.isfile(os.path.join(USER_TESSDATA_ROOT, "eng.traineddata")) and \
            os.path.isfile(os.path.join(USER_TESSDATA_ROOT, "tessdata", "eng.traineddata")):
        os.environ["TESSDATA_PREFIX"] = USER_TESSDATA_ROOT


_MIN_TRAINEDDATA_BYTES = 100 * 1024


def _download_traineddata(lang, dst, cancel_event=None, byte_cb=None):
    """Качає {lang}.traineddata у dst; перевіряє розмір і що це не
    HTML-сторінка помилки (мережеві фільтри/проксі)."""
    import urllib.request

    url = _TESSDATA_FAST_URL.format(lang=lang)
    tmp = dst + ".part"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PDFManager"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            expected = int(resp.headers.get("Content-Length") or 0)
            got = 0
            with open(tmp, "wb") as f:
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise RuntimeError("Скасовано користувачем.")
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    if byte_cb:
                        byte_cb(got, expected)
        size = os.path.getsize(tmp)
        if expected and size != expected:
            raise RuntimeError(f"розмір {size} замість {expected} байт")
        with open(tmp, "rb") as f:
            head = f.read(64)
        if size < _MIN_TRAINEDDATA_BYTES or head.lstrip().startswith(b"<"):
            raise RuntimeError("отримано некоректний файл (не traineddata)")
        os.replace(tmp, dst)
    except Exception as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise RuntimeError(
            f"Не вдалося завантажити мовну модель '{lang}': {e}")


def install_language_data(langs, progress_cb=None, cancel_event=None):
    """Кладе моделі в користувацьку теку: беремо вже наявні поруч із
    встановленим Tesseract (eng, osd), решту докачуємо з tessdata_fast.
    progress_cb(lang, index, total, got_bytes, expected_bytes).
    Піднімає RuntimeError з зрозумілим текстом при помилці."""
    import shutil

    sub = os.path.join(USER_TESSDATA_ROOT, "tessdata")
    os.makedirs(sub, exist_ok=True)

    # Користувацька тека має бути ПОВНОЮ (Tesseract не змішує теки), тому
    # разом із потрібними мовами переносимо сюди й eng та osd.
    wanted = list(dict.fromkeys(list(langs) + ["eng", "osd"]))
    for i, lang in enumerate(wanted):
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("Скасовано користувачем.")
        if progress_cb:
            progress_cb(lang, i, len(wanted), 0, 0)
        dst = os.path.join(sub, f"{lang}.traineddata")
        if not os.path.isfile(dst):
            src = _find_traineddata(lang)
            if src and not src.startswith(USER_TESSDATA_ROOT):
                shutil.copyfile(src, dst)
            else:
                _download_traineddata(
                    lang, dst, cancel_event,
                    (lambda g, e, lang=lang, i=i: progress_cb(
                        lang, i, len(wanted), g, e)) if progress_cb else None)
        copy2 = os.path.join(USER_TESSDATA_ROOT, f"{lang}.traineddata")
        if not os.path.isfile(copy2):
            shutil.copyfile(dst, copy2)
    use_user_tessdata()


use_user_tessdata()
if TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD


def set_tesseract_cmd(path):
    """Оновлює шлях до tesseract у цьому модулі й у pytesseract одразу,
    без перезапуску програми - викликається після успішного
    автовстановлення (див. tesseract_installer.py)."""
    global TESSERACT_CMD
    TESSERACT_CMD = path
    if path:
        pytesseract.pytesseract.tesseract_cmd = path
