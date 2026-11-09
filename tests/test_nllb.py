import hashlib
import http.server
import json
import os
import threading

import pytest

from modules.pdf_translator import nllb, pdf_pipeline as pp

REPO = nllb.MODEL_REPOS[0]


@pytest.fixture
def hf_server(monkeypatch, tmp_path):
    files = {"config.json": b"{}", "model.bin": os.urandom(300_000),
             "shared_vocabulary.json": b"[]"}

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path.startswith(f"/api/models/{REPO}"):
                sib = [{"rfilename": n, "size": len(b),
                        "lfs": {"sha256": hashlib.sha256(b).hexdigest()}
                        if n == "model.bin" else None} for n, b in files.items()]
                body = json.dumps({"siblings": sib}).encode()
            elif self.path.startswith(f"/{REPO}/resolve/main/"):
                body = files[self.path.rsplit("/", 1)[1]]
            elif self.path.endswith(nllb.SPM_NAME):
                body = b"spm"
            else:
                self.send_response(404)
                self.end_headers()
                return
            start = 0
            rng = self.headers.get("Range")
            if rng:
                start = int(rng.split("=")[1].split("-")[0])
                self.send_response(206)
            else:
                self.send_response(200)
            self.end_headers()
            self.wfile.write(body[start:])

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(nllb, "HF_ENDPOINT", f"http://127.0.0.1:{srv.server_port}")
    monkeypatch.setenv("PDFMANAGER_MODELS_DIR", str(tmp_path / "models"))
    yield files
    srv.shutdown()


def test_download_with_resume_and_checksum(hf_server):
    assert nllb.find_model() is None
    target = nllb.download_target()
    os.makedirs(target)
    with open(os.path.join(target, "model.bin.part"), "wb") as f:
        f.write(hf_server["model.bin"][:100_000])  # перерване завантаження
    progress = []
    path = nllb.download_model(lambda d, t, n: progress.append((d, t)))
    assert nllb.find_model() == path
    with open(os.path.join(path, "model.bin"), "rb") as f:
        assert f.read() == hf_server["model.bin"]
    assert progress[-1][0] <= progress[-1][1]


def test_checksum_mismatch_is_rejected(hf_server, monkeypatch):
    real = nllb._list_repo_files

    def bad(repo):
        return [(n, s, "0" * 64 if n == "model.bin" else h) for n, s, h in real(repo)]
    monkeypatch.setattr(nllb, "_list_repo_files", bad)
    with pytest.raises(nllb.ModelDownloadError):
        nllb.download_model()
    assert nllb.find_model() is None


def test_split_text_respects_limit():
    count = lambda t: len(t.split())
    text = " ".join(f"Sentence {i} is here." for i in range(100))
    parts = nllb.split_text(text, count, limit=50)
    assert all(count(p) <= 50 for p in parts)
    assert " ".join(parts) == text
    assert nllb.split_text("short", count) == ["short"]


class _SP:
    def encode(self, t, out_type=str):
        return t.split()

    def decode(self, toks):
        return " ".join(toks)


class _Res:
    def __init__(self, h):
        self.hypotheses = [h]


class _TR:
    def translate_batch(self, srcs, target_prefix, **kw):
        return [_Res([target_prefix[i][0]] + [w.upper() for w in s[1:-1]])
                for i, s in enumerate(srcs)]


@pytest.fixture
def fake_translator(monkeypatch):
    t = nllb.NllbTranslator.__new__(nllb.NllbTranslator)
    t.sp, t.tr, t._lock = _SP(), _TR(), threading.Lock()
    monkeypatch.setattr(nllb, "_translator", t)
    return t


def test_translate_keeps_symbols_and_empty(fake_translator):
    out = fake_translator.translate(["hello world", "123", "", "a b. c d"],
                                    "eng_Latn", "ukr_Cyrl")
    assert out == ["HELLO WORLD", "123", "", "A B. C D"]


def test_same_language_is_noop(fake_translator):
    assert fake_translator.translate(["x y"], "eng_Latn", "eng_Latn") == ["x y"]


def test_glossary_term_survives(fake_translator):
    r = pp.translate_with_glossary(["hello Acme world"], {"Acme"},
                                   target_lang="uk", source_lang="en")
    assert r == ["HELLO Acme WORLD"]


def test_detect_language_never_returns_unsupported_code():
    from modules.pdf_translator.languages import BY_ISO
    from modules.pdf_translator.text_translation import detect_text_language as d
    assert d("Доброго дня, це приклад українського тексту про їжу та ґанок") == "uk"
    assert d("Это пример русского текста, который содержит буквы ы и э") == "ru"
    assert d("The quick brown fox jumps over the lazy dog") == "en"
    assert d("Dies ist ein deutscher Satz über das Wetter und die Stadt") == "de"
    # македонська/сербська кирилиця без укр/рос літер не повинна давати
    # неіснуючий код (раніше це вело до підміни на англійську)
    assert d("Ова е пример на текст") in BY_ISO
    assert d("Ово је пример текста") in BY_ISO
    assert d("12345 67890") in BY_ISO


def test_unsupported_source_raises_instead_of_guessing(fake_translator):
    import pytest
    with pytest.raises(RuntimeError):
        pp.translate_lines(["x"], target_lang="uk", source_lang="xx")
