"""Переклад рядків: визначення мови, NLLB, глосарій."""
import re

from . import nllb
from .errors import ProcessingCancelled
from .languages import nllb_for


def detect_text_language(text):
    """Спроба визначити мову тексту локально без зовнішніх API."""
    if not text or len(text.strip()) < 3:
        return "en"

    try:
        from langdetect import detect
        lang = detect(text)
        return lang if lang else "en"
    except Exception:
        pass

    # Резервний аналіз за алфавітом
    has_cyrillic = any('\u0400' <= char <= '\u04FF' for char in text)
    if has_cyrillic:
        return "uk"
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
    if not actual_source or actual_source == "auto" or "+" in actual_source:
        sample = " ".join(l.strip() for l in lines_list if l.strip())[:600]
        actual_source = detect_text_language(sample)

    tgt = nllb_for(target_lang)
    src = nllb_for(actual_source)
    if not tgt:
        raise RuntimeError(f"Мова перекладу '{target_lang}' не підтримується.")
    if not src:
        if log_fn:
            log_fn(f"  [!] Мову оригіналу '{actual_source}' не розпізнано, "
                   "беру англійську.")
        src = nllb_for("en")

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
