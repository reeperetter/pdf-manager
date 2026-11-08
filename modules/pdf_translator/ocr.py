"""
Розпізнавання тексту (Tesseract OCR): орієнтація сторінки та
"зображення сторінки -> список розпізнаних рядків з координатами".

Пошук/встановлення Tesseract і мовних моделей - tesseract_setup.py,
виправлення викривлення - dewarp.py. PDF-специфічні речі (вставка тексту
в PDF, переклад, збереження файлів) - у pdf_pipeline.py.
"""
import os
import time

import pytesseract
from PIL import Image, ImageOps

from . import tesseract_setup
from .tesseract_setup import _external_tesseract_env


def _brute_force_orientation(pil_img, log_fn=None):
    """
    Перебір 4 кутів повороту для OSD.
    Знижено поріг confidence з 1.0 до 0.1, оскільки на діаграмах/панелях
    Tesseract рідко дає високу впевненість.
    """
    # Готуємо контрастну версію спеціально для перевірки OSD
    prep_img = preprocess_for_ocr(pil_img)

    best_angle, best_conf = 0, -1.0
    for angle in (0, 90, 180, 270):
        time.sleep(0.001)
        candidate = prep_img.rotate(-angle, expand=True) if angle else prep_img
        try:
            with _external_tesseract_env():
                osd = pytesseract.image_to_osd(
                    candidate, config="--psm 0", output_type=pytesseract.Output.DICT
                )
        except Exception:
            continue

        rotate_val = osd.get("rotate", None)
        if rotate_val is None or int(rotate_val) != 0:
            continue

        conf = float(osd.get("orientation_conf", 0) or 0)
        if conf > best_conf:
            best_conf, best_angle = conf, angle

    # Якщо знайшли кут з хоч якоюсь впевненістю (> 0.1)
    if best_angle != 0 and best_conf > 0.1:
        return best_angle, best_conf

    return 0, -1.0


def detect_and_fix_orientation(pil_img, log_fn=None):
    """Визначає поворот сторінки та повертає виправлений PIL.Image."""
    angle, conf = 0, 0.0

    # Використовуємо оброблене зображення для визначення орієнтації
    prep_img = preprocess_for_ocr(pil_img)

    try:
        with _external_tesseract_env():
            osd = pytesseract.image_to_osd(
                prep_img, config="--psm 0", output_type=pytesseract.Output.DICT
            )
        angle = int(osd.get("rotate", 0) or 0)
        conf = float(osd.get("orientation_conf", 0) or 0)
    except Exception:
        pass

    # Якщо прямому виклику OSD бракує впевненості (менше 0.5), пускаємо перебір
    if conf < 0.5:
        fallback_angle, fallback_conf = _brute_force_orientation(
            pil_img, log_fn=log_fn)
        if fallback_angle != 0:
            angle = fallback_angle
            conf = fallback_conf

    if angle != 0:
        # Повертаємо ОРИГІНАЛЬНЕ зображення, але повернуте на потрібний кут
        return pil_img.rotate(-angle, expand=True), True

    return pil_img, False


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
        with _external_tesseract_env():
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
    """Групує окремі слова у візуальні рядки з урахуванням розділення колонок."""
    if not words:
        return []

    # Розбиваємо слова на дві колонки, якщо є чітке розділення по ширині
    min_x = min(w["x"] for w in words)
    max_x = max(w["x"] + w["w"] for w in words)
    page_width = max_x - min_x

    # Пошук вертикального розриву між колонками
    columns = [words]
    if page_width > 500:
        mid_start = min_x + page_width * 0.35
        mid_end = min_x + page_width * 0.65

        left_words = [w for w in words if (w["x"] + w["w"]) <= mid_end]
        right_words = [w for w in words if w["x"] >= mid_start]

        # Перевірка на реальну наявність двох колонок
        if len(left_words) > 5 and len(right_words) > 5:
            # Перевірка, що між ними дійсно є простір
            max_left = max(w["x"] + w["w"] for w in left_words)
            min_right = min(w["x"] for w in right_words)
            if min_right - max_left > 15:
                columns = [left_words, right_words]

    groups = []
    for col_words in columns:
        rows = []
        for wd in sorted(col_words, key=lambda w: (w["y"], w["x"])):
            y_center = wd["y"] + wd["h"] / 2
            placed = False
            for row in rows:
                row_y_center = row["y_sum"] / row["count"]
                if abs(y_center - row_y_center) < row["h_avg"] * 0.6:
                    row["words"].append(wd)
                    row["y_sum"] += y_center
                    row["count"] += 1
                    row["h_avg"] = sum(w["h"] for w in row["words"]) / row["count"]
                    placed = True
                    break
            if not placed:
                rows.append({"words": [wd], "y_sum": y_center, "count": 1, "h_avg": wd["h"]})

        for row in rows:
            row_words = sorted(row["words"], key=lambda w: w["x"])
            gaps = [
                row_words[i]["x"] - (row_words[i - 1]["x"] + row_words[i - 1]["w"])
                for i in range(1, len(row_words))
            ]
            median_gap = sorted(gaps)[len(gaps) // 2] if gaps else 0
            avg_h = sum(w["h"] for w in row_words) / len(row_words)
            split_threshold = max(median_gap * 3, avg_h * 3, 50)

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


def ocr_lines_from_image(pil_img, min_confidence=0, source_lang="auto"):
    """Запускає Tesseract на зображенні сторінки та повертає рядки та впевненість."""
    if not tesseract_setup.TESSERACT_CMD:
        raise RuntimeError("Не знайдено виконуваний файл Tesseract OCR.")
    proc_img = preprocess_for_ocr(pil_img)
    scale_back_x = pil_img.width / proc_img.width
    scale_back_y = pil_img.height / proc_img.height

    config = "--oem 1 --psm 6"

    if source_lang == "auto":
        data_latin = _run_tesseract_pass(proc_img, _LATIN_LANGS, config)
        time.sleep(0.001)  # Пауза для GIL
        data_cyr = _run_tesseract_pass(proc_img, _CYRILLIC_LANGS, config)

        score_latin = _pass_score(data_latin)
        score_cyr = _pass_score(data_cyr)
        data, score = (data_latin, score_latin) if score_latin >= score_cyr else (
            data_cyr, score_cyr)
    else:
        data = _run_tesseract_pass(proc_img, source_lang, config)
        score = _pass_score(data)

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


def ocr_worker_count():
    """Скільки сторінок розпізнавати одночасно. Tesseract працює окремим
    процесом, тож потоки Python тут справді паралельні. Беремо половину
    ядер (до 4): решта лишається системі та самому Tesseract. На
    1-2 ядрах повертає 1 - поведінка як раніше."""
    return max(1, min(4, (os.cpu_count() or 2) // 2))
