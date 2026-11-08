"""
Офлайн-переклад моделлю NLLB-200 (distilled, 600M) через CTranslate2.

Жодного тексту документа назовні не йде: інтернет потрібен лише один раз -
щоб завантажити файли моделі (~600 МБ, int8). Ліміту символів немає.

Де лежить модель
----------------
Модель зберігається в теці ``models/nllb-200-600m`` ПОРЯД ІЗ ЗБІРКОЮ
(поруч із PDFManager.exe або з main.py), тож програма лишається
портативною і не пише у профіль користувача. Якщо ця тека недоступна для
запису (наприклад, програма лежить у Program Files, а в користувача
обмежені права), модель кладеться в теку даних користувача
(%LOCALAPPDATA%\\PDFManager\\models або ~/.local/share/PDFManager/models).
Теку можна задати вручну змінною середовища PDFMANAGER_MODELS_DIR.
Модель можна й просто скопіювати в одну з цих тек (вручну, з іншого
комп'ютера) - програма знайде її без завантаження.

Файли беруться з HuggingFace (адресу можна замінити змінною
PDFMANAGER_HF_ENDPOINT, наприклад на дзеркало).
Увага: ваги NLLB-200 поширюються за ліцензією CC-BY-NC 4.0
(некомерційна) - перевірте її перед комерційним використанням.
"""
import hashlib
import json
import os
import re
import sys
import tempfile
import threading
import urllib.request

# Репозиторії з готовою конвертацією CTranslate2 (int8). Пробуємо по черзі.
MODEL_REPOS = [
    "JustFrederik/nllb-200-distilled-600M-ct2-int8",
    "winstxnhdw/nllb-200-distilled-600M-ct2-int8",
]
# Токенізатор (SentencePiece), якщо його немає в репозиторії конвертації.
TOKENIZER_REPO = "facebook/nllb-200-distilled-600M"
SPM_NAME = "sentencepiece.bpe.model"
MODEL_SUBDIR = "nllb-200-600m"
APPROX_SIZE_MB = 600

HF_ENDPOINT = os.environ.get(
    "PDFMANAGER_HF_ENDPOINT", "https://huggingface.co").rstrip("/")

# Максимум токенів в одному сегменті (NLLB тренувався на реченнях; ліміт
# моделі - 512, беремо із запасом).
MAX_SEGMENT_TOKENS = 200
BATCH_SIZE = 16

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))


class ModelDownloadError(Exception):
    pass


class DownloadCancelled(Exception):
    pass


# --------------------------------------------------------------- теки --
def app_dir():
    """Тека збірки: поруч із exe (PyInstaller) або корінь репозиторію."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return _PROJECT_ROOT


def user_data_dir():
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser(
            r"~\AppData\Local")
        return os.path.join(base, "PDFManager")
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser(
        "~/.local/share")
    return os.path.join(base, "PDFManager")


def candidate_roots():
    """Теки 'models' у порядку пріоритету."""
    roots = []
    env = os.environ.get("PDFMANAGER_MODELS_DIR")
    if env:
        roots.append(env)
    roots.append(os.path.join(app_dir(), "models"))
    roots.append(os.path.join(user_data_dir(), "models"))
    seen, result = set(), []
    for r in roots:
        r = os.path.abspath(r)
        if r not in seen:
            seen.add(r)
            result.append(r)
    return result


def _is_writable(directory):
    try:
        os.makedirs(directory, exist_ok=True)
        fd, probe = tempfile.mkstemp(dir=directory, prefix=".w")
        os.close(fd)
        os.remove(probe)
        return True
    except OSError:
        return False


def _complete(path):
    """Тека містить повну модель (є мітка успішного завантаження)."""
    if not os.path.isdir(path):
        return False
    names = os.listdir(path)
    has_vocab = any(n.startswith("shared_vocabulary") for n in names)
    return (os.path.isfile(os.path.join(path, "model.bin"))
            and os.path.isfile(os.path.join(path, "config.json"))
            and os.path.isfile(os.path.join(path, SPM_NAME))
            and has_vocab
            and (os.path.isfile(os.path.join(path, ".complete"))
                 or not os.path.isfile(os.path.join(path, "model.bin.part"))))


def find_model():
    """Шлях до готової моделі або None."""
    for root in candidate_roots():
        path = os.path.join(root, MODEL_SUBDIR)
        if _complete(path):
            return path
    return None


def download_target():
    """Куди качати: перша тека зі списку, у яку можна писати."""
    for root in candidate_roots():
        if _is_writable(root):
            return os.path.join(root, MODEL_SUBDIR)
    raise ModelDownloadError(
        "Немає теки, у яку можна записати модель. Задайте її змінною "
        "середовища PDFMANAGER_MODELS_DIR.")


# --------------------------------------------------------- завантаження --
def _http_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "PDFManager"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _list_repo_files(repo):
    """[(name, size, sha256|None)] потрібних файлів репозиторію."""
    info = _http_json(f"{HF_ENDPOINT}/api/models/{repo}?blobs=true")
    wanted = []
    for s in info.get("siblings", []):
        name = s.get("rfilename", "")
        if "/" in name:
            continue
        if (name in ("config.json", "model.bin", SPM_NAME)
                or name.startswith("shared_vocabulary")):
            sha = (s.get("lfs") or {}).get("sha256")
            wanted.append((name, s.get("size") or 0, sha))
    names = {w[0] for w in wanted}
    if "model.bin" not in names or "config.json" not in names:
        raise ModelDownloadError(f"У репозиторії {repo} немає файлів моделі.")
    return wanted


def _download_file(url, dest, expected_size, sha256, on_bytes, cancel_event):
    part = dest + ".part"
    start = os.path.getsize(part) if os.path.isfile(part) else 0
    headers = {"User-Agent": "PDFManager"}
    if start:
        headers["Range"] = f"bytes={start}-"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as r:
        if start and r.status != 206:
            start = 0  # сервер не підтримує докачування
        mode = "ab" if start else "wb"
        with open(part, mode) as f:
            on_bytes(start)
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise DownloadCancelled()
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                on_bytes(len(chunk))
    size = os.path.getsize(part)
    if expected_size and size != expected_size:
        os.remove(part)
        raise ModelDownloadError(
            f"{os.path.basename(dest)}: розмір {size} замість {expected_size} "
            "байт. Спробуйте ще раз.")
    if sha256:
        h = hashlib.sha256()
        with open(part, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        if h.hexdigest() != sha256:
            os.remove(part)
            raise ModelDownloadError(
                f"{os.path.basename(dest)}: контрольна сума не збігається. "
                "Спробуйте ще раз.")
    os.replace(part, dest)


def download_model(progress_cb=None, cancel_event=None):
    """Завантажує модель у download_target(). progress_cb(done, total, text).
    Докачує перервані завантаження. Повертає шлях до теки моделі."""
    target = download_target()
    os.makedirs(target, exist_ok=True)

    last_err = None
    files, repo = None, None
    for r in MODEL_REPOS:
        try:
            files = _list_repo_files(r)
            repo = r
            break
        except Exception as e:  # мережа, 404, дивний формат
            last_err = e
    if files is None:
        raise ModelDownloadError(
            f"Не вдалося отримати список файлів моделі ({last_err}). "
            "Перевірте інтернет або скопіюйте модель вручну в "
            f"{target}")

    jobs = [(f"{HF_ENDPOINT}/{repo}/resolve/main/{n}", n, size, sha)
            for n, size, sha in files]
    if not any(n == SPM_NAME for _, n, _, _ in jobs):
        jobs.append((f"{HF_ENDPOINT}/{TOKENIZER_REPO}/resolve/main/{SPM_NAME}",
                     SPM_NAME, 0, None))

    # Розмір токенізатора (~5 МБ) невідомий наперед - беремо з запасом.
    total = sum(j[2] or 6_000_000 for j in jobs)
    done = [0]
    marker = os.path.join(target, ".complete")
    if os.path.isfile(marker):
        os.remove(marker)

    for url, name, size, sha in jobs:
        dest = os.path.join(target, name)
        if os.path.isfile(dest) and (not size or os.path.getsize(dest) == size):
            done[0] += os.path.getsize(dest)
            continue

        def on_bytes(n, name=name):
            done[0] += n
            if progress_cb:
                progress_cb(min(done[0], total), total, name)

        try:
            _download_file(url, dest, size, sha, on_bytes, cancel_event)
        except (DownloadCancelled, ModelDownloadError):
            raise
        except Exception as e:
            raise ModelDownloadError(f"{name}: {e}") from e
    with open(marker, "w", encoding="utf-8") as f:
        f.write(repo)
    return target


# ------------------------------------------------------------ сегменти --
_SENT_SPLIT = re.compile(r"(?<=[.!?…;:])\s+")


def split_text(text, count_tokens, limit=MAX_SEGMENT_TOKENS):
    """Ділить довгий рядок на частини <= limit токенів: за реченнями, а якщо
    речення задовге - за словами. Короткий рядок лишається одним сегментом."""
    if count_tokens(text) <= limit:
        return [text]
    parts, cur = [], ""
    for sent in _SENT_SPLIT.split(text):
        for piece in _split_long(sent, count_tokens, limit):
            candidate = f"{cur} {piece}".strip() if cur else piece
            if cur and count_tokens(candidate) > limit:
                parts.append(cur)
                cur = piece
            else:
                cur = candidate
    if cur:
        parts.append(cur)
    return parts


def _split_long(sentence, count_tokens, limit):
    if count_tokens(sentence) <= limit:
        return [sentence]
    out, cur = [], ""
    for word in sentence.split():
        candidate = f"{cur} {word}".strip()
        if cur and count_tokens(candidate) > limit:
            out.append(cur)
            cur = word
        else:
            cur = candidate
    if cur:
        out.append(cur)
    return out


def _has_letters(s):
    return any(ch.isalpha() for ch in s)


# -------------------------------------------------------------- рушій --
class NllbTranslator:
    """Обгортка CTranslate2 + SentencePiece. Створювати через get_translator()."""

    def __init__(self, model_path, threads=None):
        import ctranslate2
        import sentencepiece as spm

        self.sp = spm.SentencePieceProcessor()
        self.sp.load(os.path.join(model_path, SPM_NAME))
        threads = threads or min(os.cpu_count() or 2, 8)
        self.tr = ctranslate2.Translator(
            model_path, device="cpu", compute_type="int8",
            inter_threads=1, intra_threads=threads)
        self._lock = threading.Lock()

    def _count(self, text):
        return len(self.sp.encode(text, out_type=str))

    def translate(self, texts, src, tgt, cancel_event=None):
        """texts: список рядків; src/tgt: коди NLLB (напр. 'ukr_Cyrl').
        Повертає список перекладів тієї ж довжини. Рядки без літер
        (номери, розділювачі) повертаються без змін."""
        result = list(texts)
        if src == tgt:
            return result

        segments = []  # (індекс рядка, частина, токени)
        for i, text in enumerate(texts):
            t = (text or "").strip()
            if not t or not _has_letters(t):
                continue
            for part in split_text(t, self._count):
                segments.append(
                    (i, part, [src] + self.sp.encode(part, out_type=str) + ["</s>"]))
        if not segments:
            return result

        order = sorted(range(len(segments)), key=lambda k: len(segments[k][2]))
        translated = {}
        with self._lock:
            for b in range(0, len(order), BATCH_SIZE):
                if cancel_event is not None and cancel_event.is_set():
                    from .errors import ProcessingCancelled
                    raise ProcessingCancelled()
                idx = order[b:b + BATCH_SIZE]
                outs = self.tr.translate_batch(
                    [segments[k][2] for k in idx],
                    target_prefix=[[tgt]] * len(idx),
                    beam_size=2,
                    max_decoding_length=MAX_SEGMENT_TOKENS * 2,
                )
                for k, out in zip(idx, outs):
                    tokens = out.hypotheses[0][1:]  # без мовного префікса
                    translated[k] = self.sp.decode(tokens).strip()

        pieces = {}
        for k, (i, _part, _tok) in enumerate(segments):
            pieces.setdefault(i, []).append(translated.get(k, ""))
        for i, parts in pieces.items():
            result[i] = " ".join(p for p in parts if p) or texts[i]
        return result


_translator = None
_translator_lock = threading.Lock()


def get_translator():
    """Кешований переклад-рушій (модель вантажиться один раз за сесію)."""
    global _translator
    with _translator_lock:
        if _translator is None:
            path = find_model()
            if path is None:
                raise RuntimeError(
                    "Модель перекладу NLLB не завантажена. Запустіть переклад "
                    "із графічного інтерфейсу - програма запропонує завантажити "
                    "її, або скопіюйте модель у "
                    f"{os.path.join(candidate_roots()[0], MODEL_SUBDIR)}")
            _translator = NllbTranslator(path)
        return _translator


def unload():
    global _translator
    with _translator_lock:
        _translator = None
