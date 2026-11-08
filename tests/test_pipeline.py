import io

import pymupdf
from PIL import Image

from modules.pdf_translator import pdf_pipeline as pp
from modules.pdf_translator import text_translation


def _scan_pdf(path, dpi):
    px = int(8.27 * dpi), int(11.69 * dpi)
    buf = io.BytesIO()
    Image.new("L", px, 255).save(buf, "PNG")
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(page.rect, stream=buf.getvalue())
    doc.save(path)
    doc.close()


def test_render_dpi_follows_scan_resolution(tmp_path, make_pdf):
    scan = str(tmp_path / "s.pdf")
    _scan_pdf(scan, 300)
    with pymupdf.open(scan) as d:
        assert 300 <= pp.page_render_dpi(d[0], 600) <= 310
    low = str(tmp_path / "l.pdf")
    _scan_pdf(low, 100)
    with pymupdf.open(low) as d:
        assert pp.page_render_dpi(d[0], 600) == pp.MIN_RENDER_DPI
    with pymupdf.open(make_pdf("v.pdf", 1)) as d:
        assert pp.page_render_dpi(d[0], 600) == 600  # вектор - як раніше


def test_render_dpi_is_capped(tmp_path):
    hi = str(tmp_path / "h.pdf")
    _scan_pdf(hi, 900)
    with pymupdf.open(hi) as d:
        assert pp.page_render_dpi(d[0], 600) == 600


def test_extract_lines_from_text_layer(make_pdf):
    with pymupdf.open(make_pdf("t.pdf", 1)) as d:
        lines = pp.extract_lines_from_page(d[0])
    assert lines and lines[0]["text"] == "Page 1"


def test_glossary_retry_when_marker_lost(monkeypatch):
    calls = []

    def fake(texts, **kw):
        calls.append(list(texts))
        # перший виклик "ламає" маркер, повторний (без захисту) - ні
        return [t.replace("QZX0QZ", "") if "QZX0QZ" in t else t.upper()
                for t in texts]
    monkeypatch.setattr(text_translation, "translate_lines", fake)
    r = pp.translate_with_glossary(["say Acme now"], {"Acme"},
                                   target_lang="uk", source_lang="en")
    assert r == ["SAY ACME NOW"] and len(calls) == 2
