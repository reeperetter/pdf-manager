"""Шрифти та геометрія: пошук Unicode-шрифту, рядки текстового шару PDF,
підбір розміру шрифту, колір фону під перекладений текст."""
import os

import pymupdf

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# DejaVuSans.ttf фізично лежить у КОРЕНІ репозиторію (поруч із main.py), а
# не в modules/pdf_translator/. У зібраному --onedir/--onefile застосунку
# це не впадало в очі, бо build.yml явно копіює файл саме сюди через
# --add-data "DejaVuSans.ttf;modules/pdf_translator" - але при запуску з
# сирого коду такого копіювання ніхто не робить, SCRIPT_DIR/DejaVuSans.ttf
# просто не існує, і пошук одразу провалювався в FALLBACK_FONTS (жорстко
# прописані системні шляхи, яких на конкретній машині може й не бути -
# звідси "Не знайдено TTF-шрифт з підтримкою кирилиці" при запуску з коду).
# Перевіряємо обидва місця, щоб працювало і так, і так, незалежно від
# того, чи є той самий --add-data у build.yml.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
_BUNDLED_FONT_CANDIDATES = [
    os.path.join(SCRIPT_DIR, "DejaVuSans.ttf"),
    os.path.join(_PROJECT_ROOT, "DejaVuSans.ttf"),
]
BUNDLED_FONT = next((p for p in _BUNDLED_FONT_CANDIDATES if os.path.isfile(p)), None)

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
    """Повертає шлях до TTF-шрифту, що підтримує кирилицю."""
    if user_path and os.path.isfile(user_path):
        return user_path
    if BUNDLED_FONT and os.path.isfile(BUNDLED_FONT):
        return BUNDLED_FONT
    for p in FALLBACK_FONTS:
        if os.path.isfile(p):
            return p
    return None


def extract_lines_from_page(page):
    """Витягує рядки тексту з наявного текстового шару PDF."""
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
                {"text": text, "bbox": (x0, y0, x1, y1), "page_coords": True,
                 "size": max(s.get("size", 0) for s in spans),
                 "font": spans[0].get("font", "")}
            )
    return lines


def line_to_rect(line, scale_x, scale_y):
    """Перетворює bbox рядка у pymupdf.Rect."""
    x0, y0, x1, y1 = line["bbox"]
    if line.get("page_coords"):
        return pymupdf.Rect(x0, y0, x1, y1)
    return pymupdf.Rect(x0 * scale_x, y0 * scale_y, x1 * scale_x, y1 * scale_y)


def line_to_pixel_bbox(line, scale_x, scale_y):
    """Перетворює bbox рядка у координати пікселів зображення."""
    x0, y0, x1, y1 = line["bbox"]
    if line.get("page_coords"):
        return (x0 / scale_x, y0 / scale_y, x1 / scale_y, y1 / scale_y)
    return line["bbox"]


def fit_fontsize(text, rect_width, rect_height, fontfile, max_size=None):
    """Підбирає розмір шрифту під прямокутник."""
    if max_size is None:
        max_size = max(4, rect_height * 0.85)
    size = max_size
    try:
        font = pymupdf.Font(fontfile=fontfile)
    except Exception:
        font = pymupdf.Font("helv")
    while size > 4:
        width = font.text_length(text, fontsize=size)
        if width <= rect_width or size <= 4.5:
            break
        size -= 0.5
    return size


def sample_bg_color(pil_img, bbox, pad=4):
    """Визначає колір фону навколо текстового блоку."""
    x0, y0, x1, y1 = bbox
    w, h = pil_img.size
    x0i, y0i, x1i, y1i = int(x0), int(y0), int(x1), int(y1)

    strips = [
        (x0i, max(0, y0i - pad), x1i, y0i),
        (x0i, y1i, x1i, min(h, y1i + pad)),
        (max(0, x0i - pad), y0i, x0i, y1i),
        (x1i, y0i, min(w, x1i + pad), y1i),
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
