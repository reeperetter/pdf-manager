"""Збереження розпізнаного/перекладеного тексту у TXT і DOCX."""
import os

import docx as _docx_module


def _write_txt_file(path, page_texts):
    with open(path, "w", encoding="utf-8") as f:
        for i, text in enumerate(page_texts):
            if len(page_texts) > 1:
                if i > 0:
                    f.write("\n\n")
                f.write(f"----- Сторінка {i + 1} -----\n\n")
            f.write(text)
            f.write("\n")


def _write_docx_file(path, page_texts):
    doc = _docx_module.Document()
    for i, text in enumerate(page_texts):
        if i > 0:
            doc.add_page_break()
        if len(page_texts) > 1:
            heading = doc.add_paragraph(f"Сторінка {i + 1}")
            heading.runs[0].bold = True
        for line in text.split("\n"):
            if line.strip():
                doc.add_paragraph(line)
    doc.save(path)


def save_text_outputs(page_texts, output_dir, base_name, suffix, formats, split_pages):
    saved = []
    writers = {"txt": _write_txt_file, "docx": _write_docx_file}
    if split_pages:
        for i, text in enumerate(page_texts):
            for fmt in formats:
                out_path = os.path.join(
                    output_dir, f"{base_name}{suffix}_p{i + 1}.{fmt}")
                writers[fmt](out_path, [text])
                saved.append(out_path)
    else:
        for fmt in formats:
            out_path = os.path.join(output_dir, f"{base_name}{suffix}.{fmt}")
            writers[fmt](out_path, page_texts)
            saved.append(out_path)
    return saved
