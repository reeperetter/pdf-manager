from modules.pdf_translator.paragraphs import group_lines, join_paragraph, split_by_widths
from modules.pdf_translator.text_translation import translate_paragraphs


def L(text, x0, y0, x1, y1=None):
    return {"text": text, "bbox": (x0, y0, x1, y1 if y1 else y0 + 10)}


def test_body_paragraph_merged_and_toc_entries_kept_apart():
    lines = [
        L("The quick brown fox jumps over", 50, 100, 300),
        L("the lazy dog and keeps running", 50, 112, 298),
        L("until night.", 50, 124, 120),
        L("Next paragraph starts here.", 50, 150, 200),
        L("FRONT SEATS . . . . . 25", 50, 300, 300),
        L("REAR SEATS . . . . . 27", 50, 312, 300),
    ]
    assert group_lines(lines) == [[0, 1, 2], [3], [4], [5]]


def test_wrapped_caps_heading_merged_and_size_change_splits():
    wrapped = [L("SUPPLEMENTAL RESTRAINT SYSTEM", 50, 100, 300),
               L("AIR BAGS", 50, 112, 130)]
    assert group_lines(wrapped) == [[0, 1]]
    big = [L("INTRODUCTION", 50, 100, 300, 120), L("WELCOME TO FCA", 50, 122, 290, 132)]
    assert group_lines(big) == [[0], [1]]


def test_join_hyphenation_and_split_back():
    assert join_paragraph(["multi-", "function lever", "next"]) == "multifunction lever next"
    assert join_paragraph(["a", "b"]) == "a b"
    parts = split_by_widths("one two three four five six", [100, 100, 100])
    assert parts == ["one two", "three four", "five six"]
    assert split_by_widths("abc", [10]) == ["abc"]
    assert len(split_by_widths("single", [10, 10, 10])) == 3


def test_translate_paragraphs_keeps_line_count(monkeypatch):
    calls = []

    def fake(texts, glossary, **kw):
        calls.append(list(texts))
        return [t.upper() for t in texts]
    monkeypatch.setattr("modules.pdf_translator.text_translation.translate_with_glossary", fake)
    lines = [L("hello big", 0, 0, 100), L("world again", 0, 11, 100),
             L("Other.", 0, 100, 50)]
    out = translate_paragraphs(lines, [], target_lang="uk")
    assert calls == [["hello big world again", "Other."]]
    assert len(out) == 3 and out[0] + " " + out[1] == "HELLO BIG WORLD AGAIN" and out[2] == "OTHER."


def test_toc_wrapped_entry_and_font_size_boundary():
    def T(text, y0, x1, size, font):
        d = L(text, 36, y0, x1, y0 + 8)
        d.update(size=size, font=font)
        return d
    lines = [T("SIX-SPEED AUTOMATIC", 332, 110, 7.2, "Trade"),
             T("TRANSMISSION . . . . . . 39", 340, 176, 7.2, "Trade"),
             T("CUSTOMER ASSISTANCE", 408, 117, 9.0, "Gotham"),
             T("FCA US LLC CUSTOMER CENTER . . . 136", 420, 142, 7.2, "Trade")]
    assert group_lines(lines) == [[0, 1], [2], [3]]
