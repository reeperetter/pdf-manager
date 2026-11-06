"""
Чиста логіка конвертацій (без GUI). Кожна функція приймає шлях вхідного
файлу й повертає список створених файлів; у разі проблем піднімає
RuntimeError зі зрозумілим текстом.

Office -> PDF (Word/Excel/PowerPoint): Microsoft Office через COM (Windows),
а якщо його немає - LibreOffice у фоновому режимі. Готового якісного
Python-рішення без офісного пакета не існує. Якщо немає жодного - показуємо
коротку підказку.
"""
import glob
import os
import shutil
import subprocess
import sys
import tempfile

import pymupdf as fitz

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
_FONT_CANDIDATES = [
    os.path.join(_ROOT, "DejaVuSans.ttf"),
    os.path.join(_ROOT, "modules", "pdf_translator", "DejaVuSans.ttf"),
    os.path.join(os.path.dirname(SCRIPT_DIR), "pdf_translator", "DejaVuSans.ttf"),
    r"C:\Windows\Fonts\arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
FONT_PATH = next((p for p in _FONT_CANDIDATES if os.path.isfile(p)), None)

OFFICE_HINT = (
    "Для конвертації Word/Excel/PowerPoint у PDF потрібен Microsoft Office "
    "або LibreOffice (безкоштовний): https://www.libreoffice.org/download/\n"
    "Встановіть один із них і спробуйте ще раз.")


# --------------------------------------------------------- LibreOffice --
def find_soffice():
    for name in ("soffice", "libreoffice"):
        p = shutil.which(name)
        if p:
            return p
    candidates = []
    if os.name == "nt":
        for var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
            base = os.environ.get(var)
            if base:
                candidates.append(os.path.join(
                    base, "LibreOffice", "program", "soffice.exe"))
    elif sys.platform == "darwin":
        candidates.append("/Applications/LibreOffice.app/Contents/MacOS/soffice")
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


# ----------------------------------------------------------- MS Office --
# Microsoft Office керується через COM з PowerShell (додаткових Python-
# пакетів не потрібно). Шляхи передаємо через змінні середовища, щоб не
# мучитися з лапками. Працює лише на Windows, де встановлено відповідну
# програму (Word / Excel / PowerPoint).
_MS_APPS = {
    # розширення -> (ProgID, скрипт)
    "word": ("Word.Application", r"""
$ErrorActionPreference = 'Stop'
$app = New-Object -ComObject Word.Application
try {
  $app.Visible = $false; $app.DisplayAlerts = 0
  $doc = $app.Documents.Open($env:CONV_SRC, $false, $true)
  try { $doc.ExportAsFixedFormat($env:CONV_OUT, 17) } finally { $doc.Close(0) }
} finally { $app.Quit() }
"""),
    "excel": ("Excel.Application", r"""
$ErrorActionPreference = 'Stop'
$app = New-Object -ComObject Excel.Application
try {
  $app.Visible = $false; $app.DisplayAlerts = $false
  $wb = $app.Workbooks.Open($env:CONV_SRC, 0, $true)
  try { $wb.ExportAsFixedFormat(0, $env:CONV_OUT) } finally { $wb.Close($false) }
} finally { $app.Quit() }
"""),
    "powerpoint": ("PowerPoint.Application", r"""
$ErrorActionPreference = 'Stop'
$app = New-Object -ComObject PowerPoint.Application
try {
  $pres = $app.Presentations.Open($env:CONV_SRC, $true, $false, $false)
  try { $pres.SaveAs($env:CONV_OUT, 32) } finally { $pres.Close() }
} finally { $app.Quit() }
"""),
}
_EXT_TO_MS = {
    ".doc": "word", ".docx": "word", ".rtf": "word", ".odt": "word",
    ".xls": "excel", ".xlsx": "excel", ".csv": "excel", ".ods": "excel",
    ".ppt": "powerpoint", ".pptx": "powerpoint", ".odp": "powerpoint",
}


def _ms_office_available(kind):
    if os.name != "nt":
        return False
    try:
        import winreg
        winreg.CloseKey(winreg.OpenKey(
            winreg.HKEY_CLASSES_ROOT, _MS_APPS[kind][0]))
        return True
    except OSError:
        return False


def _office_via_ms(src, out_path, kind):
    powershell = shutil.which("powershell") or "powershell"
    env = dict(os.environ, CONV_SRC=os.path.abspath(src),
               CONV_OUT=os.path.abspath(out_path))
    try:
        proc = subprocess.run(
            [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-Command", _MS_APPS[kind][1]],
            capture_output=True, text=True, timeout=300, env=env,
            creationflags=0x08000000)
    except subprocess.TimeoutExpired:
        raise RuntimeError("Microsoft Office не відповів за 5 хвилин.")
    if proc.returncode != 0 or not os.path.isfile(out_path):
        raise RuntimeError(
            "Microsoft Office не зміг конвертувати файл. "
            + (proc.stderr or proc.stdout or "").strip()[-300:])


def _office_via_libreoffice(src, out_path):
    soffice = find_soffice()
    with tempfile.TemporaryDirectory() as tmp:
        profile = os.path.join(tmp, "profile")
        outdir = os.path.join(tmp, "out")
        os.makedirs(outdir)
        # Окремий профіль - щоб не конфліктувати з уже відкритим LibreOffice.
        profile_url = "file:///" + profile.replace("\\", "/").lstrip("/")
        cmd = [soffice, f"-env:UserInstallation={profile_url}", "--headless",
               "--convert-to", "pdf", "--outdir", outdir, src]
        kwargs = {}
        if os.name == "nt":
            kwargs["creationflags"] = 0x08000000  # без чорного вікна консолі
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  timeout=300, **kwargs)
        except subprocess.TimeoutExpired:
            raise RuntimeError("LibreOffice не відповів за 5 хвилин.")
        produced = glob.glob(os.path.join(outdir, "*.pdf"))
        if not produced:
            msg = (proc.stderr or proc.stdout or "").strip()[-300:]
            raise RuntimeError(f"LibreOffice не зміг конвертувати файл. {msg}")
        shutil.move(produced[0], out_path)


def office_to_pdf(src, out_path, **_):
    """Word/Excel/PowerPoint -> PDF. Порядок: Microsoft Office (якщо є на
    Windows) -> LibreOffice. Якщо перший варіант не вдався, а LibreOffice є,
    пробуємо його."""
    kind = _EXT_TO_MS.get(os.path.splitext(src)[1].lower())
    errors = []
    if kind and _ms_office_available(kind):
        try:
            _office_via_ms(src, out_path, kind)
            return [out_path]
        except RuntimeError as e:
            errors.append(str(e))
    if find_soffice():
        _office_via_libreoffice(src, out_path)
        return [out_path]
    raise RuntimeError(("\n".join(errors) + "\n" if errors else "") + OFFICE_HINT)


# ----------------------------------------------------------------- PDF -> --
def pdf_to_images(src, out_path, fmt="png", dpi=200, **_):
    """out_path - шаблон шляху БЕЗ розширення сторінки: файли
    <out_path>_001.<fmt>, <out_path>_002.<fmt>, ..."""
    fmt = fmt.lower()
    zoom = dpi / 72.0
    created = []
    with fitz.open(src) as doc:
        digits = max(3, len(str(len(doc))))
        for i, page in enumerate(doc, 1):
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            path = f"{out_path}_{i:0{digits}d}.{fmt}"
            if fmt in ("jpg", "jpeg"):
                pix.save(path, jpg_quality=92)
            else:
                pix.save(path)
            created.append(path)
    return created


def pdf_to_txt(src, out_path, **_):
    parts = []
    with fitz.open(src) as doc:
        for page in doc:
            parts.append(page.get_text("text").rstrip())
    text = "\n\n".join(p for p in parts)
    if not text.strip():
        raise RuntimeError(
            "У PDF немає текстового шару (схоже, це скан). Спершу "
            "розпізнайте його у вкладці «OCR».")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    return [out_path]


def pdf_to_docx(src, out_path, **_):
    try:
        from pdf2docx import Converter
    except ImportError:
        raise RuntimeError("Не встановлено пакет pdf2docx.")
    cv = Converter(src)
    try:
        cv.convert(out_path)
    finally:
        cv.close()
    return [out_path]


def _good_text_table(rows):
    """Відсіює "таблиці", знайдені за вирівнюванням тексту, які насправді
    є звичайним абзацом: потрібно >=3 рядків, >=2 колонок і щільне
    заповнення."""
    rows = [r for r in rows if any((c or "").strip() for c in r)]
    if len(rows) < 3:
        return None
    cols = max(len(r) for r in rows)
    if cols < 2:
        return None
    filled = sum(1 for r in rows for c in r if (c or "").strip())
    return rows if filled / (len(rows) * cols) >= 0.5 else None


def pdf_to_xlsx(src, out_path, **_):
    """Знаходить таблиці на сторінках (PyMuPDF find_tables) і кладе кожну
    на окремий аркуш: "С1 Т1", "С1 Т2", ... (сторінка, таблиця).
    Спершу шукає таблиці з лініями; якщо в документі їх немає зовсім -
    повторює пошук за вирівнюванням тексту (таблиці без рамок)."""
    import openpyxl

    def collect(strategy):
        found = []
        with fitz.open(src) as doc:
            for pno, page in enumerate(doc, 1):
                try:
                    tables = page.find_tables(strategy=strategy).tables
                except Exception:
                    tables = []
                for tno, table in enumerate(tables, 1):
                    rows = table.extract()
                    if strategy == "text":
                        rows = _good_text_table(rows or [])
                    if rows:
                        found.append((pno, tno, rows))
        return found

    found = collect("lines") or collect("text")
    if not found:
        raise RuntimeError(
            "Таблиць у PDF не знайдено (для сканів спершу виконайте OCR).")
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for pno, tno, rows in found:
        ws = wb.create_sheet(f"С{pno} Т{tno}"[:31])
        for row in rows:
            ws.append([_cell_value(c) for c in row])
    wb.save(out_path)
    return [out_path]


def _cell_value(value):
    if value is None:
        return None
    text = " ".join(str(value).split())
    try:
        number = float(text.replace(" ", "").replace(",", "."))
        return int(number) if number.is_integer() and "." not in text \
            and "," not in text else number
    except ValueError:
        return text


def pdf_to_pptx(src, out_path, dpi=150, **_):
    """Кожна сторінка PDF - окремий слайд-картинка (вигляд зберігається
    точно); витягнутий текст сторінки кладемо в нотатки слайда."""
    from pptx import Presentation
    from pptx.util import Emu
    prs = Presentation()
    with fitz.open(src) as doc, tempfile.TemporaryDirectory() as tmp:
        if len(doc):
            r = doc[0].rect
            prs.slide_width = Emu(int(r.width * 12700))
            prs.slide_height = Emu(int(r.height * 12700))
        blank = prs.slide_layouts[6]
        zoom = dpi / 72.0
        for i, page in enumerate(doc, 1):
            img = os.path.join(tmp, f"p{i}.png")
            page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False).save(img)
            slide = prs.slides.add_slide(blank)
            slide.shapes.add_picture(img, 0, 0, prs.slide_width, prs.slide_height)
            text = page.get_text("text").strip()
            if text:
                slide.notes_slide.notes_text_frame.text = text
    prs.save(out_path)
    return [out_path]


# --------------------------------------------------------- TXT -> PDF --
def _read_text(path):
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "cp1251", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def txt_to_pdf(src, out_path, fontsize=11, **_):
    text = _read_text(src).replace("\t", "    ")
    if FONT_PATH:
        font = fitz.Font(fontfile=FONT_PATH)
        fontname = "body"
    else:
        font = fitz.Font("helv")
        fontname = "helv"
    width, height = fitz.paper_size("a4")
    margin = 56
    max_w = width - 2 * margin
    line_h = fontsize * 1.35

    lines = []
    for para in text.splitlines():
        if not para.strip():
            lines.append("")
            continue
        current = ""
        for word in para.split(" "):
            trial = word if not current else current + " " + word
            if font.text_length(trial, fontsize) <= max_w:
                current = trial
                continue
            if current:
                lines.append(current)
            # дуже довге слово - ріжемо по символах
            while font.text_length(word, fontsize) > max_w:
                n = len(word)
                while n > 1 and font.text_length(word[:n], fontsize) > max_w:
                    n -= 1
                lines.append(word[:n])
                word = word[n:]
            current = word
        lines.append(current)

    per_page = max(1, int((height - 2 * margin) // line_h))
    doc = fitz.open()
    try:
        for start in range(0, max(len(lines), 1), per_page):
            page = doc.new_page(width=width, height=height)
            if FONT_PATH:
                page.insert_font(fontname=fontname, fontfile=FONT_PATH)
            y = margin + fontsize
            for line in lines[start:start + per_page]:
                if line:
                    page.insert_text((margin, y), line, fontname=fontname,
                                     fontsize=fontsize)
                y += line_h
        doc.save(out_path, garbage=3, deflate=True)
    finally:
        doc.close()
    return [out_path]
