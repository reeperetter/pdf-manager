"""
Діагностика визначення орієнтації сторінки.

Використання:
    python3 diagnose_orientation.py шлях/до/файлу.pdf [номер_сторінки]

(номер_сторінки - 1-індексований, за замовчуванням 1)

Виводить детальну інформацію про те, що саме бачить наш код на кожному
кроці - можна скопіювати весь вивід і надіслати для діагностики, навіть
без самого PDF-файлу.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fitz
import io
from PIL import Image
import pytesseract

import ocr as ocr_module


def main():
    if len(sys.argv) < 2:
        print("Використання: python3 diagnose_orientation.py файл.pdf [сторінка]")
        sys.exit(1)

    pdf_path = sys.argv[1]
    page_num = int(sys.argv[2]) if len(sys.argv) > 2 else 1

    print(f"=== Файл: {pdf_path} ===")
    print(f"TESSERACT_CMD: {ocr_module.TESSERACT_CMD}")
    print(f"Версія pytesseract: {pytesseract.get_tesseract_version()}")
    print()

    doc = fitz.open(pdf_path)
    print(f"Сторінок у файлі: {doc.page_count}")
    page = doc[page_num - 1]
    print(f"Розмір сторінки {page_num}: {page.rect}")

    for dpi in (300,):
        print()
        print(f"--- Рендеринг при {dpi} DPI ---")
        pix = page.get_pixmap(dpi=dpi)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        print(f"Розмір зображення: {img.size}")

        print()
        print("--- Основний OSD-прохід (на оригіналі) ---")
        try:
            osd = pytesseract.image_to_osd(img, output_type=pytesseract.Output.DICT)
            print(f"OSD результат: {osd}")
        except Exception as e:
            print(f"OSD ПОМИЛКА: {e}")

        print()
        print("--- Перебір усіх 4 орієнтацій (резервний метод) ---")
        for angle in (0, 90, 180, 270):
            candidate = img.rotate(-angle, expand=True) if angle else img
            try:
                osd_c = pytesseract.image_to_osd(candidate, output_type=pytesseract.Output.DICT)
                print(f"  Кандидат {angle:>3}°: {osd_c}")
            except Exception as e:
                print(f"  Кандидат {angle:>3}°: ПОМИЛКА {e}")

        print()
        print("--- Підсумок функції detect_and_fix_orientation ---")
        fixed, was_rotated = ocr_module.detect_and_fix_orientation(img, log_fn=print)
        print(f"Було повернуто: {was_rotated}, фінальний розмір: {fixed.size}")

        out_path = f"diagnose_output_page{page_num}_{dpi}dpi.png"
        fixed.save(out_path)
        print(f"Результат збережено: {out_path} (гляньте на нього)")


if __name__ == "__main__":
    main()
