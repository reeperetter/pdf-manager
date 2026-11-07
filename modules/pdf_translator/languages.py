"""
Єдиний реєстр мов для розпізнавання (Tesseract) і перекладу (NLLB-200).

Додати нову мову = додати один рядок у LANGUAGES. Потрібно знати:
  iso     - двобуквений код (langdetect);
  tess    - код мовної моделі Tesseract (<tess>.traineddata);
  nllb    - код мови моделі NLLB-200 (напр. ukr_Cyrl);
  name    - назва мови (називний відмінок) - для списку "Мова оригіналу";
  target  - назва в знахідному відмінку - для "Перекласти на: ...".
Усі мови нижче мають шрифт DejaVu Sans (латиниця, кирилиця, грецька).
Китайська/японська/корейська/арабська не підтримані: потрібен інший шрифт.
"""
from collections import namedtuple

Lang = namedtuple("Lang", "iso tess nllb name target")

LANGUAGES = [
    Lang("uk", "ukr", "ukr_Cyrl", "Українська", "Українську"),
    Lang("en", "eng", "eng_Latn", "Англійська", "Англійську"),
    Lang("ru", "rus", "rus_Cyrl", "Російська", "Російську"),
    Lang("pl", "pol", "pol_Latn", "Польська", "Польську"),
    Lang("de", "deu", "deu_Latn", "Німецька", "Німецьку"),
    Lang("fr", "fra", "fra_Latn", "Французька", "Французьку"),
    Lang("es", "spa", "spa_Latn", "Іспанська", "Іспанську"),
    Lang("it", "ita", "ita_Latn", "Італійська", "Італійську"),
    Lang("pt", "por", "por_Latn", "Португальська", "Португальську"),
    Lang("cs", "ces", "ces_Latn", "Чеська", "Чеську"),
    Lang("sk", "slk", "slk_Latn", "Словацька", "Словацьку"),
    Lang("bg", "bul", "bul_Cyrl", "Болгарська", "Болгарську"),
    Lang("ro", "ron", "ron_Latn", "Румунська", "Румунську"),
    Lang("hu", "hun", "hun_Latn", "Угорська", "Угорську"),
    Lang("nl", "nld", "nld_Latn", "Нідерландська", "Нідерландську"),
    Lang("sv", "swe", "swe_Latn", "Шведська", "Шведську"),
    Lang("tr", "tur", "tur_Latn", "Турецька", "Турецьку"),
    Lang("lt", "lit", "lit_Latn", "Литовська", "Литовську"),
    Lang("lv", "lav", "lvs_Latn", "Латиська", "Латиську"),
    Lang("et", "est", "est_Latn", "Естонська", "Естонську"),
    Lang("el", "ell", "ell_Grek", "Грецька", "Грецьку"),
]

# Три найпопулярніші - окремими прапорцями у вкладці перекладу.
MAIN_TARGETS = ["uk", "ru", "en"]

BY_ISO = {l.iso: l for l in LANGUAGES}
BY_TESS = {l.tess: l for l in LANGUAGES}

# Додаткові синоніми кодів (старі/альтернативні).
_ALIASES = {"ger": "de", "fre": "fr", "ces": "cs", "cze": "cs",
            "slo": "sk", "rum": "ro", "dut": "nl", "gre": "el"}


def nllb_for(code):
    """Код NLLB для ISO-коду, коду Tesseract або None."""
    if not code:
        return None
    code = _ALIASES.get(code, code)
    lang = BY_ISO.get(code) or BY_TESS.get(code)
    return lang.nllb if lang else None


def target_name(iso):
    lang = BY_ISO.get(iso)
    return lang.target if lang else iso
