"""Вибір імені вихідного файлу для пакетних інструментів."""
import os


def resolve_output_path(output_dir, filename, suffix, used, skip_existing):
    """Повертає шлях виходу '<тека>/<ім'я><суфікс><розширення>'.

    - skip_existing і файл уже є (не створений у цьому запуску) -> None;
    - колізія (однакові імена з різних тек або файл уже є) -> '_1', '_2'...
    Знайдений шлях додається в used."""
    stem, ext = os.path.splitext(filename)
    out = os.path.join(output_dir, f"{stem}{suffix}{ext}")
    if skip_existing and out not in used and os.path.exists(out):
        return None
    n = 1
    while out in used or os.path.exists(out):
        out = os.path.join(output_dir, f"{stem}{suffix}_{n}{ext}")
        n += 1
    used.add(out)
    return out
