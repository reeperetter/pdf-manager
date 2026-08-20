"""
Розпізнавання тексту (Tesseract OCR) та виправлення викривлення сторінок.

Усе, що стосується "зображення сторінки -> список розпізнаних рядків з
координатами", живе тут. PDF-специфічні речі (вставка тексту в PDF,
переклад, збереження файлів) - у pdf_pipeline.py.
"""
import os
import shutil

import pytesseract
from PIL import Image, ImageOps

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


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


def detect_and_fix_orientation(pil_img, log_fn=None):
    """Визначає, чи сторінка повернута на 90/180/270° (типово при
    фотографуванні - телефон міг триматись "боком" чи взагалі догори
    ногами), і виправляє орієнтацію ще ДО основного розпізнавання.

    Використовує вбудований у Tesseract механізм OSD (Orientation and
    Script Detection) - окремий, швидкий прохід, що аналізує форму
    літер для визначення напрямку тексту, а не намагається його
    прочитати. Значно надійніший за спроби вгадати орієнтацію по формі
    сторінки чи вмісту фото.

    Повертає (виправлене_зображення, чи_був_поворот: bool)."""
    try:
        osd = pytesseract.image_to_osd(
            pil_img, output_type=pytesseract.Output.DICT)
    except Exception:
        # Замало тексту на сторінці, чи інша причина, через яку OSD не
        # спрацював - не критично, просто лишаємо орієнтацію як є.
        return pil_img, False

    angle = int(osd.get("rotate", 0) or 0)
    conf = float(osd.get("orientation_conf", 0) or 0)
    if angle == 0:
        return pil_img, False
    if conf < 1.0:
        # Дуже непевне визначення (напр. дуже мало тексту на сторінці) -
        # краще не ризикувати й лишити як є, ніж повернути правильну
        # сторінку неправильно.
        if log_fn:
            log_fn(
                f"  Орієнтація: можливий поворот на {angle}°, але "
                f"впевненість замала ({conf:.1f}) - не чіпаю")
        return pil_img, False

    if log_fn:
        log_fn(f"  Орієнтація: сторінку повернуто на {angle}°, виправляю...")
    return pil_img.rotate(-angle, expand=True), True


def preprocess_for_ocr(pil_img):
    """Готує зображення для Tesseract.

    На відміну від EasyOCR (нейромережа, стійка до "сирого" кольорового
    зображення), класичний Tesseract значно точніший на чистому
    чорно-білому вході з високим контрастом. Тому: переводимо в
    відтінки сірого й піднімаємо контраст (autocontrast). Якщо сторінка
    дрібна (низький DPI) - додатково збільшуємо, бо для Tesseract
    рекомендований мінімум ~300 DPI, а дрібні літери він банально не
    розпізнає."""
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
        # відносно висоти шрифту. Навмисно з великим запасом (5x висоти
        # шрифту, мінімум 90px): на практиці розрив між реальними
        # колонками - сотні пікселів (~600px на типовому розвороті A4 при
        # 300 DPI), тоді як випадкова прогалина через дрібний огріх OCR
        # (напр. кілька невпевнено розпізнаних символів після
        # розпрямлення сторінки) - зазвичай 60-90px. Занизький поріг тут
        # раніше хибно розбивав такі рядки навпіл.
        split_threshold = max(median_gap * 4, avg_h * 5, 90)

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
    """Запускає Tesseract на зображенні сторінки та повертає
    (lines, confidence_score):
    lines - список {"text": str, "bbox": (x0,y0,x1,y1)} у пікселях
    оригінального pil_img; confidence_score - середньозважена впевненість
    переможного проходу (0-100), для позначення сторінок з сумнівним
    розпізнаванням."""
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
    score_latin = _pass_score(data_latin)
    score_cyr = _pass_score(data_cyr)
    data, score = (data_latin, score_latin) if score_latin >= score_cyr else (
        data_cyr, score_cyr)

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
    return lines, max(score, 0.0)


_CV2_MODULE = None
_NP_MODULE = None


def _lazy_import_cv2():
    """Лінивий імпорт opencv-python-headless + numpy. Вони НЕ входять в
    основні залежності і не імпортуються при старті програми - лише коли
    користувач реально вмикає опцію розпрямлення сторінок. Так на слабких
    ПК, де ця опція не використовується, вона не займає ані байта пам'яті
    понад те, що вже потрібно решті програми."""
    global _CV2_MODULE, _NP_MODULE
    if _CV2_MODULE is None:
        try:
            import cv2 as _cv2
            import numpy as _np
        except ImportError:
            raise RuntimeError(
                "Для розпрямлення сторінок потрібен пакет opencv-python-headless.\n"
                "Встановіть: pip install opencv-python-headless numpy\n"
                "(або, якщо проєкт запущено через uv: uv sync --extra dewarp)"
            )
        _CV2_MODULE, _NP_MODULE = _cv2, _np
    return _CV2_MODULE, _NP_MODULE


def _dewarp_global_curve(pil_img, cv2, np, log_fn=None):
    """Стратегія 1: одна спільна "крива згину" на всю сторінку.

    Працює на локальній проекції яскравості по вузьких смугах (без
    Tesseract - швидше й не залежить від якості розпізнавання), тому
    добре підходить, коли кривизна ОДНАКОВА для всіх рядків (типовий
    рівномірний згин сторінки). Повертає None, якщо не вдалось впевнено
    побудувати єдину модель (ознака, що кривизна для різних рядків
    відрізняється - тоді краще підійде _dewarp_perline)."""
    arr = np.array(pil_img.convert("RGB"))
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    h, w = gray.shape
    thresh = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 25, 15
    )

    n_strips = 30
    strip_w = max(20, w // n_strips)
    smooth_k = max(5, h // 170)
    strip_centers, strip_line_ys = [], []
    for i in range(n_strips):
        x0, x1 = i * strip_w, min(w, (i + 1) * strip_w)
        if x1 - x0 < 5:
            continue
        row_density = thresh[:, x0:x1].sum(axis=1).astype(np.float64)
        if row_density.max() <= 0:
            continue
        row_density = np.convolve(
            row_density, np.ones(smooth_k) / smooth_k, mode="same")
        threshold_val = row_density.max() * 0.25
        peaks, in_peak, peak_start = [], False, 0
        for y in range(h):
            if row_density[y] > threshold_val:
                if not in_peak:
                    in_peak, peak_start = True, y
            else:
                if in_peak:
                    in_peak = False
                    peaks.append((peak_start + y) / 2)
        if in_peak:
            peaks.append((peak_start + h) / 2)
        if peaks:
            strip_centers.append((x0 + x1) / 2)
            strip_line_ys.append(peaks)

    if len(strip_centers) < 5:
        return None

    from collections import Counter
    common_n, n_match = Counter(len(p)
                                for p in strip_line_ys).most_common(1)[0]
    if common_n < 3 or n_match < len(strip_centers) * 0.6:
        # Занадто мало смуг узгоджені по кількості рядків - типова
        # ознака, що кривизна різна для різних рядків (складне фото).
        return None

    line_curve_points = [[] for _ in range(common_n)]
    for cx, ys in zip(strip_centers, strip_line_ys):
        if len(ys) != common_n:
            continue
        for idx, y in enumerate(ys):
            line_curve_points[idx].append((cx, y))

    grid_x = np.linspace(0, w, 200)
    all_curv = []
    for pts in line_curve_points:
        if len(pts) < 5:
            continue
        xs = np.array([p[0] for p in pts])
        ys = np.array([p[1] for p in pts])
        curvature = ys - ys.mean()
        all_curv.append(np.interp(grid_x, xs, curvature,
                        left=np.nan, right=np.nan))

    if len(all_curv) < 3:
        return None

    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        avg_curv = np.nanmedian(np.array(all_curv), axis=0)
    valid = ~np.isnan(avg_curv)
    if valid.sum() < 10:
        return None

    # Перевіряємо, що рядки дійсно узгоджені: розкид (IQR) між рядками
    # на кожній x-точці має бути малим порівняно з самою кривизною -
    # інакше це не "одна крива", а суміш різних кривих, усереднення яких
    # дасть викривлений (неправильний) результат.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        spread = np.nanstd(np.array(all_curv), axis=0)
    typical_spread = float(np.nanmedian(spread[valid]))
    max_bend = float(np.max(np.abs(avg_curv[valid])))
    if max_bend < 3.0:
        return "no_bend"
    if typical_spread > max(6.0, max_bend * 0.5):
        return None  # рядки надто розходяться - краще per-line

    poly_coeffs = np.polyfit(grid_x[valid], avg_curv[valid], deg=4)
    full_curve = np.polyval(poly_coeffs, np.arange(w))

    map_x, map_y = np.meshgrid(
        np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    map_y = map_y + full_curve.astype(np.float32)[np.newaxis, :]
    dewarped = cv2.remap(
        arr, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

    if log_fn:
        log_fn(
            f"  Розпрямлення: єдина крива для сторінки, викривлення до {max_bend:.0f}px")
    return Image.fromarray(dewarped)


def _dewarp_perline(pil_img, cv2, np, log_fn=None):
    """Стратегія 2 (fallback): кожен рядок випрямляється окремо за
    власною формою, визначеною через позиції слів з Tesseract. Повільніша
    й менш точна за _dewarp_global_curve на простих випадках, зате працює
    і тоді, коли кривизна для різних рядків різна (фото під кутом)."""
    arr = np.array(pil_img.convert("RGB"))
    h, w = arr.shape[:2]

    proc_img = preprocess_for_ocr(pil_img)
    data = _run_tesseract_pass(proc_img, _LATIN_LANGS, "--oem 1 --psm 3")
    words = _extract_words(data, 0)
    groups = _group_words_into_lines(words)

    scale_x = pil_img.width / proc_img.width
    scale_y = pil_img.height / proc_img.height

    line_infos = []
    for group in groups:
        if len(group) < 4:
            continue
        xs = np.array([wd["x"] for wd in group]) * scale_x
        ys = np.array([(wd["y"] + wd["h"] / 2) for wd in group]) * scale_y
        hs = np.array([wd["h"] for wd in group]) * scale_y
        if xs.max() - xs.min() < w * 0.15:
            continue
        deg = 2 if len(xs) >= 6 else 1
        coeffs = np.polyfit(xs, ys, deg)
        line_infos.append({
            "coeffs": coeffs, "target_y": float(np.median(ys)),
            "med_h": float(np.median(hs)),
            "x0": float(xs.min()), "x1": float(xs.max()),
        })

    if len(line_infos) < 3:
        if log_fn:
            log_fn("  Розпрямлення: замало придатних рядків для оцінки, пропущено")
        return pil_img

    max_bend = max(
        float(np.max(np.abs(np.polyval(li["coeffs"], np.linspace(
            li["x0"], li["x1"], 20)) - li["target_y"])))
        for li in line_infos
    )
    if max_bend < 3.0:
        if log_fn:
            log_fn("  Розпрямлення: помітного викривлення не виявлено, без змін")
        return pil_img

    line_infos.sort(key=lambda li: li["target_y"])
    output = arr.copy()
    n_corrected = 0
    for i, li in enumerate(line_infos):
        gap_above = (li["target_y"] - line_infos[i - 1]
                     ["target_y"]) / 2 if i > 0 else 1e9
        gap_below = (line_infos[i + 1]["target_y"] - li["target_y"]
                     ) / 2 if i < len(line_infos) - 1 else 1e9
        band_half = min(li["med_h"] * 1.6 + 8,
                        max(6.0, min(gap_above, gap_below) - 2))

        y0 = int(max(0, li["target_y"] - band_half))
        y1 = int(min(h, li["target_y"] + band_half))
        x0 = int(max(0, li["x0"] - 20))
        x1 = int(min(w, li["x1"] + 20))
        if y1 <= y0 or x1 <= x0:
            continue

        col_x = np.arange(x0, x1)
        shift = (np.polyval(li["coeffs"], col_x) -
                 li["target_y"]).astype(np.float32)
        shift = np.clip(shift, -h * 0.05, h * 0.05)

        map_x_band, map_y_band = np.meshgrid(
            col_x.astype(np.float32), np.arange(y0, y1, dtype=np.float32))
        map_y_band = map_y_band + shift[np.newaxis, :]
        band = cv2.remap(
            arr, map_x_band, map_y_band, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        output[y0:y1, x0:x1] = band
        n_corrected += 1

    if n_corrected == 0:
        if log_fn:
            log_fn("  Розпрямлення: не вдалось скоригувати жоден рядок, пропущено")
        return pil_img

    if log_fn:
        log_fn(
            f"  Розпрямлення: скориговано {n_corrected} рядків окремо "
            f"(різна кривизна по рядках, до {max_bend:.0f}px)")
    return Image.fromarray(output)


def dewarp_page_image(pil_img, log_fn=None):
    """Намагається виправити викривлення сторінки - типово для сканів чи
    фото розгорнутої книги/документа. Повертає новий PIL.Image або
    оригінал без змін, якщо виправити нема чого чи даних замало.

    Пробує ДВІ стратегії по черзі:
    1. _dewarp_global_curve - одна спільна крива для всієї сторінки.
       Швидша й точніша, коли кривизна ОДНАКОВА для всіх рядків
       (типовий рівномірний згин сторінки).
    2. Якщо перша не змогла впевнено побудувати єдину модель (ознака, що
       кривизна різна для різних рядків - типово для фото під кутом) -
       fallback на _dewarp_perline: кожен рядок випрямляється окремо за
       власною формою. Універсальніший, але трохи менш точний на
       простих випадках і повільніший.

    Чесно про межі методу: на дуже складних фото (згин + нахил +
    відблиски одночасно) результат не ідеальний і не завжди дає чистий
    виграш - це помітне, але не магічне виправлення."""
    cv2, np = _lazy_import_cv2()

    result = _dewarp_global_curve(pil_img, cv2, np, log_fn=log_fn)
    if result == "no_bend":
        if log_fn:
            log_fn("  Розпрямлення: помітного викривлення не виявлено, без змін")
        return pil_img
    if result is not None:
        return result

    if log_fn:
        log_fn("  Розпрямлення: єдина крива не підійшла (різна кривизна по рядках), пробую по-рядково...")
    return _dewarp_perline(pil_img, cv2, np, log_fn=log_fn)
