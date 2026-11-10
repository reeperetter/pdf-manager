"""Переклад рядків: визначення мови, NLLB, глосарій."""
import re

from . import nllb
from .paragraphs import group_lines, join_paragraph, split_by_widths
from .errors import ProcessingCancelled
from .languages import BY_ISO, nllb_for


_UK_LETTERS = set("іїєґІЇЄҐ")
_RU_LETTERS = set("ыэъёЫЭЪЁ")


def detect_text_language(text):
    """Визначає мову тексту локально, лише серед мов, які ми вміємо
    перекладати (реєстр languages.py).

    Раніше брався перший результат langdetect: для української він часто
    повертав 'mk', 'sr', 'be' тощо - таких мов у реєстрі немає, і код
    підмінявся англійським. Модель отримувала кириличний текст із позначкою
    'англійська' і лише копіювала/транслітерувала слова. Тепер:
      1) українська/російська розрізняються за характерними літерами;
      2) з розподілу ймовірностей langdetect береться найкраща ПІДТРИМУВАНА
         мова;
      3) якщо нічого не підійшло - за алфавітом (кирилиця -> uk, грецька
         -> el, інакше en)."""
    if not text or len(text.strip()) < 3:
        return "en"

    uk = sum(1 for ch in text if ch in _UK_LETTERS)
    ru = sum(1 for ch in text if ch in _RU_LETTERS)
    if uk > ru:
        return "uk"
    if ru > uk:
        return "ru"

    try:
        from langdetect import DetectorFactory, detect_langs
        DetectorFactory.seed = 0  # однаковий результат при кожному запуску
        for cand in detect_langs(text):
            if cand.lang in BY_ISO:
                return cand.lang
    except Exception:
        pass

    if any("\u0400" <= ch <= "\u04FF" for ch in text):
        return "uk"
    if any("\u0370" <= ch <= "\u03FF" for ch in text):
        return "el"
    return "en"


def translate_lines(lines_list, target_lang="uk", source_lang="auto", log_fn=None, cancel_event=None):
    """Офлайн-переклад рядків моделлю NLLB-200.

    source_lang: 'auto', код Tesseract ('ukr'), ISO ('uk') або комбінація
    ('ukr+eng') - у двох останніх випадках мову визначаємо локально за
    текстом. Повертає список тієї ж довжини; порожні рядки лишаються
    порожніми.
    """
    if not lines_list:
        return []
    if cancel_event and cancel_event.is_set():
        raise ProcessingCancelled()

    actual_source = source_lang
    auto = not actual_source or actual_source == "auto" or "+" in actual_source
    if auto:
        sample = " ".join(l.strip() for l in lines_list if l.strip())[:3000]
        actual_source = detect_text_language(sample)

    tgt = nllb_for(target_lang)
    src = nllb_for(actual_source)
    if not tgt:
        raise RuntimeError(f"Мова перекладу '{target_lang}' не підтримується.")
    if not src:
        raise RuntimeError(
            f"Мову оригіналу '{actual_source}' не підтримує переклад. "
            "Оберіть її вручну у списку «Мова оригіналу».")
    if log_fn:
        log_fn(f"  Переклад: {src} -> {tgt}"
               + (" (мову оригіналу визначено автоматично)" if auto else ""))

    return nllb.get_translator().translate(
        lines_list, src, tgt, cancel_event=cancel_event)



def translate_with_glossary(texts, glossary, **kwargs):
    """Переклад із глосарієм: терміни зі списку залишаються без змін.

    Перед відправкою в перекладач кожен термін (без урахування регістру, як
    окреме слово/фразу) підміняється нейтральним маркером QZX<n>QZ, який
    модель зазвичай не чіпає, а після отримання перекладу маркер
    замінюється назад на оригінальний фрагмент. Рядок, де модель маркер
    зіпсувала, перекладається ще раз без захисту (глосарій у ньому тоді
    не гарантується), а якщо рядок складається лише з терміна, він
    лишається як є.
    """
    terms = sorted({t.strip() for t in (glossary or ()) if t and t.strip()},
                   key=len, reverse=True)
    if not terms:
        return translate_lines(texts, **kwargs)

    pattern = re.compile(
        r"(?<!\w)(?:" + "|".join(re.escape(t) for t in terms) + r")(?!\w)",
        re.IGNORECASE)

    protected, originals = [], []
    for text in texts:
        found = []

        def _sub(m, found=found):
            found.append(m.group(0))
            return f"QZX{len(found) - 1}QZ"

        protected.append(pattern.sub(_sub, text))
        originals.append(found)

    translated = translate_lines(protected, **kwargs)

    result, retry = [], []
    for n, (text, tr, found) in enumerate(zip(texts, translated, originals)):
        if not found:
            result.append(tr)
            continue
        tr = tr or ""
        ok = all(re.search(rf"QZX{i}QZ", tr, re.IGNORECASE)
                 for i in range(len(found)))
        if not ok:
            result.append(text)
            retry.append(n)
            continue
        for i, original in enumerate(found):
            tr = re.sub(rf"QZX{i}QZ", lambda _m, o=original: o, tr,
                        flags=re.IGNORECASE)
        result.append(tr)

    # Рядки зі зіпсованими маркерами: переклад без захисту термінів, крім
    # випадку, коли весь рядок і є терміном.
    retry = [n for n in retry
             if not pattern.fullmatch(texts[n].strip())]
    if retry:
        again = translate_lines([texts[n] for n in retry], **kwargs)
        for n, tr in zip(retry, again):
            result[n] = tr
    return result


def translate_paragraphs(lines, glossary, **kwargs):
    """Переклад рядків сторінки з урахуванням абзаців: сусідні рядки одного
    абзацу перекладаються разом, а результат розкладається назад по
    оригінальних рядках. Повертає список тієї ж довжини, що й lines."""
    groups = group_lines(lines)
    joined = [join_paragraph([lines[i]["text"] for i in g]) for g in groups]
    translated = translate_with_glossary(joined, glossary, **kwargs)

    result = [""] * len(lines)
    for g, text in zip(groups, translated):
        if len(g) == 1:
            result[g[0]] = text
            continue
        widths = [max(lines[i]["bbox"][2] - lines[i]["bbox"][0], 1e-6) for i in g]
        for i, piece in zip(g, split_by_widths(text or "", widths)):
            result[i] = piece
    return result
