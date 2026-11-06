"""
Єдиний реєстр мов для розпізнавання (Tesseract) і перекладу (MyMemory).

Додати нову мову = додати один рядок у LANGUAGES. Потрібно знати:
  iso     - двобуквений код (langdetect, DeepL);
  tess    - код мовної моделі Tesseract (<tess>.traineddata);
  locale  - повна локаль для MyMemory;
  name    - назва мови (називний відмінок) - для списку "Мова оригіналу";
  target  - назва в знахідному відмінку - для "Перекласти на: ...".
Усі мови нижче мають шрифт DejaVu Sans (латиниця, кирилиця, грецька).
Китайська/японська/корейська/арабська не підтримані: потрібен інший шрифт.
"""
from collections import namedtuple

Lang = namedtuple("Lang", "iso tess locale name target")

LANGUAGES = [
    Lang("uk", "ukr", "uk-UA", "Українська", "Українську"),
    Lang("en", "eng", "en-US", "Англійська", "Англійську"),
    Lang("ru", "rus", "ru-RU", "Російська", "Російську"),
    Lang("pl", "pol", "pl-PL", "Польська", "Польську"),
    Lang("de", "deu", "de-DE", "Німецька", "Німецьку"),
    Lang("fr", "fra", "fr-FR", "Французька", "Французьку"),
    Lang("es", "spa", "es-ES", "Іспанська", "Іспанську"),
    Lang("it", "ita", "it-IT", "Італійська", "Італійську"),
    Lang("pt", "por", "pt-PT", "Португальська", "Португальську"),
    Lang("cs", "ces", "cs-CZ", "Чеська", "Чеську"),
    Lang("sk", "slk", "sk-SK", "Словацька", "Словацьку"),
    Lang("bg", "bul", "bg-BG", "Болгарська", "Болгарську"),
    Lang("ro", "ron", "ro-RO", "Румунська", "Румунську"),
    Lang("hu", "hun", "hu-HU", "Угорська", "Угорську"),
    Lang("nl", "nld", "nl-NL", "Нідерландська", "Нідерландську"),
    Lang("sv", "swe", "sv-SE", "Шведська", "Шведську"),
    Lang("tr", "tur", "tr-TR", "Турецька", "Турецьку"),
    Lang("lt", "lit", "lt-LT", "Литовська", "Литовську"),
    Lang("lv", "lav", "lv-LV", "Латиська", "Латиську"),
    Lang("et", "est", "et-EE", "Естонська", "Естонську"),
    Lang("el", "ell", "el-GR", "Грецька", "Грецьку"),
]

# Три найпопулярніші - окремими прапорцями у вкладці перекладу.
MAIN_TARGETS = ["uk", "ru", "en"]

BY_ISO = {l.iso: l for l in LANGUAGES}
BY_TESS = {l.tess: l for l in LANGUAGES}

# Додаткові синоніми кодів (старі/альтернативні).
_ALIASES = {"ger": "de", "fre": "fr", "ces": "cs", "cze": "cs",
            "slo": "sk", "rum": "ro", "dut": "nl", "gre": "el"}


def locale_for(code):
    """Локаль MyMemory для ISO-коду, коду Tesseract або None."""
    if not code:
        return None
    code = _ALIASES.get(code, code)
    lang = BY_ISO.get(code) or BY_TESS.get(code)
    return lang.locale if lang else None


def target_name(iso):
    lang = BY_ISO.get(iso)
    return lang.target if lang else iso
