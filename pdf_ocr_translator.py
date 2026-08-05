import io
import os
import sys
import glob
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
    import numpy as np
except ImportError:
    MISSING.append("numpy")
try:
    from PIL import Image
except ImportError:
    MISSING.append("pillow")
try:
    import easyocr
except ImportError:
    MISSING.append("easyocr")
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


def ocr_lines_from_image(reader, pil_img, min_confidence=0.25):
    """Запускає EasyOCR на зображенні сторінки та повертає список рядків:
    {"text": str, "bbox": (x0,y0,x1,y1)} у пікселях зображення."""
    arr = np.array(pil_img.convert("RGB"))
    raw_results = reader.readtext(arr)
    lines = []
    for bbox_points, text, conf in raw_results:
        text = text.strip()
        if not text or conf < min_confidence:
            continue
        xs = [p[0] for p in bbox_points]
        ys = [p[1] for p in bbox_points]
        lines.append(
            {"text": text, "bbox": (min(xs), min(ys), max(xs), max(ys))}
        )
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


def process_pdf(
    input_path,
    output_dir,
    dpi,
    make_searchable,
    translate_targets,   # список кодів мов deep-translator, напр. ["uk", "ru"]
    font_path,
    log_fn,
    cancel_event,
    reader=None,         # easyocr.Reader або None, якщо OCR ще не потрібен
    get_reader=None,     # callable() -> reader; lazy-завантаження при fallback OCR
    force_ocr=False,     # True = завжди розпізнавати наново, ігноруючи текстовий шар PDF
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

    def ensure_reader():
        nonlocal reader
        if reader is None:
            if get_reader is None:
                raise RuntimeError(
                    "OCR потрібен, але модель розпізнавання не завантажена.")
            reader = get_reader()
        return reader

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
            # 1) Якщо не увімкнено примусовий OCR — спершу пробуємо взяти
            #    вже наявний текстовий шар PDF. Це стосується ОБОХ режимів
            #    (і "розпізнаваний PDF", і "переклад"), а не лише перекладу,
            #    як було раніше. Саме тут ховався головний баг: раніше для
            #    "розпізнаваного PDF" OCR запускався на кожній сторінці
            #    безумовно, навіть коли текст уже був у файлі.
            if not force_ocr:
                lines = extract_lines_from_page(page)
            if lines:
                log_fn(
                    f"[{base_name}] Сторінка {page_index + 1}/{n_pages}: "
                    f"текст з PDF ({len(lines)} рядків), OCR пропущено")
            else:
                reason = "примусовий режим OCR" if force_ocr else "немає текстового шару"
                log_fn(
                    f"[{base_name}] Сторінка {page_index + 1}/{n_pages}: "
                    f"{reason} — розпізнавання (OCR)...")
                lines = ocr_lines_from_image(ensure_reader(), pil_img)

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
                    try:
                        translations[lang] = translators[lang].translate_batch(
                            texts_to_translate
                        )
                    except Exception as e:
                        log_fn(
                            f"  [!] Помилка перекладу ({lang}): {e}. Пробую по рядку...")
                        result = []
                        for t in texts_to_translate:
                            try:
                                result.append(translators[lang].translate(t))
                            except Exception:
                                result.append(t)
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

    os.makedirs(output_dir, exist_ok=True)
    saved_files = []

    if out_searchable is not None:
        out_path = os.path.join(output_dir, f"{base_name}_searchable.pdf")
        out_searchable.save(out_path)
        out_searchable.close()
        saved_files.append(out_path)

    for lang in translate_targets:
        out_path = os.path.join(output_dir, f"{base_name}_{lang}.pdf")
        out_translated[lang].save(out_path)
        out_translated[lang].close()
        saved_files.append(out_path)

    doc.close()
    return saved_files


# =========================================================================
#  GUI
# =========================================================================

# (назва для відображення, код мови EasyOCR)
OCR_LANGS = [
    ("Українська", "uk"),
    ("Російська", "ru"),
    ("Англійська", "en"),
]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PDF-manager: OCR + переклад")
        self.geometry("780x680")
        self.minsize(700, 580)

        self.files = []
        self.log_queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker_thread = None
        self.reader_cache = {}  # {(tuple(sorted(langs)), gpu): easyocr.Reader}

        # Діалоги вибору файлів за замовчуванням відкриваються в корені
        # диска (Linux: "/", Windows: "C:\\"), а далі запам'ятовують
        # останню відкриту користувачем директорію.
        self.last_dir = os.path.expanduser("~")

        self.gui_font = setup_gui_fonts(self)
        self._build_ui()
        self.after(150, self._poll_log_queue)

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

        frm_opts = ttk.LabelFrame(self, text="2. Мови розпізнавання (OCR)")
        frm_opts.pack(fill="x", **pad)

        ttk.Label(
            frm_opts,
            text="Яку(і) мову(и) шукати в тексті оригіналу (потрібно для розпізнаваного PDF\n"
            "або для сканів без текстового шару при перекладі):",
        ).grid(row=0, column=0, columnspan=4, sticky="w", **pad)
        self.ocr_lang_vars = {}
        col = 0
        for label, code in OCR_LANGS:
            var = tk.BooleanVar(value=True)  # усі увімкнені за замовчуванням
            self.ocr_lang_vars[code] = var
            ttk.Checkbutton(frm_opts, text=label, variable=var).grid(
                row=1, column=col, sticky="w", padx=12, pady=2
            )
            col += 1

        ttk.Label(frm_opts, text="DPI рендерингу:").grid(
            row=2, column=0, sticky="w", **pad)
        self.dpi_var = tk.IntVar(value=300)
        ttk.Spinbox(frm_opts, from_=150, to=600, increment=50, textvariable=self.dpi_var, width=6).grid(
            row=2, column=1, sticky="w", **pad
        )

        self.gpu_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frm_opts, text="Використовувати GPU, якщо доступно (прискорює розпізнавання)",
            variable=self.gpu_var,
        ).grid(row=3, column=0, columnspan=4, sticky="w", **pad)

        self.force_ocr_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            frm_opts,
            text="Завжди розпізнавати наново (OCR), навіть якщо в PDF вже є текстовий шар",
            variable=self.force_ocr_var,
        ).grid(row=4, column=0, columnspan=4, sticky="w", **pad)

        ttk.Label(
            frm_opts,
            text="Шрифт з кирилицею (необов'язково — за замовчуванням\nвикористовується вбудований DejaVu Sans):",
        ).grid(row=5, column=0, columnspan=2, sticky="w", **pad)
        self.font_var = tk.StringVar(value="")
        font_entry_kwargs = {"textvariable": self.font_var, "width": 40}
        if entry_font:
            font_entry_kwargs["font"] = entry_font
        tk.Entry(frm_opts, **font_entry_kwargs).grid(
            row=5, column=2, sticky="w", **pad
        )
        ttk.Button(frm_opts, text="Огляд...", command=self.choose_font).grid(
            row=5, column=3, sticky="w", **pad)

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
        if not (self.var_searchable.get() or self.var_uk.get() or self.var_ru.get()):
            messagebox.showwarning(
                "Нічого робити", "Виберіть хоча б одну дію у розділі 3.")
            return

        make_searchable = self.var_searchable.get()
        translate_targets = []
        if self.var_uk.get():
            translate_targets.append("uk")
        if self.var_ru.get():
            translate_targets.append("ru")

        ocr_langs = [code for code,
                     var in self.ocr_lang_vars.items() if var.get()]
        if (make_searchable or translate_targets) and not ocr_langs:
            messagebox.showwarning(
                "Немає мов OCR",
                "Виберіть хоча б одну мову OCR у розділі 2.\n\n"
                "OCR запуститься лише для сторінок, де немає текстового шару "
                "(або для всіх сторінок, якщо увімкнено «Завжди розпізнавати наново»).",
            )
            return

        dpi = self.dpi_var.get()
        font_path = self.font_var.get().strip() or None
        out_dir = self.out_dir_var.get().strip()
        gpu = self.gpu_var.get()
        force_ocr = self.force_ocr_var.get()

        self.cancel_event.clear()
        self.start_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self.progress.config(maximum=len(self.files), value=0)

        self.worker_thread = threading.Thread(
            target=self._run_worker,
            args=(
                list(self.files), out_dir, ocr_langs, gpu, dpi,
                self.var_searchable.get(), translate_targets, font_path, force_ocr,
            ),
            daemon=True,
        )
        self.worker_thread.start()

    def cancel_processing(self):
        self.cancel_event.set()
        self.log(">>> Скасування... зачекайте завершення поточної сторінки.")

    def _get_reader(self, ocr_langs, gpu):
        key = (tuple(sorted(ocr_langs)), gpu)
        if key not in self.reader_cache:
            self.log(
                f"Завантаження моделі розпізнавання для мов {', '.join(ocr_langs)} "
                f"(лише при першому запуску, потрібен інтернет)..."
            )
            self.reader_cache[key] = easyocr.Reader(
                list(ocr_langs), gpu=gpu, verbose=False)
            self.log("Модель готова.")
        return self.reader_cache[key]

    def _run_worker(self, files, out_dir, ocr_langs, gpu, dpi, make_searchable, translate_targets, font_path, force_ocr):
        reader = None
        reader_error = None

        def get_reader():
            nonlocal reader, reader_error
            if reader is not None:
                return reader
            if reader_error is not None:
                raise reader_error
            try:
                reader = self._get_reader(ocr_langs, gpu)
                return reader
            except Exception as exc:
                reader_error = exc
                raise

        # Модель OCR гарантовано знадобиться відразу, лише якщо увімкнено
        # примусовий OCR. В інших випадках вона підвантажується лениво —
        # тільки якщо для конкретної сторінки справді немає текстового шару.
        if force_ocr and (make_searchable or translate_targets):
            try:
                get_reader()
            except Exception:
                self.log(
                    f"[ПОМИЛКА] Не вдалося завантажити модель розпізнавання:\n{traceback.format_exc()}")
                self.start_btn.after(
                    0, lambda: self.start_btn.config(state="normal"))
                self.cancel_btn.after(
                    0, lambda: self.cancel_btn.config(state="disabled"))
                return

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
                    reader=reader,
                    get_reader=get_reader if ocr_langs else None,
                    force_ocr=force_ocr,
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