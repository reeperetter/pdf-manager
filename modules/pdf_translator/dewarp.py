"""Виправлення викривлення сторінок (фото книжок/згинів) через OpenCV."""

from PIL import Image

from .ocr import (_LATIN_LANGS, _extract_words, _group_words_into_lines,
                  _run_tesseract_pass, preprocess_for_ocr)

_CV2_MODULE = None
_NP_MODULE = None


def _lazy_import_cv2():
    """Лінивий імпорт opencv-python-headless + numpy.

    Це основні залежності проєкту (завжди встановлені й завжди включені
    в готову збірку) - лінивий імпорт лишився лише тому, що завантаження
    cv2 займає помітний час, і немає сенсу платити цим часом при старті
    програми, якщо людина жодного разу не вмикала "Випрямлення сторінки"."""
    global _CV2_MODULE, _NP_MODULE
    if _CV2_MODULE is None:
        import cv2 as _cv2
        import numpy as _np
        _CV2_MODULE, _NP_MODULE = _cv2, _np
    return _CV2_MODULE, _NP_MODULE


def _dewarp_global_curve(pil_img, cv2, np, log_fn=None, cancel_event=None):
    """Стратегія 1: одна спільна "крива згину" на всю сторінку."""
    arr = np.array(pil_img.convert("RGB"))
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    h, w = gray.shape
    thresh = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 25, 15
    )

    n_strips = 30
    strip_w = max(20, w // n_strips)
    smooth_k = max(5, h // 170)
    strip_centers, strip_line_ys = [], []
    for i in range(n_strips):
        if cancel_event and cancel_event.is_set():
            return None
        x0, x1 = i * strip_w, min(w, (i + 1) * strip_w)
        if x1 - x0 < 5:
            continue
        row_density = thresh[:, x0:x1].sum(axis=1).astype(np.float64)
        if row_density.max() <= 0:
            continue
        row_density = np.convolve(
            row_density, np.ones(smooth_k) / smooth_k, mode="same")
        threshold_val = row_density.max() * 0.25
        peaks, in_peak, peak_start = [], False, 0
        for y in range(h):
            if row_density[y] > threshold_val:
                if not in_peak:
                    in_peak, peak_start = True, y
            else:
                if in_peak:
                    in_peak = False
                    peaks.append((peak_start + y) / 2)
        if in_peak:
            peaks.append((peak_start + h) / 2)
        if peaks:
            strip_centers.append((x0 + x1) / 2)
            strip_line_ys.append(peaks)

    if len(strip_centers) < 5:
        return None

    from collections import Counter
    common_n, n_match = Counter(len(p) for p in strip_line_ys).most_common(1)[0]
    if common_n < 3 or n_match < len(strip_centers) * 0.6:
        return None

    line_curve_points = [[] for _ in range(common_n)]
    for cx, ys in zip(strip_centers, strip_line_ys):
        if len(ys) != common_n:
            continue
        for idx, y in enumerate(ys):
            line_curve_points[idx].append((cx, y))

    grid_x = np.linspace(0, w, 200)
    all_curv = []
    for pts in line_curve_points:
        if len(pts) < 5:
            continue
        xs = np.array([p[0] for p in pts])
        ys = np.array([p[1] for p in pts])
        curvature = ys - ys.mean()
        all_curv.append(np.interp(grid_x, xs, curvature,
                        left=np.nan, right=np.nan))

    if len(all_curv) < 3:
        return None

    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        avg_curv = np.nanmedian(np.array(all_curv), axis=0)
    valid = ~np.isnan(avg_curv)
    if valid.sum() < 10:
        return None

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        spread = np.nanstd(np.array(all_curv), axis=0)
    typical_spread = float(np.nanmedian(spread[valid]))
    max_bend = float(np.max(np.abs(avg_curv[valid])))
    if max_bend < 3.0:
        return "no_bend"
    if typical_spread > max(6.0, max_bend * 0.5):
        return None

    poly_coeffs = np.polyfit(grid_x[valid], avg_curv[valid], deg=4)
    full_curve = np.polyval(poly_coeffs, np.arange(w))

    map_x, map_y = np.meshgrid(
        np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    map_y = map_y + full_curve.astype(np.float32)[np.newaxis, :]
    dewarped = cv2.remap(
        arr, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

    return Image.fromarray(dewarped)


def _dewarp_perline(pil_img, cv2, np, log_fn=None, cancel_event=None):
    """Стратегія 2 (fallback): кожен рядок випрямляється окремо."""
    arr = np.array(pil_img.convert("RGB"))
    h, w = arr.shape[:2]

    proc_img = preprocess_for_ocr(pil_img)
    data = _run_tesseract_pass(proc_img, _LATIN_LANGS, "--oem 1 --psm 6")
    words = _extract_words(data, 0)
    groups = _group_words_into_lines(words)

    scale_x = pil_img.width / proc_img.width
    scale_y = pil_img.height / proc_img.height

    line_infos = []
    for group in groups:
        if cancel_event and cancel_event.is_set():
            return pil_img
        if len(group) < 4:
            continue
        xs = np.array([wd["x"] for wd in group]) * scale_x
        ys = np.array([(wd["y"] + wd["h"] / 2) for wd in group]) * scale_y
        hs = np.array([wd["h"] for wd in group]) * scale_y
        if xs.max() - xs.min() < w * 0.15:
            continue
        deg = 2 if len(xs) >= 6 else 1
        coeffs = np.polyfit(xs, ys, deg)
        line_infos.append({
            "coeffs": coeffs, "target_y": float(np.median(ys)),
            "med_h": float(np.median(hs)),
            "x0": float(xs.min()), "x1": float(xs.max()),
        })

    if len(line_infos) < 3:
        return pil_img

    max_bend = max(
        float(np.max(np.abs(np.polyval(li["coeffs"], np.linspace(
            li["x0"], li["x1"], 20)) - li["target_y"])))
        for li in line_infos
    )
    if max_bend < 3.0:
        return pil_img

    line_infos.sort(key=lambda li: li["target_y"])
    output = arr.copy()
    n_corrected = 0
    for i, li in enumerate(line_infos):
        if cancel_event and cancel_event.is_set():
            return pil_img
        gap_above = (li["target_y"] - line_infos[i - 1]
                     ["target_y"]) / 2 if i > 0 else 1e9
        gap_below = (line_infos[i + 1]["target_y"] - li["target_y"]
                     ) / 2 if i < len(line_infos) - 1 else 1e9
        band_half = min(li["med_h"] * 1.6 + 8,
                        max(6.0, min(gap_above, gap_below) - 2))

        y0 = int(max(0, li["target_y"] - band_half))
        y1 = int(min(h, li["target_y"] + band_half))
        x0 = int(max(0, li["x0"] - 20))
        x1 = int(min(w, li["x1"] + 20))
        if y1 <= y0 or x1 <= x0:
            continue

        col_x = np.arange(x0, x1)
        shift = (np.polyval(li["coeffs"], col_x) -
                 li["target_y"]).astype(np.float32)
        shift = np.clip(shift, -h * 0.05, h * 0.05)

        map_x_band, map_y_band = np.meshgrid(
            col_x.astype(np.float32), np.arange(y0, y1, dtype=np.float32))
        map_y_band = map_y_band + shift[np.newaxis, :]
        band = cv2.remap(
            arr, map_x_band, map_y_band, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        output[y0:y1, x0:x1] = band
        n_corrected += 1

    if n_corrected == 0:
        return pil_img

    return Image.fromarray(output)


def dewarp_page_image(pil_img, log_fn=None, cancel_event=None):
    """Виправляє викривлення сторінки через _dewarp_global_curve чи _dewarp_perline."""
    cv2, np = _lazy_import_cv2()

    result = _dewarp_global_curve(
        pil_img, cv2, np, log_fn=log_fn, cancel_event=cancel_event)
    if result == "no_bend":
        return pil_img
    if result is not None:
        return result

    if cancel_event and cancel_event.is_set():
        return pil_img

    return _dewarp_perline(
        pil_img, cv2, np, log_fn=log_fn, cancel_event=cancel_event)
