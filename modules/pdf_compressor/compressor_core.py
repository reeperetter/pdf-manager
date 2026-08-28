"""
Логіка стиснення PDF-файлів.

Підхід: текст, вектори та шрифти в PDF стискаються без втрат (deflate).
Основний виграш у розмірі дає перекодування вбудованих растрових зображень
(наприклад, сканованих сторінок) у JPEG з обмеженням ефективної роздільної
здатності (DPI відносно розміру сторінки) та заданою якістю стиснення.

Не потребує жодних додаткових залежностей - використовує лише pymupdf
та pillow, які вже є в базових залежностях проєкту.
"""

import io
import os

import pymupdf as fitz
from PIL import Image


# Готові пресети рівнів стиснення.
# max_dpi - максимальна ефективна роздільна здатність зображення на сторінці.
# jpeg_quality - якість перекодування JPEG (1-95).
COMPRESSION_PRESETS = {
    "light": {
        "label": "Легке (висока якість)",
        "max_dpi": 200,
        "jpeg_quality": 85,
    },
    "medium": {
        "label": "Середнє (рекомендовано)",
        "max_dpi": 150,
        "jpeg_quality": 65,
    },
    "strong": {
        "label": "Сильне (максимальна економія)",
        "max_dpi": 100,
        "jpeg_quality": 45,
    },
}

DEFAULT_PRESET_KEY = "medium"


def _has_own_alpha(pil_img):
    """Перевіряє, чи зображення має власний альфа-канал (не окремий SMask)."""
    if pil_img.mode in ("RGBA", "LA", "PA"):
        return True
    if pil_img.mode == "P" and "transparency" in pil_img.info:
        return True
    return False


def compress_pdf_file(src_path, out_path, max_dpi=150, jpeg_quality=65, progress_callback=None):
    """
    Стискає один PDF-файл і зберігає результат за шляхом out_path.

    Повертає кортеж (original_size_bytes, new_size_bytes).
    Кидає виняток, якщо файл не вдалося відкрити чи зберегти взагалі -
    обробка окремих "проблемних" зображень усередині файлу при цьому
    не переривається (вони просто лишаються без змін).
    """
    original_size = os.path.getsize(src_path)

    doc = fitz.open(src_path)
    processed_xrefs = set()
    total_pages = len(doc)

    try:
        for page_index, page in enumerate(doc):
            page_rect = page.rect
            page_w_in = (page_rect.width / 72.0) if page_rect.width else 0
            page_h_in = (page_rect.height / 72.0) if page_rect.height else 0

            for img in page.get_images(full=True):
                xref = img[0]
                smask_xref = img[1]

                if xref in processed_xrefs:
                    continue
                processed_xrefs.add(xref)

                try:
                    base = doc.extract_image(xref)
                    img_bytes = base["image"]
                    pil_img = Image.open(io.BytesIO(img_bytes))

                    # Якщо в зображення "вшита" власна прозорість і немає
                    # окремого SMask - не чіпаємо його, щоб не зіпсувати вигляд.
                    if _has_own_alpha(pil_img) and smask_xref == 0:
                        continue

                    if pil_img.mode not in ("RGB", "L"):
                        pil_img = pil_img.convert("RGB")

                    w, h = pil_img.size
                    cur_dpi = max(
                        w / page_w_in if page_w_in else max_dpi,
                        h / page_h_in if page_h_in else max_dpi,
                    )

                    if cur_dpi > max_dpi and max_dpi > 0:
                        scale = max_dpi / cur_dpi
                        new_dims = (max(1, int(w * scale)), max(1, int(h * scale)))
                        pil_img = pil_img.resize(new_dims, Image.LANCZOS)

                    buf = io.BytesIO()
                    pil_img.save(buf, format="JPEG", quality=jpeg_quality, optimize=True)
                    new_bytes = buf.getvalue()

                    # Замінюємо, лише якщо це реально зменшує розмір зображення.
                    if len(new_bytes) < len(img_bytes):
                        page.replace_image(xref, stream=new_bytes)
                except Exception:
                    # Проблемне зображення (незвичайний формат/кольоропростір
                    # тощо) - пропускаємо, продовжуємо з рештою файлу.
                    continue

            if progress_callback:
                progress_callback(page_index + 1, total_pages)

        doc.save(
            out_path,
            garbage=4,
            deflate=True,
            deflate_images=True,
            deflate_fonts=True,
            clean=True,
        )
    finally:
        doc.close()

    new_size = os.path.getsize(out_path)
    return original_size, new_size


def format_size(num_bytes):
    """Форматує розмір у людяному вигляді (Б/КБ/МБ/ГБ)."""
    size = float(num_bytes)
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if size < 1024 or unit == "ГБ":
            return f"{size:.0f} {unit}" if unit == "Б" else f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} ГБ"
