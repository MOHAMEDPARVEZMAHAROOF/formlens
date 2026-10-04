"""FormLens vision core: OpenCV 5 paper-form analysis.

Pipeline
--------
1. Decode upload -> BGR, downscale to a working size.
2. Document rectification: largest quadrilateral contour -> perspective warp
   to a fixed 1200x1600 canvas (falls back to the raw image, flagged).
3. Adaptive Gaussian thresholding (handles shadows / uneven light).
4. Field detection on the rectified binary image:
   - checkboxes: small square contours -> fill-ratio classification
   - OMR bubbles: circular contours grouped into rows -> darkest = selected
   - signature box: wide rectangle -> dark-pixel density classification
5. Per-field confidence from the distance of the fill metric to its
   decision threshold.
6. Annotated output image with color-coded boxes and labels.

Everything is generic contour analysis; no template coordinates are used.
"""
from __future__ import annotations

import cv2
import numpy as np

WARP_W, WARP_H = 1200, 1600
MAX_DIM = 1600

# Decision thresholds (documented; tuned on self-authored synthetic fixtures)
CHECK_FILL_T = 0.15    # center-region fill ratio above this -> checked
BUBBLE_DARK_T = 150.0  # bubble mean-gray below this -> candidate for filled
SIG_DENSITY_T = 0.015  # signature-region ink density above this -> present
AMBIGUITY_T = 0.75   # confidence below this -> flag field for human review


def _conf(dist: float, scale: float) -> float:
    """Map distance-from-threshold to a 0.55..0.99 confidence."""
    return round(0.55 + 0.44 * min(1.0, max(0.0, dist) / scale), 2)


def decode_image(data: bytes) -> np.ndarray:
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Could not decode image (not a valid image file).")
    h, w = img.shape[:2]
    if min(h, w) < 200:
        raise ValueError("Image too small to analyze (min 200px).")
    scale = min(1.0, MAX_DIM / max(h, w))
    if scale < 1.0:
        img = cv2.resize(img, (int(w * scale), int(h * scale)),
                         interpolation=cv2.INTER_AREA)
    return img


def _order_points(pts: np.ndarray) -> np.ndarray:
    r = pts.reshape(4, 2).astype(np.float32)
    s = r.sum(axis=1)            # x + y
    d = np.diff(r, axis=1).ravel()  # y - x
    # tl: min sum; tr: min (y-x); br: max sum; bl: max (y-x)
    return np.array([r[np.argmin(s)], r[np.argmin(d)],
                     r[np.argmax(s)], r[np.argmax(d)]], dtype=np.float32)


def rectify(gray: np.ndarray) -> tuple[np.ndarray, bool]:
    """Warp the detected document to WARP_W x WARP_H. Returns (img, found).

    Finds the bright page region (OTSU + morphological close to fill text),
    so the dark photo background does not merge into the page contour.
    """
    blur = cv2.GaussianBlur(gray, (7, 7), 0)
    _, th = cv2.threshold(blur, 0, 255,
                          cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE,
                          cv2.getStructuringElement(cv2.MORPH_RECT, (31, 31)))
    contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    h, w = gray.shape
    page_area = h * w
    best, best_area = None, 0
    for c in contours:
        area = cv2.contourArea(c)
        if area < 0.25 * page_area or area > 0.995 * page_area:
            continue
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4 and area > best_area:
            best, best_area = approx, area
    if best is None:
        # Fallback: resize raw frame to the working canvas.
        return cv2.resize(gray, (WARP_W, WARP_H)), False
    src = _order_points(best)
    dst = np.array([[0, 0], [WARP_W, 0], [WARP_W, WARP_H], [0, WARP_H]],
                   dtype=np.float32)
    m = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(gray, m, (WARP_W, WARP_H)), True


def _center_fill(bin_inv: np.ndarray, bbox: list, frac: float = 0.5) -> float:
    """Dark-pixel fraction in the central region of a bbox.

    The printed border lives at the edges, so the center cleanly separates
    a real mark (tick/cross through the middle) from an empty box.
    """
    x, y, w, h = bbox
    cw, ch = int(w * frac), int(h * frac)
    cx, cy = x + w // 2, y + h // 2
    roi = bin_inv[cy - ch // 2:cy + ch // 2, cx - cw // 2:cx + cw // 2]
    if roi.size == 0:
        return 0.0
    return float((roi > 0).mean())


def _ink_density(bin_inv: np.ndarray, bbox: list) -> float:
    """Signature ink density.

    Measured on the central interior of the box (printed labels sit above
    it, the border at its edges). A 5x5 opening plus a 100px minimum
    component area rejects speckle noise; only real strokes count.
    """
    x, y, w, h = bbox
    x0, x1 = x + int(w * 0.15), x + int(w * 0.85)
    y0, y1 = y + int(h * 0.25), y + int(h * 0.80)
    roi = bin_inv[y0:y1, x0:x1]
    if roi.size == 0:
        return 0.0
    opened = cv2.morphologyEx(
        roi, cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5)))
    n, _, stats, _ = cv2.connectedComponentsWithStats(opened, 8)
    ink = sum(int(stats[i, cv2.CC_STAT_AREA]) for i in range(1, n)
              if stats[i, cv2.CC_STAT_AREA] >= 100)
    return ink / roi.size


def _iou(a: list, b: list) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    if ix == 0 or iy == 0:
        return 0.0
    inter = ix * iy
    return inter / (aw * ah + bw * bh - inter)


def find_checkboxes(bin_inv: np.ndarray, page_area: float) -> list[dict]:
    contours, _ = cv2.findContours(bin_inv, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    cands = []
    for c in contours:
        area = cv2.contourArea(c)
        if not (0.0004 * page_area < area < 0.012 * page_area):
            continue
        peri = cv2.arcLength(c, True)
        if peri == 0:
            continue
        approx = cv2.approxPolyDP(c, 0.04 * peri, True)
        if len(approx) != 4:
            continue
        x, y, w, h = cv2.boundingRect(c)
        aspect = w / max(1, h)
        if not (0.78 < aspect < 1.28):
            continue
        hull = cv2.convexHull(c)
        if area / max(1, cv2.contourArea(hull)) < 0.82:
            continue
        bbox = [int(x), int(y), int(w), int(h)]
        fill = _center_fill(bin_inv, bbox, 0.5)
        checked = fill > CHECK_FILL_T
        cands.append({
            "kind": "checkbox",
            "value": "checked" if checked else "unchecked",
            "confidence": _conf(abs(fill - CHECK_FILL_T), 0.30),
            "metric": round(fill, 3),
            "bbox": bbox,
        })
    return _dedup(cands)


def _dedup(fields: list[dict]) -> list[dict]:
    kept: list[dict] = []
    for f in sorted(fields, key=lambda d: -d["bbox"][2] * d["bbox"][3]):
        if all(_iou(f["bbox"], k["bbox"]) < 0.35 for k in kept):
            kept.append(f)
    return kept


def find_bubbles(bin_inv: np.ndarray, gray: np.ndarray,
                 page_area: float) -> list[dict]:
    contours, _ = cv2.findContours(bin_inv, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    circles = []
    for c in contours:
        area = cv2.contourArea(c)
        if not (0.0006 * page_area < area < 0.010 * page_area):
            continue
        peri = cv2.arcLength(c, True)
        if peri == 0:
            continue
        circularity = 4 * np.pi * area / (peri * peri)
        if circularity < 0.70:
            continue
        x, y, w, h = cv2.boundingRect(c)
        if abs(w - h) / max(1, max(w, h)) > 0.25:
            continue
        roi = gray[y:y + h, x:x + w]
        if roi.size == 0:
            continue
        mask = np.zeros_like(roi)
        cv2.drawContours(mask, [c - np.array([x, y])], -1, 255, cv2.FILLED)
        mean = cv2.mean(roi, mask=mask)[0]
        circles.append({"bbox": [int(x), int(y), int(w), int(h)],
                        "cx": x + w / 2, "cy": y + h / 2,
                        "mean": float(mean)})
    circles = _dedup(circles)
    # Group into rows by y proximity.
    rows: list[list[dict]] = []
    for b in sorted(circles, key=lambda d: d["cy"]):
        placed = False
        for row in rows:
            if abs(b["cy"] - np.mean([r["cy"] for r in row])) < 45:
                row.append(b)
                placed = True
                break
        if not placed:
            rows.append([b])
    fields: list[dict] = []
    q = 0
    for row in rows:
        if len(row) < 3:
            continue  # not an answer row
        q += 1
        row = sorted(row, key=lambda d: d["cx"])[:6]
        means = [b["mean"] for b in row]
        order = sorted(range(len(row)), key=lambda i: means[i])
        darkest, second = order[0], order[1]
        if means[darkest] > BUBBLE_DARK_T:
            value, conf = "none", _conf(BUBBLE_DARK_T - means[darkest], 60.0)
        else:
            gap = means[second] - means[darkest]
            value = "ABCD"[darkest] if darkest < 4 else f"opt{darkest + 1}"
            conf = _conf(gap, 60.0)
        xs = [b["bbox"][0] for b in row]
        ys = [b["bbox"][1] for b in row]
        xe = [b["bbox"][0] + b["bbox"][2] for b in row]
        ye = [b["bbox"][1] + b["bbox"][3] for b in row]
        fields.append({
            "kind": "bubble_group",
            "label": f"Q{q}",
            "value": value,
            "confidence": conf,
            "metric": round(means[darkest], 1),
            "bbox": [min(xs), min(ys), max(xe) - min(xs), max(ye) - min(ys)],
            "options": len(row),
        })
    return fields


def find_signature(bin_inv: np.ndarray, page_area: float) -> list[dict]:
    contours, _ = cv2.findContours(bin_inv, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    best = None
    for c in contours:
        area = cv2.contourArea(c)
        if not (0.012 * page_area < area < 0.09 * page_area):
            continue
        x, y, w, h = cv2.boundingRect(c)
        aspect = w / max(1, h)
        if not (2.2 < aspect < 7.0):
            continue
        if y < 0.55 * WARP_H:  # signature boxes live near the bottom
            continue
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.03 * peri, True)
        if len(approx) != 4:
            continue
        if best is None or area > best[0]:
            best = (area, c, (x, y, w, h))
    if best is None:
        return []
    _, c, (x, y, w, h) = best
    bbox = [int(x), int(y), int(w), int(h)]
    density = _ink_density(bin_inv, bbox)
    present = density > SIG_DENSITY_T
    return [{
        "kind": "signature",
        "label": "Signature",
        "value": "present" if present else "absent",
        "confidence": _conf(abs(density - SIG_DENSITY_T), 0.03),
        "metric": round(density, 4),
        "bbox": bbox,
    }]


def annotate(warped_bgr: np.ndarray, fields: list[dict]) -> np.ndarray:
    out = warped_bgr.copy()
    GREEN, RED, AMBER, INK = (34, 139, 34), (220, 60, 60), (200, 140, 20), (30, 41, 59)
    for i, f in enumerate(fields):
        x, y, w, h = f["bbox"]
        good = f["value"] not in ("unchecked", "absent", "none")
        color = GREEN if good else (AMBER if f["value"] == "none" else RED)
        cv2.rectangle(out, (x, y), (x + w, y + h), color, 4)
        tag = f.get("label") or f"Field {i + 1}"
        text = f"{tag}: {f['value']} ({f['confidence']:.0%})"
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)
        ty = max(0, y - th - 14)
        cv2.rectangle(out, (x, ty), (x + tw + 16, ty + th + 14), color, cv2.FILLED)
        cv2.putText(out, text, (x + 8, ty + th + 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2,
                    cv2.LINE_AA)
    # Footer strip with summary.
    bar_h = 64
    cv2.rectangle(out, (0, WARP_H - bar_h), (WARP_W, WARP_H), INK, cv2.FILLED)
    n = len(fields)
    cv2.putText(out, f"FormLens: {n} fields detected",
                (24, WARP_H - 22), cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                (255, 255, 255), 2, cv2.LINE_AA)
    return out


def analyze(data: bytes) -> dict:
    """Full pipeline: bytes in -> fields + annotated PNG bytes out."""
    img = decode_image(data)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    warped, rectified = rectify(gray)
    page_area = float(WARP_W * WARP_H)
    blur = cv2.GaussianBlur(warped, (5, 5), 0)
    bin_inv = cv2.adaptiveThreshold(
        blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV,
        51, 9)

    fields: list[dict] = []
    fields += find_checkboxes(bin_inv, page_area)
    fields += find_bubbles(bin_inv, warped, page_area)
    fields += find_signature(bin_inv, page_area)

    # Reading order: top-to-bottom, then left-to-right.
    fields.sort(key=lambda f: (f["bbox"][1] // 60, f["bbox"][0]))
    for i, f in enumerate(fields):
        f["id"] = f"f{i + 1}"
        if not f.get("label"):
            f["label"] = f"Checkbox {i + 1}" if f["kind"] == "checkbox" else f"Field {i + 1}"
        # Uncertainty-first UX: near-threshold readings are flagged for
        # human review instead of being silently guessed.
        f["ambiguous"] = f["confidence"] < AMBIGUITY_T
        f.pop("cx", None); f.pop("cy", None)

    warped_bgr = cv2.cvtColor(warped, cv2.COLOR_GRAY2BGR)
    annotated = annotate(warped_bgr, fields)
    ok, png = cv2.imencode(".png", annotated)
    if not ok:
        raise RuntimeError("Failed to encode annotated image.")

    checked = sum(1 for f in fields if f["kind"] == "checkbox" and f["value"] == "checked")
    answered = sum(1 for f in fields if f["kind"] == "bubble_group" and f["value"] != "none")
    sig = next((f for f in fields if f["kind"] == "signature"), None)
    return {
        "fields": fields,
        "summary": {
            "total_fields": len(fields),
            "checkboxes": sum(1 for f in fields if f["kind"] == "checkbox"),
            "checkboxes_checked": checked,
            "bubble_questions": sum(1 for f in fields if f["kind"] == "bubble_group"),
            "bubble_answered": answered,
            "signature": sig["value"] if sig else "not_found",
            "rectified": rectified,
            "needs_review": sum(1 for f in fields if f["ambiguous"]),
        },
        "annotated_png": png.tobytes(),
    }
