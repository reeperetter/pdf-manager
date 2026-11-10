"""Склеювання рядків OCR в абзаци перед перекладом.

OCR і текстовий шар віддають текст по рядках, а переклад якісніший, коли
модель бачить цілу фразу: заголовок, розірваний на два рядки ("SUPPLEMENTAL
RESTRAINT SYSTEM" / "(SRS)"), чи абзац тексту, перекладений по шматках,
дають помилки. Тому:

  group_lines(lines)             -> [[індекси рядків одного абзацу], ...]
  join_paragraph(texts)          -> один рядок (з переносами слів)
  split_by_widths(text, widths)  -> розкладає переклад назад по рядках
                                    пропорційно їхній ширині

Сторінка малюється як і раніше - рядок за рядком, у рамках оригінальних
прямокутників, тож розмітка не змінюється.
"""
import re

# Рядок завершує абзац: кінцева пунктуація або виносні "...... 47".
_TERMINAL = re.compile(r"(?:[.!?…:;]\s*$)|(?:(?:\.\s*){2,}\s*\d*\s*$)")
_LEADER_END = re.compile(r"(?:\.\s*){2,}\s*\d*\s*$")
_TRAILING_PAGE_NO = re.compile(r"\s\d{1,3}\s*$")


def _is_caps(text):
    letters = [c for c in text if c.isalpha()]
    return len(letters) >= 4 and sum(c.isupper() for c in letters) / len(letters) >= 0.85


def _has_letters(text):
    return any(c.isalpha() for c in text)


def _ends_paragraph(text):
    t = text.rstrip()
    if _TERMINAL.search(t):
        return True
    return _is_caps(t) and bool(_TRAILING_PAGE_NO.search(t))


def _geometry_ok(a, b, caps):
    ax0, ay0, ax1, ay1 = a["bbox"]
    bx0, by0, bx1, by1 = b["bbox"]
    ha, hb = ay1 - ay0, by1 - by0
    if ha <= 0 or hb <= 0:
        return False
    sa, sb = a.get("size"), b.get("size")
    if sa and sb:  # текстовий шар: розмір і гарнітура шрифту мають збігатися
        if abs(sa - sb) > 0.05 * max(sa, sb) or a.get("font") != b.get("font"):
            return False
    else:  # OCR: орієнтуємось на висоту рядка
        lo, hi = (0.9, 1.11) if caps else (0.8, 1.25)
        if not lo <= hb / ha <= hi:
            return False
    h = max(ha, hb)
    gap = by0 - ay1
    if gap < -0.3 * h or gap > 0.7 * h or by0 < ay0:
        return False
    return abs(bx0 - ax0) <= 2 * h and bx0 < ax1


def group_lines(lines):
    """Повертає список груп індексів (у порядку читання, як у lines)."""
    n = len(lines)
    texts = [(ln["text"] or "").strip() for ln in lines]
    # 1) геометричні ланцюжки сусідніх рядків
    chains, cur = [], [0] if n else []
    for i in range(1, n):
        a, b = i - 1, i
        caps = _is_caps(texts[a]) and _is_caps(texts[b])
        if (_has_letters(texts[a]) and _has_letters(texts[b])
                and not _ends_paragraph(texts[a])
                and _geometry_ok(lines[a], lines[b], caps)):
            cur.append(i)
        else:
            chains.append(cur)
            cur = [i]
    if cur:
        chains.append(cur)

    # 2) усередині ланцюжка: зливаємо, якщо рядок "повний" (дотягується до
    # правого краю абзацу) або наступний починається з малої літери
    groups = []
    for chain in chains:
        left = min(lines[i]["bbox"][0] for i in chain)
        right = max(lines[i]["bbox"][2] for i in chain)
        span = max(right - left, 1e-6)
        group = [chain[0]]
        for prev, nxt in zip(chain, chain[1:]):
            full = lines[prev]["bbox"][2] >= right - 0.08 * span
            lower = texts[nxt][:1].islower()
            # продовження заголовка, що закінчується виносною: "SIX-SPEED
            # AUTOMATIC" / "TRANSMISSION . . . 39"
            finishes_entry = bool(_LEADER_END.search(texts[nxt]))
            if full or lower or finishes_entry:
                group.append(nxt)
            else:
                groups.append(group)
                group = [nxt]
        groups.append(group)
    return groups


def join_paragraph(texts):
    out = ""
    for t in (x.strip() for x in texts):
        if not t:
            continue
        if not out:
            out = t
        elif out.endswith("-") and t[:1].islower() and out[-2:-1].isalpha():
            out = out[:-1] + t  # перенесене слово
        else:
            out += " " + t
    return out


def split_by_widths(text, widths):
    """Ділить текст на len(widths) частин за словами, пропорційно ширинам."""
    n = len(widths)
    words = text.split()
    if n == 1:
        return [text.strip()]
    parts = [[] for _ in range(n)]
    total_w = float(sum(widths)) or float(n)
    total_c = sum(len(w) + 1 for w in words) or 1
    cum_w, used, line = 0.0, 0, 0
    for w in words:
        # границя поточного рядка в символах
        limit = total_c * (cum_w + widths[line]) / total_w
        if line < n - 1 and parts[line] and used + (len(w) + 1) / 2 > limit:
            cum_w += widths[line]
            line += 1
        parts[line].append(w)
        used += len(w) + 1
    return [" ".join(p) for p in parts]
