"""
Розпізнавання тексту (Tesseract OCR) та виправлення викривлення сторінок.

Усе, що стосується "зображення сторінки -> список розпізнаних рядків з
координатами", живе тут. PDF-специфічні речі (вставка тексту в PDF,
переклад, збереження файлів) - у pdf_pipeline.py.
"""
import os
import shutil
import time

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


def _brute_force_orientation(pil_img, log_fn=None):
    """Резервний метод, коли вбудований OSD Tesseract на оригінальному
    зображенні не може впевнено визначити орієнтацію (типово - сторінка
    з малою кількістю тексту, багато картинок, як приладова панель авто).

    Ідея: замість одного невпевненого запитання "як повернута сторінка?"
    ставимо OSD чотири РІЗНІ, простіші запитання - для кожної з 4
    можливих орієнтацій кандидата запитуємо "чи ТИ вже прямий?" (тобто
    чи OSD скаже rotate=0 саме для цього варіанта). Обираємо кандидата
    з найвищою впевненістю серед тих, хто відповів "так"."""
    best_angle, best_conf = None, -1.0
    for angle in (0, 90, 180, 270):
        time.sleep(0.001)  # Даємо GIL вивільнитись для UI
        candidate = pil_img.rotate(-angle, expand=True) if angle else pil_img
        try:
            osd = pytesseract.image_to_osd(
                candidate, output_type=pytesseract.Output.DICT)
        except Exception:
            continue
        rotate_val = osd.get("rotate", None)
        if rotate_val is None or int(rotate_val) != 0:
            continue
        conf = float(osd.get("orientation_conf", 0) or 0)
        if conf > best_conf:
            best_conf, best_angle = conf, angle
    if best_angle is None:
        return 0, -1.0
    return best_angle, best_conf


def detect_and_fix_orientation(pil_img, log_fn=None):
    """Визначає, чи сторінка повернута на 90/180/270° і виправляє її."""
    angle, conf = 0, 0.0
    try:
        osd = pytesseract.image_to_osd(
            pil_img, output_type=pytesseract.Output.DICT)
        angle = int(osd.get("rotate", 0) or 0)
        conf = float(osd.get("orientation_conf", 0) or 0)
    except Exception:
        pass

    if angle == 0 and conf >= 1.0:
        return pil_img, False

    if conf < 1.0:
        fallback_angle, fallback_conf = _brute_force_orientation(
            pil_img, log_fn=log_fn)
        if fallback_angle == 0 or fallback_conf < 1.0:
            return pil_img, False
        angle = fallback_angle
        if log_fn:
            log_fn(
                f"  Орієнтація: основний OSD не певен, за результатом "
                f"перебору обрано поворот на {angle}° (впевненість {fallback_conf:.1f})")
        return pil_img.rotate(-angle, expand=True), True

    if angle == 0:
        return pil_img, False

    if log_fn:
        log_fn(f"  Орієнтація: сторінку повернуто на {angle}°, виправляю...")
    return pil_img.rotate(-angle, expand=True), True


def preprocess_for_ocr(pil_img):
    """Готує зображення для Tesseract (контраст + масштабування)."""
    gray = ImageOps.grayscale(pil_img)
    gray = ImageOps.autocontrast(gray, cutoff=1)
    if gray.width < 1600:
        scale = 1600 / gray.width
        gray = gray.resize(
            (int(gray.width * scale), int(gray.height * scale)),
            Image.LANCZOS,
        )
    return gray


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
    """Оцінка якості проходу."""
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
    """Дістає з сирого виводу Tesseract список слів з координатами."""
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
    """Групує окремі слова у візуальні рядки."""
    if not words:
        return []

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
    """Запускає Tesseract на зображенні сторінки та повертає рядки та впевненість."""
    if not TESSERACT_CMD:
        raise RuntimeError(
            "Не знайдено виконуваний файл Tesseract OCR. Встановіть його:\n"
            "  Linux: sudo apt install tesseract-ocr tesseract-ocr-ukr tesseract-ocr-rus\n"
            "  Windows: https://github.com/UB-Mannheim/tesseract/wiki"
        )
    proc_img = preprocess_for_ocr(pil_img)
    scale_back_x = pil_img.width / proc_img.width
    scale_back_y = pil_img.height / proc_img.height

    config = "--oem 1 --psm 3"

    data_latin = _run_tesseract_pass(proc_img, _LATIN_LANGS, config)
    time.sleep(0.001)  # Пауза для GIL
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
    """Лінивий імпорт opencv-python-headless + numpy."""
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


def _dewarp_global_curve(pil_img, cv2, np, log_fn=None, cancel_event=None):
    """Стратегія 1: одна спільна "крива згину" на всю сторінку."""
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
        if cancel_event and cancel_event.is_set():
            return None
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

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        spread = np.nanstd(np.array(all_curv), axis=0)
    typical_spread = float(np.nanmedian(spread[valid]))
    max_bend = float(np.max(np.abs(avg_curv[valid])))
    if max_bend < 3.0:
        return "no_bend"
    if typical_spread > max(6.0, max_bend * 0.5):
        return None

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


def _dewarp_perline(pil_img, cv2, np, log_fn=None, cancel_event=None):
    """Стратегія 2 (fallback): кожен рядок випрямляється окремо."""
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
        if cancel_event and cancel_event.is_set():
            return pil_img
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
        if cancel_event and cancel_event.is_set():
            return pil_img
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


def dewarp_page_image(pil_img, log_fn=None, cancel_event=None):
    """Виправляє викривлення сторінки через _dewarp_global_curve чи _dewarp_perline."""
    cv2, np = _lazy_import_cv2()

    result = _dewarp_global_curve(
        pil_img, cv2, np, log_fn=log_fn, cancel_event=cancel_event)
    if result == "no_bend":
        if log_fn:
            log_fn("  Розпрямлення: помітного викривлення не виявлено, без змін")
        return pil_img
    if result is not None:
        return result

    if cancel_event and cancel_event.is_set():
        return pil_img

    if log_fn:
        log_fn("  Розпрямлення: єдина крива не підійшла (різна кривизна по рядках), пробую по-рядково...")
    return _dewarp_perline(
        pil_img, cv2, np, log_fn=log_fn, cancel_event=cancel_event)