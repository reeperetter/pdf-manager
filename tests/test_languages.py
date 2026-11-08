from modules.pdf_translator.languages import BY_ISO, BY_TESS, LANGUAGES, nllb_for


def test_registry_is_consistent():
    assert len(LANGUAGES) == 21
    assert len({l.iso for l in LANGUAGES}) == len(LANGUAGES)
    assert len({l.tess for l in LANGUAGES}) == len(LANGUAGES)
    assert len({l.nllb for l in LANGUAGES}) == len(LANGUAGES)
    for l in LANGUAGES:
        assert "_" in l.nllb and l.name


def test_nllb_for_accepts_iso_tess_and_unknown():
    assert nllb_for("uk") == "ukr_Cyrl"
    assert nllb_for("ukr") == "ukr_Cyrl"
    assert nllb_for("en") == "eng_Latn"
    assert nllb_for("xx") is None
    assert BY_ISO["uk"] is BY_TESS["ukr"]
