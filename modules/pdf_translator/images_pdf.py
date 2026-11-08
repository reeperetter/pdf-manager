"""Конвертація зображень у PDF."""
import io
import os

import pymupdf
from PIL import Image, ImageOps

from .errors import ProcessingCancelled


IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp")


def _flatten_image_for_pdf(img):
    """Готує зображення для вставки у PDF-сторінку.

    Повертає (img_rgb_or_rgba, has_real_transparency):
    - якщо в зображення є альфа-канал, і хоч один піксель дійсно не
      повністю непрозорий (alpha < 255 десь є) - повертає RGBA як є,
      True. Такі зображення далі зберігаються як PNG (JPEG альфу не
      підтримує), і прозорі ділянки лишаються прозорими на сторінці
      (переглядач покаже під ними фон самої сторінки PDF, типово
      білий) - це і є "прозорий, де можливо".
    - інакше - складає зображення на БІЛИЙ фон і повертає RGB, False.
      Раніше тут був просто img.convert("RGB") - для RGBA-зображень
      PIL при такій конвертації просто ВІДКИДАЄ альфа-канал і лишає
      "сирі" RGB-значення пікселів як є, а в стертих/прозорих ділянках
      типового PNG ці значення часто (0, 0, 0) - звідси й чорний фон
      замість очікуваного білого чи прозорого.
    """
    has_alpha = img.mode in ("RGBA", "LA") or (
        img.mode == "P" and "transparency" in img.info
    )
    if not has_alpha:
        return img.convert("RGB"), False

    img = img.convert("RGBA")
    alpha_extrema = img.getchannel("A").getextrema()
    is_really_transparent = alpha_extrema[0] < 255
    if is_really_transparent:
        return img, True

    # Альфа-канал технічно є, але всі пікселі повністю непрозорі -
    # звичайний RGB-шлях, без зайвого PNG.
    background = Image.new("RGB", img.size, (255, 255, 255))
    background.paste(img, mask=img.getchannel("A"))
    return background, False


def images_to_pdf(image_paths, output_path, log_fn=None, progress_fn=None,
                  cancel_event=None, jpeg_quality=88, max_dimension=2200):
    """Збирає список зображень в один PDF."""
    assumed_dpi = 200
    doc = pymupdf.open()
    total_before = 0
    total_after = 0
    try:
        for i, img_path in enumerate(image_paths):
            if cancel_event is not None and cancel_event.is_set():
                raise ProcessingCancelled()
            try:
                total_before += os.path.getsize(img_path)
            except OSError:
                pass

            img = Image.open(img_path)
            img = ImageOps.exif_transpose(img)
            img, is_transparent = _flatten_image_for_pdf(img)

            if max(img.width, img.height) > max_dimension:
                scale = max_dimension / max(img.width, img.height)
                img = img.resize(
                    (max(1, int(img.width * scale)),
                     max(1, int(img.height * scale))),
                    Image.LANCZOS,
                )

            w_pt = img.width * 72 / assumed_dpi
            h_pt = img.height * 72 / assumed_dpi
            page = doc.new_page(width=w_pt, height=h_pt)

            buf = io.BytesIO()
            if is_transparent:
                # JPEG не підтримує прозорість - для таких зображень
                # зберігаємо без втрат у PNG, щоб прозорі ділянки
                # лишились прозорими на сторінці.
                img.save(buf, format="PNG", optimize=True)
            else:
                img.save(buf, format="JPEG", quality=jpeg_quality, optimize=True)
            total_after += buf.tell()
            page.insert_image(pymupdf.Rect(0, 0, w_pt, h_pt),
                              stream=buf.getvalue())

            if log_fn:
                log_fn(
                    f"  Додано сторінку {i + 1}/{len(image_paths)}: "
                    f"{os.path.basename(img_path)}"
                )
            if progress_fn:
                progress_fn(i + 1, len(image_paths))
        doc.save(output_path, garbage=3, deflate=True)
    finally:
        doc.close()

    if log_fn and total_before > 0:
        final_size = os.path.getsize(output_path)
        log_fn(
            f"  Стиснення: вихідні зображення ~{total_before / 1_048_576:.1f} МБ "
            f"→ підсумковий PDF {final_size / 1_048_576:.1f} МБ"
        )
    return output_path
