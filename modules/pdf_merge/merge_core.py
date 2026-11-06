"""Логіка об'єднання PDF (без GUI)."""
import os

import pymupdf as fitz


def page_count(path):
    """Кількість сторінок або RuntimeError (пошкоджений/захищений файл)."""
    try:
        with fitz.open(path) as doc:
            if doc.needs_pass:
                raise RuntimeError("файл захищено паролем")
            return len(doc)
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"не вдалося відкрити: {e}")


def merge_pdfs(paths, out_path, bookmarks=True, progress_cb=None,
               cancel_event=None):
    """Об'єднує файли за порядком у списку. Якщо bookmarks=True - додає
    закладку на початок кожного файла (назва без розширення) і зберігає
    власні закладки вихідних файлів як вкладені."""
    if not paths:
        raise RuntimeError("Немає файлів для об'єднання.")
    out = fitz.open()
    toc = []
    try:
        for i, src in enumerate(paths, 1):
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("Скасовано.")
            name = os.path.basename(src)
            try:
                with fitz.open(src) as doc:
                    if doc.needs_pass:
                        raise RuntimeError("файл захищено паролем")
                    start = len(out)
                    out.insert_pdf(doc)
                    if bookmarks and len(doc):
                        toc.append([1, os.path.splitext(name)[0], start + 1])
                        for lvl, title, page in doc.get_toc(simple=True):
                            if page >= 1:
                                toc.append([min(lvl + 1, 3 + lvl), title,
                                            start + page])
            except RuntimeError as e:
                raise RuntimeError(f"{name}: {e}")
            except Exception as e:
                raise RuntimeError(f"{name}: не вдалося відкрити ({e})")
            if progress_cb:
                progress_cb(i, len(paths))
        if bookmarks and toc:
            toc = _fix_toc_levels(toc)
            out.set_toc(toc)
        out.save(out_path, garbage=3, deflate=True)
        return len(out)
    finally:
        out.close()


def _fix_toc_levels(toc):
    """PyMuPDF вимагає, щоб рівень наступної закладки був не більшим за
    попередній +1."""
    fixed, prev = [], 0
    for lvl, title, page in toc:
        lvl = max(1, min(lvl, prev + 1))
        fixed.append([lvl, title, page])
        prev = lvl
    return fixed
