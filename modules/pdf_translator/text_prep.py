"""Підготовка рядка до машинного перекладу й відновлення після нього.

Прикладом став зміст посібника, де заголовки ВЕЛИКИМИ ЛІТЕРАМИ і крапкові
виносні "......  47". NLLB (як і більшість MT-моделей) тренувався на тексті
звичайного регістру: слова у КАПСІ розбиваються на рідкісні фрагменти, і
модель замість перекладу транслітерує ("DRIVER COCKPIT" -> "ДРИВЕР
СКОКПИТ", "MULTIFUNCTION LEVER" -> "МУРТФУКЦИОННЫЙ ЛЕВЕР"). Крапки й
номери сторінок теж заважають. Тому:

  prepare(text) -> (текст для моделі, finish)
    1) відрізає хвіст "  . . . . 47" (виносні + номер сторінки);
    2) якщо рядок майже весь у верхньому регістрі - переводить слова (крім
       абревіатур SRS, CVT, USB) у нижній, перша
       літера велика;
  finish(переклад) -> повертає верхній регістр (якщо був) і хвіст.
"""
import re

_LEADER_TAIL = re.compile(r"^(?P<core>.*?\S)(?P<tail>\s*(?:\.\s*){2,}\s*\d*\s*)$", re.S)
_WORD = re.compile(r"[^\W\d_]+")
_CAPS_RATIO = 0.85
_KEEP_UPPER_LEN = 2
# Абревіатури з голосними, які не слід перетворювати на звичайні слова
# (SRS, CVT, ATC, LLC без голосних і так лишаються).
_ACRONYMS = {"FCA", "USB", "AUX", "GPS", "LED", "ABS", "ESC", "SUV", "TPMS",
             "EVIC", "DVD", "USA", "UAE", "EU", "UK", "FM", "AM", "TV", "CD"}
_VOWELS = set("AEIOUYАЕЄИІЇОУЮЯЭЫ")


def _is_regular_word(w):
    """Слово, яке в капсі слід перетворити на звичайне (не абревіатура)."""
    if len(w) <= _KEEP_UPPER_LEN or w.upper() in _ACRONYMS:
        return False
    return any(ch in _VOWELS for ch in w.upper())


def _is_caps(text):
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 4:
        return False
    upper = sum(1 for c in letters if c.isupper())
    has_long_word = any(_is_regular_word(w) for w in _WORD.findall(text))
    return has_long_word and upper / len(letters) >= _CAPS_RATIO


def _decaps(text):
    def fix(m):
        w = m.group(0)
        return w.lower() if _is_regular_word(w) else w
    out = _WORD.sub(fix, text)
    for i, c in enumerate(out):
        if c.isalpha():
            return out[:i] + c.upper() + out[i + 1:]
    return out


_DASHES = re.compile(r"\s*[\u2012\u2013\u2014\u2015]\s*")


def prepare(text):
    # Довге тире немає в словнику NLLB: модель повертає "⁇" - міняємо на дефіс.
    text = _DASHES.sub(" - ", text)
    tail = ""
    core = text
    m = _LEADER_TAIL.match(text)
    if m:
        core, tail = m.group("core"), m.group("tail")
    caps = _is_caps(core)
    if caps:
        core = _decaps(core)

    def finish(translated):
        translated = re.sub(r"\s*\u2047\s*", " ", translated).strip()  # невідомі символи
        result = translated.upper() if caps else translated
        return result + tail

    return core, finish
