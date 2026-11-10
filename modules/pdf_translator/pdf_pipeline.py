"""
Основний PDF-пайплайн: рендеринг сторінок, розпізнавання (паралельно),
вставка розпізнаного/перекладеного тексту в PDF.

Допоміжні частини: pdf_layout.py (шрифти, геометрія), text_translation.py
(переклад), text_export.py (TXT/DOCX), images_pdf.py (зображення -> PDF),
ocr.py / dewarp.py / tesseract_setup.py (розпізнавання).
Імена, що раніше жили тут, реекспортуються для сумісності.
"""
import gc
import io
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pymupdf
from PIL import Image

from .dewarp import dewarp_page_image
from .errors import ProcessingCancelled
from .images_pdf import IMAGE_EXTENSIONS, images_to_pdf  # noqa: F401  (реекспорт)
from .ocr import (detect_and_fix_orientation, ocr_lines_from_image,
                  ocr_worker_count)
from .pdf_layout import (BUNDLED_FONT, FALLBACK_FONTS,  # noqa: F401  (реекспорт)
                         extract_lines_from_page, find_unicode_font, fit_fontsize,
                         line_to_pixel_bbox, line_to_rect, sample_bg_color)
from .text_export import save_text_outputs  # noqa: F401  (реекспорт)
from .text_translation import (detect_text_language, translate_lines,  # noqa: F401
                               translate_paragraphs, translate_with_glossary)



class PdfProcessResult:
    """Результат обробки одного PDF у пам'яті (ще не збережений на диск).

    Документи (searchable / translated[lang]) належить викликачу: його
    справа або зберегти їх, або вставити в інший документ і закрити."""

    def __init__(self, searchable, translated, original_texts,
                 translated_texts, low_confidence_pages):
        self.searchable = searchable
        self.translated = translated
        self.original_texts = original_texts
        self.translated_texts = translated_texts
        self.low_confidence_pages = low_confidence_pages

    def close(self):
        if self.searchable is not None:
            self.searchable.close()
            self.searchable = None
        for d in self.translated.values():
            d.close()
        self.translated = {}


MIN_RENDER_DPI = 200


def page_render_dpi(page, max_dpi):
    """DPI рендеру сторінки.

    Для скану немає сенсу рендерити вище за природну роздільність
    вбудованого зображення: це лише збільшує картинку (повільніший OCR,
    більший вихідний PDF) без жодного виграшу в чіткості. Тому беремо
    найвищу роздільність великих зображень на сторінці (округлюємо вгору
    до 10, в межах MIN_RENDER_DPI..max_dpi). Сторінки без великих
    зображень (векторний текст) рендеримо з max_dpi, як і раніше."""
    try:
        page_area = max(page.rect.width * page.rect.height, 1.0)
        best = 0.0
        for info in page.get_image_info():
            bbox = pymupdf.Rect(info["bbox"]) & page.rect
            if bbox.is_empty or bbox.width * bbox.height < 0.5 * page_area:
                continue
            w_in = info["bbox"][2] - info["bbox"][0]
            h_in = info["bbox"][3] - info["bbox"][1]
            if w_in <= 0 or h_in <= 0:
                continue
            dpi_x = info["width"] / (w_in / 72.0)
            dpi_y = info["height"] / (h_in / 72.0)
            best = max(best, dpi_x, dpi_y)
        if best <= 0:
            return max_dpi
        native = int(-(-best // 10) * 10)
        return max(MIN_RENDER_DPI, min(max_dpi, native))
    except Exception:
        return max_dpi


def _shutdown_pool(scope):
    """Зупиняє пул OCR, закриває документи потоків, відновлює OMP."""
    executor = scope.get("executor")
    if executor is not None:
        executor.shutdown(wait=True, cancel_futures=True)
    for d in scope.get("worker_docs", []):
        try:
            d.close()
        except Exception:
            pass
    if "old_omp" in scope and scope.get("workers", 1) > 1:
        if scope["old_omp"] is None:
            os.environ.pop("OMP_THREAD_LIMIT", None)
        else:
            os.environ["OMP_THREAD_LIMIT"] = scope["old_omp"]


def _process_pdf_core(
    input_path,
    dpi,
    make_searchable,
    translate_targets,
    font_path,
    log_fn,
    cancel_event,
    page_start=None,
    page_end=None,
    page_progress_fn=None,
    glossary=None,
    low_confidence_threshold=55,
    dewarp=False,
    collect_text=False,
    source_lang="auto",
):
    """Розпізнає/перекладає один PDF і повертає PdfProcessResult (у пам'яті)."""
    export_text_formats = {"txt"} if collect_text else set()
    glossary = glossary or set()
    low_confidence_pages = []
    original_page_texts = []
    translated_page_texts = {lang: [] for lang in translate_targets}

    base_name = os.path.splitext(os.path.basename(input_path))[0]
    doc = pymupdf.open(input_path)
    n_pages = doc.page_count

    fontfile = find_unicode_font(font_path)
    if fontfile is None:
        doc.close()
        raise RuntimeError("Не знайдено TTF-шрифт з підтримкою кирилиці.")

    out_searchable = pymupdf.open() if make_searchable else None
    out_translated = {lang: pymupdf.open() for lang in translate_targets}

    try:
        dewarp_state = {"on": dewarp}
        local = threading.local()
        worker_docs = []
        docs_lock = threading.Lock()

        def thread_doc():
            """Документ PyMuPDF не можна ділити між потоками: у кожного
            потоку власна копія."""
            d = getattr(local, "doc", None)
            if d is None:
                d = pymupdf.open(input_path)
                local.doc = d
                with docs_lock:
                    worker_docs.append(d)
            return d

        def analyze(page_index):
            """Рендер + орієнтація + розпрямлення + OCR однієї сторінки
            (виконується у пулі потоків; не чіпає вихідні документи)."""
            if cancel_event and cancel_event.is_set():
                raise ProcessingCancelled()
            page_num = page_index + 1
            in_range = (page_start is None or page_num >= page_start) and \
                       (page_end is None or page_num <= page_end)

            page = thread_doc()[page_index]
            page_dpi = page_render_dpi(page, dpi)
            pix = page.get_pixmap(dpi=page_dpi)
            img_bytes = pix.tobytes("png")
            pil_img = Image.open(io.BytesIO(img_bytes))
            pil_img.load()
            del pix

            was_rotated = False
            if in_range:
                pil_img, was_rotated = detect_and_fix_orientation(
                    pil_img, log_fn=log_fn)
                if was_rotated:
                    buf = io.BytesIO()
                    pil_img.save(buf, format="PNG")
                    img_bytes = buf.getvalue()

            if dewarp_state["on"] and in_range:
                try:
                    corrected = dewarp_page_image(
                        pil_img, log_fn=log_fn, cancel_event=cancel_event)
                    if corrected is not pil_img:
                        pil_img = corrected
                        buf = io.BytesIO()
                        pil_img.save(buf, format="PNG")
                        img_bytes = buf.getvalue()
                except RuntimeError as e:
                    log_fn(f"  [!] Розпрямлення недоступне: {e}")
                    dewarp_state["on"] = False

            lines, ocr_score = [], None
            if in_range and (make_searchable or translate_targets or collect_text):
                if was_rotated:
                    lines, ocr_score = ocr_lines_from_image(
                        pil_img, source_lang=source_lang)
                else:
                    lines = extract_lines_from_page(page)
                    if not lines:
                        lines, ocr_score = ocr_lines_from_image(
                            pil_img, source_lang=source_lang)
            page = None
            return {
                "page_num": page_num, "pil_img": pil_img, "img_bytes": img_bytes,
                "lines": lines, "ocr_score": ocr_score, "dpi": page_dpi,
            }

        workers = min(ocr_worker_count(), max(1, n_pages))
        old_omp = os.environ.get("OMP_THREAD_LIMIT")
        if workers > 1:
            # Кожен екземпляр Tesseract - в один потік, щоб кілька сторінок
            # паралельно не конкурували за ядра.
            os.environ["OMP_THREAD_LIMIT"] = "1"
        executor = ThreadPoolExecutor(max_workers=workers)
        futures = {}
        next_submit = 0

        def submit_upto(limit):
            nonlocal next_submit
            while next_submit < min(limit, n_pages):
                futures[next_submit] = executor.submit(analyze, next_submit)
                next_submit += 1

        submit_upto(workers)
        for page_index in range(n_pages):
            if cancel_event and cancel_event.is_set():
                raise ProcessingCancelled()

            res = futures.pop(page_index).result()
            submit_upto(page_index + 1 + workers)

            page_num = res["page_num"]
            pil_img, img_bytes, lines = res["pil_img"], res["img_bytes"], res["lines"]
            page_dpi = res["dpi"]
            ocr_score = res["ocr_score"]
            if lines and ocr_score is not None and ocr_score < low_confidence_threshold:
                low_confidence_pages.append(page_num)
                log_fn(
                    f"  [!] Стор. {page_num}: низька впевненість OCR "
                    f"({ocr_score:.0f}/100)")

            page_w = pil_img.width * 72 / page_dpi
            page_h = pil_img.height * 72 / page_dpi
            scale_x = page_w / pil_img.width
            scale_y = page_h / pil_img.height

            if export_text_formats:
                original_page_texts.append("\n".join(ln["text"] for ln in lines))

            # 1) Searchable PDF
            if out_searchable is not None:
                sp = out_searchable.new_page(width=page_w, height=page_h)
                sp.insert_image(sp.rect, stream=img_bytes)
                for line in lines:
                    rect = line_to_rect(line, scale_x, scale_y)
                    if rect.is_empty or rect.width <= 0 or rect.height <= 0:
                        continue
                    fs = fit_fontsize(
                        line["text"], rect.width, rect.height, fontfile)
                    baseline = pymupdf.Point(rect.x0, rect.y1 - 0.15 * fs)
                    try:
                        sp.insert_text(
                            baseline,
                            line["text"],
                            fontsize=fs,
                            fontfile=fontfile,
                            fontname="cyr1",
                            render_mode=3,
                        )
                    except Exception as e:
                        log_fn(f"  [!] Пропущено рядок (текстовий шар): {e}")

            # 2) Translated PDF
            if translate_targets:
                translations = {}
                if lines:
                    for lang in translate_targets:
                        translated_lines = translate_paragraphs(
                            lines, glossary, target_lang=lang,
                            source_lang=source_lang, log_fn=log_fn,
                            cancel_event=cancel_event
                        )
                        translations[lang] = translated_lines

                if export_text_formats:
                    for lang in translate_targets:
                        text = "\n".join(translations.get(
                            lang, [])) if lines else ""
                        translated_page_texts[lang].append(text)

                for lang in translate_targets:
                    tp = out_translated[lang].new_page(width=page_w, height=page_h)
                    tp.insert_image(tp.rect, stream=img_bytes)
                    if not lines:
                        continue
                    translated_lines = translations[lang]

                    to_draw = []
                    for line, tr_text in zip(lines, translated_lines):
                        orig_text = line["text"].strip()
                        tr_text_stripped = (tr_text or "").strip()
                        if tr_text_stripped.lower() == orig_text.lower():
                            continue
                        rect = line_to_rect(line, scale_x, scale_y)
                        if rect.is_empty or rect.width <= 0 or rect.height <= 0:
                            continue
                        px_bbox = line_to_pixel_bbox(line, scale_x, scale_y)
                        bg = sample_bg_color(pil_img, px_bbox)
                        cover = pymupdf.Rect(rect.x0 - 1, rect.y0 - 1,
                                          rect.x1 + 1, rect.y1 + 1)
                        tp.draw_rect(cover, color=bg, fill=bg, overlay=True)
                        to_draw.append((rect, tr_text))

                    for rect, tr_text in to_draw:
                        if not tr_text:
                            continue
                        fs = fit_fontsize(tr_text, rect.width,
                                          rect.height, fontfile)
                        baseline = pymupdf.Point(rect.x0, rect.y1 - 0.15 * fs)
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

            del pil_img, img_bytes, lines, res
            pymupdf.TOOLS.store_shrink(100)
            gc.collect()

            if page_progress_fn:
                page_progress_fn(page_num, n_pages)

    except BaseException:
        # Скасування чи помилка посеред файлу - не лишаємо відкритих документів.
        _shutdown_pool(locals())
        if out_searchable is not None:
            out_searchable.close()
        for d in out_translated.values():
            d.close()
        doc.close()
        raise

    _shutdown_pool(locals())
    doc.close()
    gc.collect()
    return PdfProcessResult(
        out_searchable, out_translated, original_page_texts,
        translated_page_texts, low_confidence_pages)


def process_pdf(
    input_path,
    output_dir,
    dpi,
    make_searchable,
    translate_targets,
    font_path,
    log_fn,
    cancel_event,
    export_text_formats=None,
    export_text_split_pages=False,
    export_original_text=False,
    **core_kwargs,
):
    """Обробляє один PDF і зберігає результати у output_dir
    (<ім'я>_searchable.pdf, <ім'я>_<мова>.pdf, текстові файли)."""
    export_text_formats = export_text_formats or set()
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    res = _process_pdf_core(
        input_path, dpi, make_searchable, translate_targets, font_path,
        log_fn, cancel_event, collect_text=bool(export_text_formats),
        **core_kwargs)
    try:
        os.makedirs(output_dir, exist_ok=True)
        saved_files = []

        if res.searchable is not None:
            out_path = os.path.join(output_dir, f"{base_name}_searchable.pdf")
            res.searchable.save(out_path, garbage=3, deflate=True)
            saved_files.append(out_path)

        for lang, d in res.translated.items():
            out_path = os.path.join(output_dir, f"{base_name}_{lang}.pdf")
            d.save(out_path, garbage=3, deflate=True)
            saved_files.append(out_path)

        if export_text_formats:
            if export_original_text:
                saved_files += save_text_outputs(
                    res.original_texts, output_dir, base_name, "_text",
                    export_text_formats, export_text_split_pages)
            for lang in translate_targets:
                saved_files += save_text_outputs(
                    res.translated_texts[lang], output_dir, base_name,
                    f"_{lang}_text", export_text_formats,
                    export_text_split_pages)
        low_conf = res.low_confidence_pages
    finally:
        res.close()
    gc.collect()
    return saved_files, low_conf


class CombinedResult:
    """Накопичує результати кількох вхідних PDF в ОДИН вихідний файл
    (на кожну мову перекладу - свій), щоб зберегти їх разом."""

    def __init__(self, make_searchable, translate_targets, export_original_text=False):
        self.export_original_text = export_original_text
        self.translate_targets = list(translate_targets)
        self.searchable = pymupdf.open() if make_searchable else None
        self.translated = {lang: pymupdf.open() for lang in self.translate_targets}
        self.original_texts = []
        self.translated_texts = {lang: [] for lang in self.translate_targets}
        self.files_added = 0

    def add(self, res):
        """Дописує результат одного файлу в кінець і закриває його."""
        try:
            if self.searchable is not None and res.searchable is not None:
                self.searchable.insert_pdf(res.searchable)
            for lang in self.translate_targets:
                if lang in res.translated:
                    self.translated[lang].insert_pdf(res.translated[lang])
                self.translated_texts[lang].extend(
                    res.translated_texts.get(lang, []))
            self.original_texts.extend(res.original_texts)
            self.files_added += 1
        finally:
            res.close()

    def save(self, out_path, export_text_formats=None, export_text_split_pages=False):
        """Зберігає накопичене. out_path - шлях до головного .pdf.

        Для розпізнавання це і є вихідний файл. Для перекладу однією
        мовою - теж точно out_path; для кількох мов до імені додається
        _<мова> (<ім'я>_uk.pdf, <ім'я>_en.pdf)."""
        export_text_formats = export_text_formats or set()
        out_dir = os.path.dirname(out_path) or "."
        stem = os.path.splitext(os.path.basename(out_path))[0]
        os.makedirs(out_dir, exist_ok=True)
        saved = []

        if self.searchable is not None:
            self.searchable.save(out_path, garbage=3, deflate=True)
            saved.append(out_path)

        for lang in self.translate_targets:
            if len(self.translate_targets) == 1 and self.searchable is None:
                lang_path = out_path
            else:
                lang_path = os.path.join(out_dir, f"{stem}_{lang}.pdf")
            self.translated[lang].save(lang_path, garbage=3, deflate=True)
            saved.append(lang_path)

        if export_text_formats:
            if self.export_original_text:
                saved += save_text_outputs(
                    self.original_texts, out_dir, stem, "_text",
                    export_text_formats, export_text_split_pages)
            for lang in self.translate_targets:
                saved += save_text_outputs(
                    self.translated_texts[lang], out_dir, stem,
                    f"_{lang}_text", export_text_formats,
                    export_text_split_pages)
        return saved

    def close(self):
        if self.searchable is not None:
            self.searchable.close()
            self.searchable = None
        for d in self.translated.values():
            d.close()
        self.translated = {}
