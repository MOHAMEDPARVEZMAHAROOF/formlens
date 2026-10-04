#!/usr/bin/env python3
"""Generate self-authored synthetic form fixtures for FormLens.

These are computer-drawn test forms, NOT real documents. They exist so the
pipeline and tests have labeled inputs without using any real person's data.
Each PNG gets a JSON sidecar with ground truth.
"""
import json
import numpy as np
import cv2

W, H = 1200, 1600

SPECS = [
    # name, seed, checked idx, bubble answers (0-3 or None), signature?, warp, shadow
    ("form_clean",   11, [0, 2],    [1, 0, 3], True,  40, 0.10),
    ("form_rotated", 22, [0, 1, 3], [2, 2, 1], False, 110, 0.15),
    ("form_shadow",  33, [2],       [0, 3, 2], True,  70, 0.35),
    ("form_messy",   44, [],        [None, 3, 0], False, 90, 0.25),
]


def draw_form(spec):
    name, seed, checked, answers, sig, warp, shadow = spec
    rng = np.random.default_rng(seed)
    img = np.full((H, W, 3), 255, np.uint8)

    # Page border (document edge for rectification).
    cv2.rectangle(img, (18, 18), (W - 18, H - 18), (40, 40, 40), 10)

    cv2.putText(img, "SAMPLE FORM (synthetic fixture)", (90, 130),
                cv2.FONT_HERSHEY_SIMPLEX, 1.1, (30, 30, 30), 3, cv2.LINE_AA)
    cv2.putText(img, "self-authored test data - not a real document", (90, 185),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (120, 120, 120), 2, cv2.LINE_AA)

    # Checkboxes.
    cb = []
    for i in range(4):
        x, y, s = 140, 420 + i * 110, 48
        cv2.rectangle(img, (x, y), (x + s, y + s), (30, 30, 30), 3)
        cv2.putText(img, f"Option {i + 1}", (x + 80, y + 36),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (30, 30, 30), 2, cv2.LINE_AA)
        if i in checked:
            cv2.line(img, (x + 8, y + 8), (x + s - 8, y + s - 8), (20, 20, 20), 7)
            cv2.line(img, (x + s - 8, y + 8), (x + 8, y + s - 8), (20, 20, 20), 7)
        cb.append([x, y, s, s])

    # OMR bubble rows.
    bubbles = []
    for q in range(3):
        y = 900 + q * 120
        cv2.putText(img, f"Q{q + 1}", (300, y + 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (30, 30, 30), 2, cv2.LINE_AA)
        row = []
        for o in range(4):
            x = 430 + o * 130
            cv2.circle(img, (x, y), 32, (30, 30, 30), 3)
            if answers[q] == o:
                cv2.circle(img, (x, y), 24, (25, 25, 25), cv2.FILLED)
            row.append((x, y))
        bubbles.append(row)

    # Signature box.
    sx, sy, sw, sh = 250, 1330, 700, 150
    cv2.rectangle(img, (sx, sy), (sx + sw, sy + sh), (30, 30, 30), 3)
    cv2.putText(img, "Signature", (sx + 12, sy - 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (30, 30, 30), 2, cv2.LINE_AA)
    if sig:
        pts = []
        x = sx + 60
        while x < sx + sw - 60:
            pts.append([x, sy + sh // 2 + int(rng.integers(-35, 35))])
            x += int(rng.integers(25, 60))
        cv2.polylines(img, [np.array(pts, np.int32)], False, (25, 25, 25), 4,
                      cv2.LINE_AA)

    # Perspective warp.
    src = np.float32([[0, 0], [W, 0], [W, H], [0, H]])
    dst = src + rng.integers(-warp, warp, size=(4, 2)).astype(np.float32)
    m = cv2.getPerspectiveTransform(src, dst)
    out = cv2.warpPerspective(img, m, (W, H), borderValue=(18, 22, 30))

    # Lighting gradient + noise.
    yy = np.linspace(1.0 - shadow, 1.0, H)[:, None, None]
    out = np.clip(out.astype(np.float32) * yy, 0, 255).astype(np.uint8)
    noise = rng.normal(0, 6, out.shape).astype(np.int16)
    out = np.clip(out.astype(np.int16) + noise, 0, 255).astype(np.uint8)

    truth = {
        "fixture": name,
        "synthetic": True,
        "checkboxes_checked": sorted(checked),
        "bubble_answers": answers,   # 0-based option index or None
        "signature_present": sig,
    }
    return out, truth


if __name__ == "__main__":
    import sys
    outdir = sys.argv[1] if len(sys.argv) > 1 else "."
    for spec in SPECS:
        img, truth = draw_form(spec)
        cv2.imwrite(f"{outdir}/{spec[0]}.png", img)
        json.dump(truth, open(f"{outdir}/{spec[0]}.json", "w"), indent=2)
        print("wrote", spec[0])
