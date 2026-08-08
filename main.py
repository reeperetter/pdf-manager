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

from PyQt5 import QtCore, QtGui, QtWidgets

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

    # [{"words": [...], "y_sum": float, "count": int, "h_avg": float}]
    rows = []
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


def sample_bg_color(pil_img, bbox, pad=4):
    """Визначає колір фону навколо текстового блоку (для замальовування
    оригінального тексту перед вставкою перекладу).

    Семплює вузькі смужки одразу НАД, ПІД, ЛІВОРУЧ і ПРАВОРУЧ від bbox
    (а не крихітну ділянку в одній точці) і бере МЕДІАНУ по кожному
    каналу кольору. Медіана, а не середнє, - щоб один випадково
    захоплений темний піксель (краєчок сусіднього рядка, тінь) не тягнув
    колір у неправильний бік: на однотонному фоні медіана й середнє
    збігаються, а на "забрудненому" - медіана явно точніша."""
    x0, y0, x1, y1 = bbox
    w, h = pil_img.size
    x0i, y0i, x1i, y1i = int(x0), int(y0), int(x1), int(y1)

    strips = [
        (x0i, max(0, y0i - pad), x1i, y0i),           # над текстом
        (x0i, y1i, x1i, min(h, y1i + pad)),            # під текстом
        (max(0, x0i - pad), y0i, x0i, y1i),            # ліворуч
        (x1i, y0i, min(w, x1i + pad), y1i),            # праворуч
    ]

    samples_r, samples_g, samples_b = [], [], []
    for sx, sy, ex, ey in strips:
        if ex <= sx or ey <= sy:
            continue
        crop = pil_img.crop((sx, sy, ex, ey)).convert("RGB")
        for p in crop.getdata():
            samples_r.append(p[0])
            samples_g.append(p[1])
            samples_b.append(p[2])

    if not samples_r:
        return (1, 1, 1)

    def median(vals):
        vals = sorted(vals)
        n = len(vals)
        mid = n // 2
        if n % 2:
            return vals[mid]
        return (vals[mid - 1] + vals[mid]) / 2

    return (median(samples_r) / 255, median(samples_g) / 255, median(samples_b) / 255)


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
    # список кодів мов deep-translator, напр. ["uk", "ru", "en"]
    translate_targets,
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
                    orig_text = line["text"].strip()
                    tr_text_stripped = (tr_text or "").strip()
                    if tr_text_stripped.lower() == orig_text.lower():
                        # Переклад ідентичний оригіналу (номери, коди,
                        # власні назви тощо) - нема сенсу замальовувати
                        # й переписувати те саме, це тільки псує вигляд.
                        continue
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


class WorkerSignals(QtCore.QObject):
    """Сигнали для безпечного оновлення GUI з фонового потоку обробки.
    У Qt (на відміну від Tk) не можна напряму чіпати віджети з іншого
    потоку - сигнали/слоти автоматично переносять виклик у головний
    потік, тому саме через них тут і йде весь зв'язок з робочим потоком."""
    log = QtCore.pyqtSignal(str)
    progress = QtCore.pyqtSignal(int)
    status = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal()


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDF-manager: OCR + переклад")

        self.files = []
        self.cancel_event = threading.Event()
        self.worker_thread = None
        # Діалоги вибору файлів за замовчуванням відкриваються в домашній
        # директорії, а далі запам'ятовують останню відкриту користувачем.
        self.last_dir = os.path.expanduser("~")

        self.signals = WorkerSignals()
        self.signals.log.connect(self._append_log)
        self.signals.progress.connect(self._set_progress)
        self.signals.status.connect(self._set_status)
        self.signals.finished.connect(self._on_finished)

        self._build_ui()
        self.resize(self.sizeHint())

    # ---------------- UI ----------------
    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        root_layout = QtWidgets.QVBoxLayout(central)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(8)

        bold = QtGui.QFont()
        bold.setBold(True)

        # ---- Двоколонковий контейнер: зліва файли+вивід, справа налаштування ----
        columns = QtWidgets.QHBoxLayout()
        columns.setSpacing(10)
        root_layout.addLayout(columns)

        left_col = QtWidgets.QVBoxLayout()
        left_col.setSpacing(8)
        columns.addLayout(left_col, 3)

        right_col = QtWidgets.QVBoxLayout()
        right_col.setSpacing(8)
        columns.addLayout(right_col, 2)

        # ---- Ліва колонка: файли ----
        grp_files = QtWidgets.QGroupBox("Вхідні PDF-файли")
        grp_files.setFont(bold)
        left_col.addWidget(grp_files)
        files_layout = QtWidgets.QHBoxLayout(grp_files)

        self.listbox = QtWidgets.QListWidget()
        self.listbox.setSelectionMode(
            QtWidgets.QAbstractItemView.ExtendedSelection)
        self.listbox.setMinimumHeight(140)
        files_layout.addWidget(self.listbox, 1)

        btns = QtWidgets.QVBoxLayout()
        files_layout.addLayout(btns)
        btn_add_files = QtWidgets.QPushButton("Додати файли...")
        btn_add_files.clicked.connect(self.add_files)
        btn_add_folder = QtWidgets.QPushButton("Додати папку...")
        btn_add_folder.clicked.connect(self.add_folder)
        btn_remove = QtWidgets.QPushButton("Видалити вибране")
        btn_remove.clicked.connect(self.remove_selected)
        btn_clear = QtWidgets.QPushButton("Очистити список")
        btn_clear.clicked.connect(self.clear_files)
        for b in (btn_add_files, btn_add_folder, btn_remove, btn_clear):
            btns.addWidget(b)
        btns.addStretch(1)

        # ---- Куди зберегти - під списком файлів, та сама колонка ----
        grp_out = QtWidgets.QGroupBox("Куди зберегти результат")
        grp_out.setFont(bold)
        left_col.addWidget(grp_out)
        out_layout = QtWidgets.QHBoxLayout(grp_out)
        self.out_dir_edit = QtWidgets.QLineEdit(
            os.path.join(os.path.expanduser("~"), "pdf_ocr_output")
        )
        out_layout.addWidget(self.out_dir_edit, 1)
        btn_out = QtWidgets.QPushButton("Огляд...")
        btn_out.clicked.connect(self.choose_out_dir)
        out_layout.addWidget(btn_out)

        left_col.addStretch(1)

        # ---- Права колонка: налаштування OCR ----
        grp_opts = QtWidgets.QGroupBox("Розпізнавання (OCR)")
        grp_opts.setFont(bold)
        right_col.addWidget(grp_opts)
        opts_layout = QtWidgets.QGridLayout(grp_opts)

        hint = QtWidgets.QLabel(
            "Розпізнає укр./рос./англ. одночасно - вибір мов не потрібен.")
        hint.setStyleSheet("color: #666666;")
        hint.setWordWrap(True)
        opts_layout.addWidget(hint, 0, 0, 1, 3)

        opts_layout.addWidget(QtWidgets.QLabel("DPI:"), 1, 0)
        self.dpi_spin = QtWidgets.QSpinBox()
        self.dpi_spin.setRange(150, 600)
        self.dpi_spin.setSingleStep(50)
        self.dpi_spin.setValue(300)
        opts_layout.addWidget(self.dpi_spin, 1, 1)
        dpi_hint = QtWidgets.QLabel("більше = точніше, менше = швидше")
        dpi_hint.setStyleSheet("color: #666666;")
        opts_layout.addWidget(dpi_hint, 1, 2)

        opts_layout.addWidget(QtWidgets.QLabel("Шрифт:"), 2, 0)
        self.font_edit = QtWidgets.QLineEdit()
        opts_layout.addWidget(self.font_edit, 2, 1)
        btn_font = QtWidgets.QPushButton("Огляд...")
        btn_font.setSizePolicy(
            QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        btn_font.clicked.connect(self.choose_font)
        opts_layout.addWidget(btn_font, 2, 2)
        font_hint = QtWidgets.QLabel(
            "необов'язково - типово вбудований DejaVu Sans")
        font_hint.setStyleSheet("color: #666666;")
        opts_layout.addWidget(font_hint, 3, 0, 1, 3)
        opts_layout.setColumnStretch(1, 1)

        # ---- Що створити ----
        grp_tasks = QtWidgets.QGroupBox("Що створити")
        grp_tasks.setFont(bold)
        right_col.addWidget(grp_tasks)
        tasks_layout = QtWidgets.QVBoxLayout(grp_tasks)

        self.chk_searchable = QtWidgets.QCheckBox(
            "Розпізнаваний PDF (виділюваний текст)")
        self.chk_searchable.setChecked(False)
        self.chk_uk = QtWidgets.QCheckBox("Переклад українською")
        self.chk_uk.setChecked(False)
        self.chk_ru = QtWidgets.QCheckBox("Переклад російською")
        self.chk_ru.setChecked(False)
        self.chk_en = QtWidgets.QCheckBox("Переклад англійською")
        self.chk_en.setChecked(False)
        for c in (self.chk_searchable, self.chk_uk, self.chk_ru, self.chk_en):
            tasks_layout.addWidget(c)

        right_col.addStretch(1)

        # ---- Запуск + прогрес (на всю ширину, під двома колонками) ----
        run_layout = QtWidgets.QHBoxLayout()
        root_layout.addLayout(run_layout)
        self.start_btn = QtWidgets.QPushButton("Почати обробку")
        self.start_btn.clicked.connect(self.start_processing)
        run_layout.addWidget(self.start_btn)
        self.cancel_btn = QtWidgets.QPushButton("Скасувати")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_processing)
        run_layout.addWidget(self.cancel_btn)
        self.status_label = QtWidgets.QLabel("Готово")
        run_layout.addWidget(self.status_label)
        run_layout.addStretch(1)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setTextVisible(False)
        root_layout.addWidget(self.progress)

        # ---- Журнал ----
        grp_log = QtWidgets.QGroupBox("Журнал")
        grp_log.setFont(bold)
        root_layout.addWidget(grp_log, 1)
        log_layout = QtWidgets.QVBoxLayout(grp_log)
        self.log_text = QtWidgets.QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(160)
        log_layout.addWidget(self.log_text)

    # ---------------- Дії ----------------
    def add_files(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Виберіть PDF-файли", self.last_dir, "PDF files (*.pdf)")
        if paths:
            self.last_dir = os.path.dirname(paths[0])
        for p in paths:
            if p not in self.files:
                self.files.append(p)
                self.listbox.addItem(p)

    def add_folder(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Виберіть папку з PDF-файлами", self.last_dir)
        if folder:
            self.last_dir = folder
            for p in sorted(glob.glob(os.path.join(folder, "*.pdf"))):
                if p not in self.files:
                    self.files.append(p)
                    self.listbox.addItem(p)

    def remove_selected(self):
        for item in self.listbox.selectedItems():
            index = self.listbox.row(item)
            self.listbox.takeItem(index)
            del self.files[index]

    def clear_files(self):
        self.files.clear()
        self.listbox.clear()

    def choose_font(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Виберіть TTF-шрифт з кирилицею", self.last_dir, "TrueType Font (*.ttf)")
        if path:
            self.font_edit.setText(path)
            self.last_dir = os.path.dirname(path)

    def choose_out_dir(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Папка для результатів", self.last_dir)
        if folder:
            self.out_dir_edit.setText(folder)
            self.last_dir = folder

    # ---------------- Лог/прогрес (виконуються в головному потоці - слоти) ----------------
    def _append_log(self, msg):
        self.log_text.appendPlainText(msg)

    def _set_progress(self, value):
        self.progress.setValue(value)

    def _set_status(self, text):
        self.status_label.setText(text)

    def _on_finished(self):
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)

    def log(self, msg):
        # Викликається з робочого потоку - сигнал безпечно переносить
        # оновлення тексту в головний потік Qt.
        self.signals.log.emit(msg)

    # ---------------- Обробка ----------------
    def start_processing(self):
        if not self.files:
            QtWidgets.QMessageBox.warning(
                self, "Немає файлів", "Спочатку додайте хоча б один PDF-файл.")
            return
        if not (self.chk_searchable.isChecked() or self.chk_uk.isChecked()
                or self.chk_ru.isChecked() or self.chk_en.isChecked()):
            QtWidgets.QMessageBox.warning(
                self, "Нічого робити", "Виберіть хоча б одну дію у розділі «Що створити».")
            return

        if not TESSERACT_CMD:
            QtWidgets.QMessageBox.critical(
                self, "Tesseract не знайдено",
                "Не вдалося знайти виконуваний файл Tesseract OCR.\n\n"
                "Windows: https://github.com/UB-Mannheim/tesseract/wiki\n\n"
                "Ubuntu: sudo apt install tesseract-ocr tesseract-ocr-ukr tesseract-ocr-rus\n"
                "Fedora: sudo dnf install tesseract tesseract-langpack-eng tesseract-langpack-ukr tesseract-langpack-rus\n"
                "OCR запуститься лише для сторінок без текстового шару — "
                "якщо всі ваші PDF уже мають текст, можна продовжити і без нього.",
            )
            return

        make_searchable = self.chk_searchable.isChecked()
        translate_targets = []
        if self.chk_uk.isChecked():
            translate_targets.append("uk")
        if self.chk_ru.isChecked():
            translate_targets.append("ru")
        if self.chk_en.isChecked():
            translate_targets.append("en")

        dpi = self.dpi_spin.value()
        font_path = self.font_edit.text().strip() or None
        out_dir = self.out_dir_edit.text().strip()

        self.cancel_event.clear()
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress.setRange(0, len(self.files))
        self.progress.setValue(0)
        self.status_label.setText(f"Обробка: 0/{len(self.files)}")

        self.worker_thread = threading.Thread(
            target=self._run_worker,
            args=(
                list(self.files), out_dir, dpi,
                make_searchable, translate_targets, font_path,
            ),
            daemon=True,
        )
        self.worker_thread.start()

    def cancel_processing(self):
        self.cancel_event.set()
        self.signals.status.emit("Скасування...")
        self.log(">>> Скасування... зачекайте завершення поточної сторінки.")

    def _run_worker(self, files, out_dir, dpi, make_searchable, translate_targets, font_path):
        done = 0
        total = len(files)
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
            self.signals.progress.emit(done)
            self.signals.status.emit(f"Обробка: {done}/{total}")

        self.signals.status.emit("Готово")
        self.log("=== Готово ===")
        self.signals.finished.emit()


if __name__ == "__main__":
    QtWidgets.QApplication.setAttribute(
        QtCore.Qt.AA_EnableHighDpiScaling, True)
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
