import os

import pymupdf
import pytest

from modules.common.outputs import resolve_output_path
from modules.pdf_compressor.compressor_core import compress_pdf_file, format_size
from modules.pdf_merge.merge_core import merge_pdfs, page_count
from modules.pdf_split import split_core as sc


def test_merge_adds_bookmarks(make_pdf, tmp_path):
    a, b = make_pdf("a.pdf", 2), make_pdf("b.pdf", 3)
    out = str(tmp_path / "m.pdf")
    merge_pdfs([a, b], out)
    assert page_count(out) == 5
    with pymupdf.open(out) as d:
        titles = [t for _l, t, _p in d.get_toc()]
    assert titles[:2] == ["a", "b"]


def test_merge_requires_files(tmp_path):
    with pytest.raises(RuntimeError):
        merge_pdfs([], str(tmp_path / "x.pdf"))


@pytest.mark.parametrize("text,n,expected", [
    ("1-3, 5", 6, [(1, 3), (5, 5)]),
    ("2", 2, [(2, 2)]),
])
def test_parse_ranges_ok(text, n, expected):
    assert sc.parse_ranges(text, n) == expected


@pytest.mark.parametrize("text", ["", "abc", "3-1", "0-2", "1-99"])
def test_parse_ranges_errors(text):
    with pytest.raises(RuntimeError):
        sc.parse_ranges(text, 5)


def test_split_modes(make_pdf, tmp_path):
    src = make_pdf("doc.pdf", 5, toc=[[1, "Intro", 1], [1, "Body", 3]])
    out = tmp_path / "out"
    out.mkdir()
    files, skipped = sc.split_pdf(src, str(out), sc.MODE_EACH)
    assert len(files) == 5 and not skipped
    _f, skipped = sc.split_pdf(src, str(out), sc.MODE_EACH)
    assert skipped  # усе вже є
    files, _ = sc.split_pdf(src, str(out), sc.MODE_EVERY_N, 2, skip_existing=False)
    assert [page_count(f) for f in files] == [2, 2, 1]
    files, _ = sc.split_pdf(src, str(out), sc.MODE_BOOKMARKS)
    assert [page_count(f) for f in files] == [2, 3]


def test_split_bookmarks_without_toc(make_pdf, tmp_path):
    with pytest.raises(RuntimeError):
        sc.split_pdf(make_pdf("n.pdf", 2), str(tmp_path), sc.MODE_BOOKMARKS)


def test_compress_roundtrip(make_pdf, tmp_path):
    src = make_pdf("c.pdf", 2)
    out = str(tmp_path / "c_out.pdf")
    original, new = compress_pdf_file(src, out)
    assert original > 0 and new > 0 and os.path.exists(out)
    assert page_count(out) == 2
    assert format_size(2048).startswith("2")


def test_resolve_output_path_collisions(tmp_path):
    used = set()
    first = resolve_output_path(str(tmp_path), "a.pdf", "_x", used, False)
    second = resolve_output_path(str(tmp_path), "a.pdf", "_x", used, False)
    assert first.endswith("a_x.pdf") and second.endswith("a_x_1.pdf")
    open(first, "w").close()
    assert resolve_output_path(str(tmp_path), "b.pdf", "_x", set(), True)
    assert resolve_output_path(str(tmp_path), "a.pdf", "_x", set(), True) is None
