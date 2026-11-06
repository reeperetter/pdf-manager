"""Логіка розділення PDF (без GUI)."""
import os
import re

import pymupdf as fitz

MODE_EACH = "each"        # кожна сторінка окремо
MODE_EVERY_N = "every_n"  # по N сторінок
MODE_RANGES = "ranges"    # за діапазонами "1-3, 5, 7-9"
MODE_BOOKMARKS = "bookmarks"  # за закладками верхнього рівня


def parse_ranges(text, n_pages):
    """"1-3, 5, 7-9" -> [(1,3),(5,5),(7,9)] (нумерація з 1, включно)."""
    result = []
    for part in re.split(r"[,;]+", text or ""):
        part = part.strip()
        if not part:
            continue
        m = re.fullmatch(r"(\d+)\s*(?:[-–—]\s*(\d+))?", part)
        if not m:
            raise RuntimeError(f"Некоректний діапазон: «{part}». "
                               "Приклад: 1-3, 5, 7-9")
        a = int(m.group(1))
        b = int(m.group(2) or a)
        if b < a:
            raise RuntimeError(
                f"У діапазоні «{part}» початок більший за кінець.")
        if a < 1 or b > n_pages:
            raise RuntimeError(
                f"Діапазон «{part}» поза межами документа (1-{n_pages}).")
        result.append((a, b))
    if not result:
        raise RuntimeError("Вкажіть хоча б один діапазон.")
    return result


def _label(a, b):
    return str(a) if a == b else f"{a}-{b}"


def _safe(name):
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", name).strip(" .")
    return name[:60] or "розділ"


def plan_split(doc, mode, param=None):
    """Повертає список (мітка, перша_сторінка, остання_сторінка), 1-based."""
    n = len(doc)
    if mode == MODE_EACH:
        return [(str(i), i, i) for i in range(1, n + 1)]
    if mode == MODE_EVERY_N:
        step = max(1, int(param or 1))
        return [(_label(a, min(a + step - 1, n)), a, min(a + step - 1, n))
                for a in range(1, n + 1, step)]
    if mode == MODE_RANGES:
        return [(_label(a, b), a, b) for a, b in parse_ranges(param, n)]
    if mode == MODE_BOOKMARKS:
        marks = [(t, p) for lvl, t, p in doc.get_toc(simple=True)
                 if lvl == 1 and 1 <= p <= n]
        if not marks:
            raise RuntimeError("У документі немає закладок верхнього рівня.")
        parts = []
        if marks[0][1] > 1:
            parts.append(("початок", 1, marks[0][1] - 1))
        for i, (title, start) in enumerate(marks):
            end = (marks[i + 1][1] - 1) if i + 1 < len(marks) else n
            end = max(end, start)
            parts.append((_safe(title), start, end))
        return parts
    raise RuntimeError("Невідомий режим розділення.")


def split_pdf(src, out_dir, mode, param=None, skip_existing=True,
              cancel_event=None):
    """Розділяє один PDF. Повертає (створені_файли, пропущено: bool)."""
    stem = os.path.splitext(os.path.basename(src))[0]
    with fitz.open(src) as doc:
        if doc.needs_pass:
            raise RuntimeError("файл захищено паролем")
        parts = plan_split(doc, mode, param)
        targets = [os.path.join(out_dir, f"{stem}_{label}.pdf")
                   for label, _a, _b in parts]
        if skip_existing and all(os.path.exists(t) for t in targets):
            return [], True
        used, created = set(), []
        for (label, a, b), target in zip(parts, targets):
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("Скасовано.")
            n = 1
            base, ext = os.path.splitext(target)
            while target in used or (not skip_existing and os.path.exists(target)):
                target = f"{base}_{n}{ext}"
                n += 1
            used.add(target)
            part = fitz.open()
            try:
                part.insert_pdf(doc, from_page=a - 1, to_page=b - 1)
                part.save(target, garbage=3, deflate=True)
            finally:
                part.close()
            created.append(target)
    return created, False
