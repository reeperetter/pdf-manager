import io
import os
import sys
import gc
import glob
import shutil
import time
import random
import queue
import threading
import traceback

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import tkinter.font as tkfont

# ---- Перевірка зовнішніх залежностей з дружнім повідомленням ----
MISSING = []
try:
    import fitz  # PyMuPDF
except ImportError:
    MISSING.append("pymupdf")
try:
    from PIL import Image
except ImportError:
    MISSING.append("pillow")
try:
    import pytesseract
except ImportError:
    MISSING.append("pytesseract")
try:
    from deep_translator import GoogleTranslator
except ImportError:
    MISSING.append("deep-translator")

if MISSING:
    print("Не вистачає пакетів. Встановіть їх командою:")
    print(f"    pip install {' '.join(MISSING)}")
    print("або просто:  pip install -r requirements.txt")
    sys.exit(1)


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BUNDLED_FONT = os.path.join(SCRIPT_DIR, "DejaVuSans.ttf")

FALLBACK_FONTS = [
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\calibri.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",         # шлях на Fedora/Nobara
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]


def find_unicode_font(user_path=None):
    """Повертає шлях до TTF-шрифту, що підтримує кирилицю.
    Спочатку перевіряє шрифт, вказаний користувачем, потім шрифт,
    що постачається разом зі скриптом, і насамкінець — типові
    системні шляхи."""
    if user_path and os.path.isfile(user_path):
        return user_path
    if os.path.isfile(BUNDLED_FONT):
        return BUNDLED_FONT
    for p in FALLBACK_FONTS:
        if os.path.isfile(p):
            return p
    return None


# Мови для Tesseract фіксовані (без вибору користувачем): українська,
# російська, англійська. Розбиті на два окремі OCR-проходи нижче
# (_LATIN_LANGS / _CYRILLIC_LANGS) - див. ocr_lines_from_image.


def find_tesseract_cmd():
    """Шукає бінарник tesseract.

    Порядок пошуку зроблено з розрахунком на майбутню портативну збірку
    (exe + папка поруч): 1) бандлений бінарник у підпапці "tesseract" поруч
    зі скриптом (саме туди ляже tesseract.exe/tesseract при пакуванні для
    розповсюдження — тоді користувачам не треба нічого встановлювати
    окремо); 2) системний tesseract з PATH (типовий сценарій під час
    розробки на Linux: `sudo apt install tesseract-ocr tesseract-ocr-ukr
    tesseract-ocr-rus`); 3) типові шляхи встановлення на Windows, де
    інсталятор не завжди дописує програму в PATH."""
    bundled_dir = os.path.join(SCRIPT_DIR, "tesseract")
    bundled_bin = os.path.join(
        bundled_dir, "tesseract.exe" if os.name == "nt" else "tesseract")
    if os.path.isfile(bundled_bin):
        tessdata = os.path.join(bundled_dir, "tessdata")
        if os.path.isdir(tessdata):
            os.environ["TESSDATA_PREFIX"] = tessdata
        return bundled_bin

    system_bin = shutil.which("tesseract")
    if system_bin:
        return system_bin

    if os.name == "nt":
        for p in (
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ):
            if os.path.isfile(p):
                return p
    return None


TESSERACT_CMD = find_tesseract_cmd()
if TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD


# =========================================================================
#  Допоміжні функції
# =========================================================================

def extract_lines_from_page(page):
    """Витягує рядки тексту з наявного текстового шару PDF (координати сторінки)."""
    lines = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            if not spans:
                continue
            text = "".join(s["text"] for s in spans).strip()
            if not text:
                continue
            x0 = min(s["bbox"][0] for s in spans)
            y0 = min(s["bbox"][1] for s in spans)
            x1 = max(s["bbox"][2] for s in spans)
            y1 = max(s["bbox"][3] for s in spans)
            lines.append(
                {"text": text, "bbox": (x0, y0, x1, y1), "page_coords": True}
            )
    return lines


def line_to_rect(line, scale_x, scale_y):
    """Перетворює bbox рядка у fitz.Rect (сторінкові координати)."""
    x0, y0, x1, y1 = line["bbox"]
    if line.get("page_coords"):
        return fitz.Rect(x0, y0, x1, y1)
    return fitz.Rect(x0 * scale_x, y0 * scale_y, x1 * scale_x, y1 * scale_y)


def line_to_pixel_bbox(line, scale_x, scale_y):
    """Перетворює bbox рядка у координати пікселів зображення."""
    x0, y0, x1, y1 = line["bbox"]
    if line.get("page_coords"):
        return (x0 / scale_x, y0 / scale_y, x1 / scale_x, y1 / scale_y)
    return line["bbox"]


def setup_gui_fonts(root):
    """Налаштовує шрифт з кирилицею та охайнішу тему для Tk/ttk (особливо на Linux).

    Повертає named-font (tkfont.Font) або None.

    Створює шрифт за іменем родини, вже відомої системі через fontconfig
    (`font create ... -family {Родина} -size N`), а не за шляхом до файлу —
    Tk такого API не має. Також примусово ставить `tk scaling 1.0` і задає
    розмір у пікселях — обхід відомого класу багів з розсинхроном
    DPI/scaling на деяких Linux-системах."""
    style = ttk.Style(root)

    if os.name != "nt":
        try:
            root.tk.call("tk", "scaling", 1.0)
        except tk.TclError:
            pass
        try:
            available = style.theme_names()
            for preferred in ("clam", "alt", "default"):
                if preferred in available:
                    style.theme_use(preferred)
                    break
        except tk.TclError:
            pass

    root.update_idletasks()  # без цього список родин часто неповний

    if os.name == "nt":
        return None

    try:
        families = sorted(set(tkfont.families(root)))
    except Exception:
        families = []

    # Шукаємо першу відому "хорошу" родину з повним покриттям кирилиці.
    candidates = [
        "DejaVu Sans", "Noto Sans", "Liberation Sans", "Ubuntu",
        "Cantarell", "FreeSans", "Droid Sans", "Open Sans", "Roboto",
    ]
    lower_map = {f.lower(): f for f in families}
    chosen_family = None
    for cand in candidates:
        if cand.lower() in lower_map:
            chosen_family = lower_map[cand.lower()]
            break
    if chosen_family is None:
        # запасний варіант: перша не-bitmap/не-symbol родина зі списку
        for f in families:
            low = f.lower()
            if low not in ("symbol", "wingdings", "webdings") and "fixed" not in low:
                chosen_family = f
                break

    if not chosen_family:
        return None

    try:
        # Розмір у ПІКСЕЛЯХ (від'ємне число) — обходить перерахунок point->pixel
        # через (можливо помилковий) tk scaling.
        app_font = tkfont.Font(root, family=chosen_family, size=-15)
        root.option_add("*Font", app_font)
        ttk_classes = (
            ".", "TLabel", "TButton", "TCheckbutton", "TRadiobutton",
            "TLabelframe", "TLabelframe.Label", "TEntry", "TCombobox",
            "TSpinbox", "TNotebook", "TNotebook.Tab", "Treeview",
            "Treeview.Heading", "TFrame", "TPanedwindow", "TProgressbar",
        )
        for element in ttk_classes:
            try:
                style.configure(element, font=app_font)
            except tk.TclError:
                pass
        # Перевизначаємо й самі системні іменовані шрифти Tk, щоб охопити
        # віджети, які їх використовують напряму (Listbox, Text, Entry).
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            try:
                tkfont.nametofont(name).configure(family=chosen_family, size=-15)
            except tk.TclError:
                pass
        return app_font
    except tk.TclError:
        return None


def preprocess_for_ocr(pil_img):
    """Готує зображення для Tesseract.

    На відміну від EasyOCR (нейромережа, стійка до "сирого" кольорового
    зображення), класичний Tesseract значно точніший на чистому
    чорно-білому вході з високим контрастом. Тому: переводимо в
    відтінки сірого й піднімаємо контраст (autocontrast). Якщо сторінка
    дрібна (низький DPI) - додатково збільшуємо, бо для Tesseract
    рекомендований мінімум ~300 DPI, а дрібні літери він банально не
    розпізнає."""
    from PIL import ImageOps
    gray = ImageOps.grayscale(pil_img)
    gray = ImageOps.autocontrast(gray, cutoff=1)
    # Tesseract впевнено читає літери приблизно від ~20-30px заввишки.
    # Якщо сторінка вузька (низький DPI/дрібний скан) - масштабуємо вгору.
    if gray.width < 1600:
        scale = 1600 / gray.width
        gray = gray.resize(
            (int(gray.width * scale), int(gray.height * scale)),
            Image.LANCZOS,
        )
    return gray


# Замість однієї об'єднаної мовної моделі "ukr+rus+eng" робимо ДВА окремі
# проходи Tesseract - латиницею (eng) і кирилицею (ukr+rus) - і обираємо
# кращий за впевненістю розпізнавання. Причина: кирилична "А", "Е", "Р",
# "С", "Т", "Х" тощо піксель-у-піксель ідентичні латинським - при спільній
# мовній моделі Tesseract час від часу віддає перевагу "не тому" алфавіту
# для однаково виглядаючих літер (класична проблема мульти-скриптового
# OCR), і в результат просочуються кириличні символи всередині
# англійського тексту (і навпаки). Два окремі проходи усувають саму
# можливість такої плутанини: "eng"-прохід фізично не вміє видати
# кириличний символ.
_LATIN_LANGS = "eng"
_CYRILLIC_LANGS = "ukr+rus"


def _run_tesseract_pass(proc_img, lang, config):
    try:
        return pytesseract.image_to_data(
            proc_img, lang=lang, config=config, output_type=pytesseract.Output.DICT)
    except pytesseract.TesseractNotFoundError as e:
        raise RuntimeError(f"Tesseract не запустився: {e}")
    except pytesseract.TesseractError as e:
        raise RuntimeError(
            f"Помилка Tesseract (можливо, не встановлено мовну модель "
            f"{lang}.traineddata): {e}"
        )


def _pass_score(data):
    """Оцінка якості проходу: середня впевненість, зважена кількістю
    розпізнаних символів. Прохід у "чужому" скрипті для реального тексту
    сторінки зазвичай або знаходить набагато менше валідних слів, або
    впевненість помітно нижча (мовна модель не впізнає такі "слова")."""
    weighted, total_chars = 0.0, 0
    n = len(data.get("text", []))
    for i in range(n):
        text = (data["text"][i] or "").strip()
        if not text:
            continue
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        if conf < 0:
            continue
        weighted += conf * len(text)
        total_chars += len(text)
    if total_chars == 0:
        return -1.0
    return weighted / total_chars


def _extract_words(data, min_confidence):
    """Дістає з сирого виводу Tesseract список слів з координатами,
    відкидаючи порожні/невпевнені записи. НЕ використовує block_num/
    par_num/line_num з Tesseract - подальше групування в рядки робимо
    самі (див. _group_words_into_lines), бо Tesseract у режимі
    автосегментації (--psm 3) на сторінках зі складним макетом (фото +
    дві колонки тексту) регулярно об'єднує в один "рядок" слова з різних
    візуальних колонок, що опинились на одній висоті."""
    words = []
    n = len(data.get("text", []))
    for i in range(n):
        text = (data["text"][i] or "").strip()
        if not text:
            continue
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        if conf < min_confidence:
            continue
        words.append({
            "text": text,
            "x": data["left"][i], "y": data["top"][i],
            "w": data["width"][i], "h": data["height"][i],
        })
    return words


def _group_words_into_lines(words):
    """Групує окремі слова (з координатами) у візуальні рядки самостійно,
    не покладаючись на угруповання Tesseract.

    1. Слова об'єднуються в рядок, якщо їхні вертикальні центри близькі
       (в межах ~60% середньої висоти рядка) - це звичайне групування по
       висоті.
    2. Всередині кожного такого "рядка" слова далі розбиваються на
       під-рядки там, де горизонтальний розрив між сусідніми словами
       НАБАГАТО більший за типовий міжслівний проміжок у цьому ж рядку -
       це і є межа між колонками, що випадково опинились на одній висоті.
       Поріг адаптивний (рахується окремо для кожного рядка), тому працює
       і для дрібного, і для великого шрифту."""
    if not words:
        return []

    rows = []  # [{"words": [...], "y_sum": float, "count": int, "h_avg": float}]
    for wd in sorted(words, key=lambda w: (w["y"], w["x"])):
        y_center = wd["y"] + wd["h"] / 2
        placed = False
        for row in rows:
            row_y_center = row["y_sum"] / row["count"]
            if abs(y_center - row_y_center) < row["h_avg"] * 0.6:
                row["words"].append(wd)
                row["y_sum"] += y_center
                row["count"] += 1
                row["h_avg"] = sum(w["h"]
                                    for w in row["words"]) / row["count"]
                placed = True
                break
        if not placed:
            rows.append(
                {"words": [wd], "y_sum": y_center, "count": 1, "h_avg": wd["h"]})

    groups = []
    for row in rows:
        row_words = sorted(row["words"], key=lambda w: w["x"])
        gaps = [
            row_words[i]["x"] - (row_words[i - 1]["x"] + row_words[i - 1]["w"])
            for i in range(1, len(row_words))
        ]
        median_gap = sorted(gaps)[len(gaps) // 2] if gaps else 0
        avg_h = sum(w["h"] for w in row_words) / len(row_words)
        # Поріг розриву-між-колонками: явно більший і за типовий пробіл
        # у цьому рядку, і за приблизну ширину "нормального" пробілу
        # відносно висоти шрифту.
        split_threshold = max(median_gap * 4, avg_h * 2.5, 20)

        current = [row_words[0]]
        for i in range(1, len(row_words)):
            prev = row_words[i - 1]
            gap = row_words[i]["x"] - (prev["x"] + prev["w"])
            if gap > split_threshold:
                groups.append(current)
                current = [row_words[i]]
            else:
                current.append(row_words[i])
        groups.append(current)
    return groups


def ocr_lines_from_image(pil_img, min_confidence=0):
    """Запускає Tesseract на зображенні сторінки та повертає список рядків:
    {"text": str, "bbox": (x0,y0,x1,y1)} у пікселях оригінального pil_img."""
    if not TESSERACT_CMD:
        raise RuntimeError(
            "Не знайдено виконуваний файл Tesseract OCR. Встановіть його:\n"
            "  Linux: sudo apt install tesseract-ocr tesseract-ocr-ukr tesseract-ocr-rus\n"
            "  Windows: https://github.com/UB-Mannheim/tesseract/wiki"
        )
    proc_img = preprocess_for_ocr(pil_img)
    scale_back_x = pil_img.width / proc_img.width
    scale_back_y = pil_img.height / proc_img.height

    # --oem 1: лише LSTM-рушій (сучасніший і точніший за legacy/комбо).
    # --psm 3: автоматична сегментація сторінки для координат слів (сама
    # логіка об'єднання слів у рядки - наша власна, нижче).
    config = "--oem 1 --psm 3"

    data_latin = _run_tesseract_pass(proc_img, _LATIN_LANGS, config)
    data_cyr = _run_tesseract_pass(proc_img, _CYRILLIC_LANGS, config)
    data = data_latin if _pass_score(
        data_latin) >= _pass_score(data_cyr) else data_cyr

    words = _extract_words(data, min_confidence)
    groups = _group_words_into_lines(words)

    lines = []
    for group in groups:
        text = " ".join(w["text"] for w in group).strip()
        if not text:
            continue
        x0 = min(w["x"] for w in group)
        y0 = min(w["y"] for w in group)
        x1 = max(w["x"] + w["w"] for w in group)
        y1 = max(w["y"] + w["h"] for w in group)
        lines.append({
            "text": text,
            "bbox": (
                x0 * scale_back_x, y0 * scale_back_y,
                x1 * scale_back_x, y1 * scale_back_y,
            ),
        })
    return lines


def fit_fontsize(text, rect_width, rect_height, fontfile, max_size=None):
    """Підбирає розмір шрифту так, щоб текст влазив у прямокутник по ширині."""
    if max_size is None:
        max_size = max(4, rect_height * 0.85)
    size = max_size
    try:
        font = fitz.Font(fontfile=fontfile)
    except Exception:
        font = fitz.Font("helv")
    while size > 4:
        width = font.text_length(text, fontsize=size)
        if width <= rect_width or size <= 4.5:
            break
        size -= 0.5
    return size


def sample_bg_color(pil_img, bbox, pad=3):
    """Пробує визначити колір фону біля текстового блоку (для замальовування)."""
    x0, y0, x1, y1 = bbox
    w, h = pil_img.size
    sx = max(0, int(x0) - pad)
    sy = max(0, int(y0) - pad)
    ex = min(w, int(x0) + 4)
    ey = min(h, int(y0))
    if ex <= sx or ey <= sy:
        return (1, 1, 1)
    crop = pil_img.crop((sx, sy, ex, ey)).convert("RGB")
    pixels = list(crop.getdata())
    if not pixels:
        return (1, 1, 1)
    r = sum(p[0] for p in pixels) / len(pixels)
    g = sum(p[1] for p in pixels) / len(pixels)
    b = sum(p[2] for p in pixels) / len(pixels)
    return (r / 255, g / 255, b / 255)


# =========================================================================
#  Основна логіка обробки одного PDF
# =========================================================================

class ProcessingCancelled(Exception):
    pass


_ERROR_PAGE_MARKERS = (
    "that's an error",
    "that\u2019s an error",
    "that's all we know",
    "that\u2019s all we know",
    "please try again later",
    "<html",
    "error 500",
    "error 429",
    "500.that",
)


def _looks_like_error_page(text):
    """Google (неофіційний, безкоштовний translate.google.com) при
    перевантаженні/бані по IP повертає не JSON з перекладом, а звичайну
    HTML-сторінку помилки ("Error 500 ... That's an error ..."). deep-
    translator іноді віддає це як звичайний рядок замість винятку - без
    цієї перевірки таке сміття летіло прямо в PDF замість перекладу."""
    if not text:
        return False
    low = text.lower()
    return any(marker in low for marker in _ERROR_PAGE_MARKERS)


def safe_translate(translator, text, log_fn=None, max_retries=4, base_delay=1.2):
    """Перекладає один рядок з ретраями й експоненційною затримкою.
    Якщо після всіх спроб переклад так і не вдався - повертає ОРИГІНАЛЬНИЙ
    текст (краще лишити рядок оригіналом, ніж вставити в PDF сторінку
    помилки Google)."""
    if not text or not text.strip():
        return text
    last_err = None
    for attempt in range(max_retries):
        try:
            result = translator.translate(text)
        except Exception as e:
            last_err = e
            result = None
        if result and not _looks_like_error_page(result):
            return result
        if result and _looks_like_error_page(result):
            last_err = RuntimeError(
                "Google повернув сторінку помилки (перевантажений/тимчасовий бан) "
                "замість перекладу")
        # Експоненційна затримка перед повторною спробою + невеликий джиттер,
        # щоб не бити рівно по секунді знову в той самий ліміт.
        time.sleep(base_delay * (2 ** attempt) + random.uniform(0, 0.5))
    if log_fn:
        log_fn(
            f"  [!] Не вдалося перекласти рядок після {max_retries} спроб "
            f"({last_err}); залишаю оригінальний текст."
        )
    return text


def process_pdf(
    input_path,
    output_dir,
    dpi,
    make_searchable,
    translate_targets,   # список кодів мов deep-translator, напр. ["uk", "ru", "en"]
    font_path,
    log_fn,
    cancel_event,
):
    """Обробляє один PDF-файл: OCR + (опційно) створення searchable PDF
    та перекладених PDF. log_fn(str) - для виводу повідомлень у GUI."""

    base_name = os.path.splitext(os.path.basename(input_path))[0]
    doc = fitz.open(input_path)
    n_pages = doc.page_count

    fontfile = find_unicode_font(font_path)
    if fontfile is None:
        raise RuntimeError(
            "Не знайдено TTF-шрифт з підтримкою кирилиці. "
            "Вкажіть шлях до шрифту (напр. arial.ttf) у полі GUI."
        )

    out_searchable = fitz.open() if make_searchable else None
    out_translated = {lang: fitz.open() for lang in translate_targets}

    translators = {
        lang: GoogleTranslator(source="auto", target=lang) for lang in translate_targets
    }
    # Кеш на весь файл: однакові рядки (заголовки, футери, номери сторінок,
    # повторювані фрази) перекладаються лише один раз - це і швидше, і
    # менше запитів до Google (менше шансів наштовхнутись на ліміт).
    translation_cache = {}  # {(lang, text): translated_text}

    for page_index in range(n_pages):
        if cancel_event.is_set():
            raise ProcessingCancelled()

        log_fn(f"[{base_name}] Сторінка {page_index + 1}/{n_pages}: рендеринг...")
        page = doc[page_index]
        pix = page.get_pixmap(dpi=dpi)
        img_bytes = pix.tobytes("png")
        pil_img = Image.open(io.BytesIO(img_bytes))

        page_w, page_h = page.rect.width, page.rect.height
        scale_x = page_w / pix.width
        scale_y = page_h / pix.height

        lines = []
        if make_searchable or translate_targets:
            # Спершу пробуємо взяти вже наявний текстовий шар PDF (швидко,
            # без OCR). Якщо його немає - розпізнаємо зображення сторінки.
            lines = extract_lines_from_page(page)
            if lines:
                log_fn(
                    f"[{base_name}] Сторінка {page_index + 1}/{n_pages}: "
                    f"текст з PDF ({len(lines)} рядків), OCR пропущено")
            else:
                log_fn(
                    f"[{base_name}] Сторінка {page_index + 1}/{n_pages}: "
                    f"немає текстового шару — розпізнавання (OCR)...")
                lines = ocr_lines_from_image(pil_img)

        # ---------- 1) Розпізнаваний PDF (той самий вигляд + невидимий текст) ----------
        if out_searchable is not None:
            sp = out_searchable.new_page(width=page_w, height=page_h)
            sp.insert_image(sp.rect, stream=img_bytes)
            for line in lines:
                rect = line_to_rect(line, scale_x, scale_y)
                if rect.is_empty or rect.width <= 0 or rect.height <= 0:
                    continue
                fs = fit_fontsize(
                    line["text"], rect.width, rect.height, fontfile)
                baseline = fitz.Point(rect.x0, rect.y1 - 0.15 * fs)
                try:
                    sp.insert_text(
                        baseline,
                        line["text"],
                        fontsize=fs,
                        fontfile=fontfile,
                        fontname="cyr1",
                        render_mode=3,  # невидимий текст
                    )
                except Exception as e:
                    log_fn(f"  [!] Пропущено рядок (текстовий шар): {e}")

        # ---------- 2) Перекладені PDF ----------
        if translate_targets:
            translations = {}
            if lines:
                log_fn(
                    f"[{base_name}] Сторінка {page_index + 1}/{n_pages}: переклад...")
                texts_to_translate = [ln["text"] for ln in lines]
                for lang in translate_targets:
                    result = []
                    for t in texts_to_translate:
                        cache_key = (lang, t)
                        if cache_key in translation_cache:
                            result.append(translation_cache[cache_key])
                            continue
                        tr = safe_translate(translators[lang], t, log_fn)
                        translation_cache[cache_key] = tr
                        result.append(tr)
                        # Невелика пауза між запитами - неофіційний Google
                        # Translate банить/повертає Error 500 саме при
                        # частих запитах поспіль без жодних пауз.
                        time.sleep(0.2)
                    translations[lang] = result

            for lang in translate_targets:
                tp = out_translated[lang].new_page(width=page_w, height=page_h)
                tp.insert_image(tp.rect, stream=img_bytes)
                if not lines:
                    continue
                translated_lines = translations[lang]
                for line, tr_text in zip(lines, translated_lines):
                    rect = line_to_rect(line, scale_x, scale_y)
                    if rect.is_empty or rect.width <= 0 or rect.height <= 0:
                        continue
                    px_bbox = line_to_pixel_bbox(line, scale_x, scale_y)
                    bg = sample_bg_color(pil_img, px_bbox)
                    cover = fitz.Rect(rect.x0 - 1, rect.y0 - 1,
                                      rect.x1 + 1, rect.y1 + 1)
                    tp.draw_rect(cover, color=bg, fill=bg, overlay=True)
                    if not tr_text:
                        continue
                    fs = fit_fontsize(tr_text, rect.width,
                                      rect.height, fontfile)
                    baseline = fitz.Point(rect.x0, rect.y1 - 0.15 * fs)
                    try:
                        tp.insert_text(
                            baseline,
                            tr_text,
                            fontsize=fs,
                            fontfile=fontfile,
                            fontname="cyr1",
                            color=(0, 0, 0),
                        )
                    except Exception as e:
                        log_fn(f"  [!] Пропущено рядок (переклад {lang}): {e}")

        # Явно звільняємо памʼять цієї сторінки перед переходом до наступної.
        # На довгих документах / слабких машинах це помітно знижує пік
        # споживання RAM: без цього великі растрові зображення сторінок і
        # внутрішній кеш MuPDF накопичуються протягом усього файлу.
        del pix, pil_img, img_bytes, lines
        page = None
        fitz.TOOLS.store_shrink(100)
        gc.collect()

    os.makedirs(output_dir, exist_ok=True)
    saved_files = []

    if out_searchable is not None:
        out_path = os.path.join(output_dir, f"{base_name}_searchable.pdf")
        out_searchable.save(out_path, garbage=3, deflate=True)
        out_searchable.close()
        saved_files.append(out_path)

    for lang in translate_targets:
        out_path = os.path.join(output_dir, f"{base_name}_{lang}.pdf")
        out_translated[lang].save(out_path, garbage=3, deflate=True)
        out_translated[lang].close()
        saved_files.append(out_path)

    doc.close()
    gc.collect()
    return saved_files


# =========================================================================
#  GUI
# =========================================================================


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PDF-manager: OCR + переклад")
        # Мінімальний розумний розмір "про запас" - реальний розмір нижче
        # підганяється під фактичний вміст, тож це лише стартова заглушка.
        self.geometry("780x680")

        self.files = []
        self.log_queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker_thread = None

        # Діалоги вибору файлів за замовчуванням відкриваються в корені
        # диска (Linux: "/", Windows: "C:\\"), а далі запам'ятовують
        # останню відкриту користувачем директорію.
        self.last_dir = os.path.expanduser("~")

        self.gui_font = setup_gui_fonts(self)
        self._build_ui()
        self._fit_window_to_content()
        self.after(150, self._poll_log_queue)

    def _fit_window_to_content(self):
        """Підганяє розмір вікна під фактично потрібний розмір усіх
        віджетів, а не під захардкоджені пікселі. Так вікно завжди
        вміщує всі елементи, навіть якщо їх склад зміниться в майбутньому
        (додасться/зникне якийсь рядок налаштувань тощо)."""
        self.update_idletasks()
        req_w = self.winfo_reqwidth() + 20
        req_h = self.winfo_reqheight() + 20
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        # Не даємо вікну вилізти за межі екрана (напр. на маленьких ноутах) -
        # у такому разі просто дамо йому проскролитись/стиснутись природно.
        w = min(req_w, screen_w - 60)
        h = min(req_h, screen_h - 80)
        self.geometry(f"{w}x{h}")
        self.minsize(min(w, 700), min(h, 560))

    # ---------------- UI ----------------
    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        frm_files = ttk.LabelFrame(self, text="1. Вхідні PDF-файли")
        frm_files.pack(fill="x", **pad)

        entry_font = self.gui_font if self.gui_font else None
        listbox_kwargs = {"height": 6, "selectmode": "extended"}
        if entry_font:
            listbox_kwargs["font"] = entry_font
        self.listbox = tk.Listbox(frm_files, **listbox_kwargs)
        self.listbox.pack(fill="x", padx=6, pady=6, side="left", expand=True)
        scrollbar = ttk.Scrollbar(
            frm_files, orient="vertical", command=self.listbox.yview)
        scrollbar.pack(side="left", fill="y")
        self.listbox.config(yscrollcommand=scrollbar.set)

        btns = ttk.Frame(frm_files)
        btns.pack(side="left", padx=6)
        ttk.Button(btns, text="Додати файли...",
                   command=self.add_files).pack(fill="x", pady=2)
        ttk.Button(btns, text="Додати папку...",
                   command=self.add_folder).pack(fill="x", pady=2)
        ttk.Button(btns, text="Видалити вибране",
                   command=self.remove_selected).pack(fill="x", pady=2)
        ttk.Button(btns, text="Очистити список",
                   command=self.clear_files).pack(fill="x", pady=2)

        frm_opts = ttk.LabelFrame(self, text="2. Розпізнавання (OCR)")
        frm_opts.pack(fill="x", **pad)

        ttk.Label(
            frm_opts,
            text="Розпізнавання тексту (Tesseract) працює одразу для "
                 "української, російської та англійської — вибір мов не потрібен.",
        ).grid(row=0, column=0, columnspan=4, sticky="w", **pad)

        ttk.Label(frm_opts, text="DPI рендерингу (більше = точніше OCR, менше = швидше):").grid(
            row=1, column=0, sticky="w", **pad)
        self.dpi_var = tk.IntVar(value=300)
        ttk.Spinbox(frm_opts, from_=150, to=600, increment=50, textvariable=self.dpi_var, width=6).grid(
            row=1, column=1, sticky="w", **pad
        )

        ttk.Label(
            frm_opts,
            text="Шрифт з кирилицею (необов'язково, за замовчуванням — вбудований DejaVu Sans):",
        ).grid(row=2, column=0, columnspan=4, sticky="w", **pad)
        self.font_var = tk.StringVar(value="")
        font_entry_kwargs = {"textvariable": self.font_var}
        if entry_font:
            font_entry_kwargs["font"] = entry_font
        font_entry = tk.Entry(frm_opts, **font_entry_kwargs)
        font_entry.grid(row=3, column=0, columnspan=3, sticky="ew", **pad)
        ttk.Button(frm_opts, text="Огляд...", command=self.choose_font).grid(
            row=3, column=3, sticky="w", **pad)
        frm_opts.columnconfigure(0, weight=1)

        frm_tasks = ttk.LabelFrame(self, text="3. Що створити")
        frm_tasks.pack(fill="x", **pad)

        self.var_searchable = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            frm_tasks,
            text="Розпізнаваний PDF (той самий вигляд, текст можна виділяти)",
            variable=self.var_searchable,
        ).grid(row=0, column=0, sticky="w", **pad)

        self.var_uk = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            frm_tasks, text="Переклад українською (текст вставляється на місце оригіналу)", variable=self.var_uk
        ).grid(row=1, column=0, sticky="w", **pad)

        self.var_ru = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            frm_tasks, text="Переклад російською (текст вставляється на місце оригіналу)", variable=self.var_ru
        ).grid(row=2, column=0, sticky="w", **pad)

        self.var_en = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            frm_tasks, text="Переклад англійською (текст вставляється на місце оригіналу)", variable=self.var_en
        ).grid(row=3, column=0, sticky="w", **pad)

        frm_out = ttk.LabelFrame(self, text="4. Папка для результатів")
        frm_out.pack(fill="x", **pad)
        self.out_dir_var = tk.StringVar(
            value=os.path.join(os.path.expanduser("~"), "pdf_ocr_output")
        )
        out_entry_kwargs = {"textvariable": self.out_dir_var, "width": 60}
        if entry_font:
            out_entry_kwargs["font"] = entry_font
        tk.Entry(frm_out, **out_entry_kwargs).pack(
            side="left", padx=6, pady=6, fill="x", expand=True
        )
        ttk.Button(frm_out, text="Огляд...", command=self.choose_out_dir).pack(
            side="left", padx=6)

        frm_run = ttk.Frame(self)
        frm_run.pack(fill="x", **pad)
        self.start_btn = ttk.Button(
            frm_run, text="Почати обробку", command=self.start_processing)
        self.start_btn.pack(side="left", padx=6)
        self.cancel_btn = ttk.Button(
            frm_run, text="Скасувати", command=self.cancel_processing, state="disabled")
        self.cancel_btn.pack(side="left", padx=6)

        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(fill="x", **pad)

        frm_log = ttk.LabelFrame(self, text="Журнал")
        frm_log.pack(fill="both", expand=True, **pad)
        log_kwargs = {"height": 12, "state": "disabled", "wrap": "word"}
        if entry_font:
            log_kwargs["font"] = entry_font
        self.log_text = tk.Text(frm_log, **log_kwargs)
        self.log_text.pack(fill="both", expand=True, padx=6, pady=6)

    # ---------------- Дії ----------------
    def add_files(self):
        paths = filedialog.askopenfilenames(
            title="Виберіть PDF-файли", filetypes=[("PDF files", "*.pdf")],
            initialdir=self.last_dir,
        )
        if paths:
            self.last_dir = os.path.dirname(paths[0])
        for p in paths:
            if p not in self.files:
                self.files.append(p)
                self.listbox.insert("end", p)

    def add_folder(self):
        folder = filedialog.askdirectory(
            title="Виберіть папку з PDF-файлами", initialdir=self.last_dir)
        if folder:
            self.last_dir = folder
            for p in sorted(glob.glob(os.path.join(folder, "*.pdf"))):
                if p not in self.files:
                    self.files.append(p)
                    self.listbox.insert("end", p)

    def remove_selected(self):
        selected = list(self.listbox.curselection())
        for index in reversed(selected):
            self.listbox.delete(index)
            del self.files[index]

    def clear_files(self):
        self.files.clear()
        self.listbox.delete(0, "end")

    def choose_font(self):
        path = filedialog.askopenfilename(
            title="Виберіть TTF-шрифт з кирилицею", filetypes=[("TrueType Font", "*.ttf")],
            initialdir=self.last_dir,
        )
        if path:
            self.font_var.set(path)
            self.last_dir = os.path.dirname(path)

    def choose_out_dir(self):
        folder = filedialog.askdirectory(
            title="Папка для результатів", initialdir=self.last_dir)
        if folder:
            self.out_dir_var.set(folder)
            self.last_dir = folder

    def log(self, msg):
        self.log_queue.put(msg)

    def _poll_log_queue(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log_text.config(state="normal")
                self.log_text.insert("end", msg + "\n")
                self.log_text.see("end")
                self.log_text.config(state="disabled")
        except queue.Empty:
            pass
        self.after(150, self._poll_log_queue)

    def start_processing(self):
        if not self.files:
            messagebox.showwarning(
                "Немає файлів", "Спочатку додайте хоча б один PDF-файл.")
            return
        if not (self.var_searchable.get() or self.var_uk.get() or self.var_ru.get() or self.var_en.get()):
            messagebox.showwarning(
                "Нічого робити", "Виберіть хоча б одну дію у розділі 3.")
            return

        if not TESSERACT_CMD:
            messagebox.showerror(
                "Tesseract не знайдено",
                "Не вдалося знайти виконуваний файл Tesseract OCR.\n\n"
                "Linux: sudo apt install tesseract-ocr tesseract-ocr-ukr tesseract-ocr-rus\n"
                "Windows: https://github.com/UB-Mannheim/tesseract/wiki\n\n"
                "OCR запуститься лише для сторінок без текстового шару — "
                "якщо всі ваші PDF уже мають текст, можна продовжити і без нього.",
            )
            return

        make_searchable = self.var_searchable.get()
        translate_targets = []
        if self.var_uk.get():
            translate_targets.append("uk")
        if self.var_ru.get():
            translate_targets.append("ru")
        if self.var_en.get():
            translate_targets.append("en")

        dpi = self.dpi_var.get()
        font_path = self.font_var.get().strip() or None
        out_dir = self.out_dir_var.get().strip()

        self.cancel_event.clear()
        self.start_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self.progress.config(maximum=len(self.files), value=0)

        self.worker_thread = threading.Thread(
            target=self._run_worker,
            args=(
                list(self.files), out_dir, dpi,
                self.var_searchable.get(), translate_targets, font_path,
            ),
            daemon=True,
        )
        self.worker_thread.start()

    def cancel_processing(self):
        self.cancel_event.set()
        self.log(">>> Скасування... зачекайте завершення поточної сторінки.")

    def _run_worker(self, files, out_dir, dpi, make_searchable, translate_targets, font_path):
        done = 0
        for path in files:
            if self.cancel_event.is_set():
                self.log(">>> Обробку скасовано користувачем.")
                break
            try:
                self.log(f"=== Обробка: {os.path.basename(path)} ===")
                saved = process_pdf(
                    input_path=path,
                    output_dir=out_dir,
                    dpi=dpi,
                    make_searchable=make_searchable,
                    translate_targets=translate_targets,
                    font_path=font_path,
                    log_fn=self.log,
                    cancel_event=self.cancel_event,
                )
                for s in saved:
                    self.log(f"  -> Збережено: {s}")
            except ProcessingCancelled:
                self.log(">>> Обробку скасовано користувачем.")
                break
            except Exception:
                self.log(f"[ПОМИЛКА] {path}:\n{traceback.format_exc()}")
            done += 1
            self.progress.after(
                0, lambda d=done: self.progress.config(value=d))

        self.log("=== Готово ===")
        self.start_btn.after(0, lambda: self.start_btn.config(state="normal"))
        self.cancel_btn.after(
            0, lambda: self.cancel_btn.config(state="disabled"))


def _init_locale_for_linux_input():
    """Явно вмикає UTF-8 локаль перед створенням вікна Tk.

    На Linux ввід кирилиці в tk.Entry/tk.Text йде через систему X11 Input
    Method (XIM) або через IBus/Fcitx поверх неї. Якщо процес Python
    стартує з локаллю "C"/"POSIX" (типово, коли програму запускають не
    з термінала, а, наприклад, через ярлик або .desktop-файл без
    успадкованого середовища), Tk піднімає X-з'єднання ще до того, як
    дізнається про UTF-8, і XIM просто не активується — тоді кирилицю
    (і будь-яку не-ASCII розкладку) неможливо ввести в поля вводу, хоча
    показати її на екрані (шрифтом) можна без проблем. Це НЕ баг у
    самому коді програми, а особливість оточення, тому один виклик
    setlocale тут допомагає лише частково: якщо не спрацює, потрібно
    перевірити системну локаль і змінні GTK_IM_MODULE/XMODIFIERS
    (див. коментар у README / повідомлення від Claude)."""
    try:
        import locale
        locale.setlocale(locale.LC_ALL, "")
    except Exception:
        pass


if __name__ == "__main__":
    _init_locale_for_linux_input()
    app = App()
    app.mainloop()