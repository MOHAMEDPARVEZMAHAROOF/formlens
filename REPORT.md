# FormLens — Technical Report
### OpenCV AI Competition 2026 (powered by AWS) · Solo entry: Mohamed Parvez Maharoof

## 1. Problem & users

Paper forms — exam OMR sheets, consent forms, surveys, registration
paperwork — are still checked by hand in schools, clinics, and small
offices. Manual checking is slow, inconsistent, and scales badly. Existing
OMR tools typically require rigid pre-registered templates: move a checkbox
and the whole setup breaks. FormLens reads **arbitrary form layouts** with
generic computer vision, no template registration, and reports a confidence
score on every reading so a human knows what to double-check.

Target users: teachers grading bubble sheets, office staff digitizing
intake forms, and small teams that need a second pair of eyes on paper
without buying enterprise OMR software.

## 2. Architecture

```
photo/scan ──▶ FastAPI ──▶ OpenCV 5 pipeline ──┬──▶ annotated PNG ──▶ user / (S3)
(upload)      (uvicorn)                        │
                                               ├──▶ per-field JSON ──▶ SQLite ──▶ history / filters / report export
                                               │
                                               └──▶ AWS S3 hook (optional; activates on credentials)
```

- **Frontend:** vanilla JS single-page app (Analyze / Batch / Gallery /
  History tabs), responsive, no build step.
- **Backend:** FastAPI + SQLite (stdlib). Annotated images stored on disk;
  metadata + field records in SQLite.
- **Vision core** (`formlens/pipeline.py`): pure OpenCV 5 + NumPy. No ML
  model, no template coordinates.
- **Cloud:** `formlens/aws_store.py` uploads annotated PNGs to S3 when
  `FORMLENS_S3_BUCKET` is set and credentials resolve via boto3's default
  chain. The import is guarded; the app runs fully without it and labels
  the mode honestly in the UI and `/api/status`.

## 3. OpenCV 5 implementation

1. **Decode & scale** — `cv2.imdecode`, downscale to ≤1600px.
2. **Document rectification** — Gaussian blur → OTSU threshold →
   31×31 morphological close (fills text) → largest 4-point
   `approxPolyDP` contour → `getPerspectiveTransform` + `warpPerspective`
   to a fixed 1200×1600 canvas. Falls back to a plain resize (flagged in
   the response) when no page quad is found.
3. **Binarization** — adaptive Gaussian threshold (blockSize 51, C 9),
   inverted; chosen over global OTSU for shadow/uneven-light robustness.
4. **Checkboxes** — external contours filtered by area (0.04–1.2% of page),
   4 vertices, aspect ratio 0.78–1.28, solidity ≥ 0.82. Classification by
   **center-region fill ratio** (the printed border lives at the edges, so
   the center cleanly separates a tick/cross from an empty box); threshold
   0.15.
5. **OMR bubbles** — contours with circularity ≥ 0.70 in the bubble area
   band, grouped into rows by y-proximity (≥3 per row = one question). The
   darkest bubble (lowest mean gray) is the selection; "none" if it is
   brighter than 150. Confidence from the intensity gap to the runner-up.
6. **Signature box** — wide rectangles (aspect 2.2–7, area 1.2–9% of page,
   lower half of the page). Ink = connected components ≥100px after 5×5
   morphological opening, measured on the central interior (labels sit
   above, borders at the edges) — robust to speckle noise. Threshold 0.015.
7. **Confidence** — every field maps its distance-to-threshold to
   0.55–0.99; near-threshold readings are visibly less confident instead of
   silently guessed.
8. **Annotation** — color-coded boxes + `label: value (confidence%)` drawn
   on the rectified page (green = positive reading, red = negative, amber =
   unanswered).

## 4. AWS deployment

The S3 integration is implemented (`boto3` client, `put_object` of the
annotated PNG, URL returned in the analysis record) and activates
automatically when credentials + bucket are present. **Status: designed,
not deployed — no AWS account access was available for this build**, so no
cloud resources were provisioned and no AWS-hosted run is claimed. The UI
and API report `mode: "local-only"` in this state. A deployment path
(EC2/container or Lambda for the API, S3 for artifacts) is the natural next
step with account access.

## 5. Evaluation

Evaluated on **4 self-authored synthetic fixtures** (computer-drawn forms
with perspective warp ±40–110px, lighting gradients, Gaussian noise;
ground truth in `sample_inputs/*.json`) using the checked-in
`scripts/eval.py`, which compares every field against ground truth.
These are test fixtures, not real documents.

| Fixture | Fields | Correct | Rectified | Flagged for review |
| ------- | ------ | ------- | --------- | ------------------ |
| form_clean | 8 | 8 | yes | 0 |
| form_rotated | 8 | 8 | yes | 0 |
| form_shadow | 8 | 8 | yes | 0 |
| form_messy | 8 | 8 | no (fallback) | 2 |
| **Total** | **32** | **32** | | **2** |

Field-level accuracy on the synthetic fixtures: **32/32 (100%)**.
The 2 "review" flags on form_messy are the uncertainty-first UX working
as designed: the unanswered bubble row ("none", 55% confidence) and the
borderline-absent signature (70%) are correct verdicts the system
honestly marks for human verification instead of silently trusting.

All 18 pytest tests pass (pipeline + API, fully offline). No accuracy
percentage is claimed beyond these fixtures: the pipeline has not been
evaluated on real-world forms.

**Known limitations / failure cases:** heavy perspective (>~15°) can defeat
page detection (graceful fallback: analyze unwarped, flagged); faint pencil
marks near the fill threshold get low confidence rather than a firm answer;
handwriting inside checkbox areas can confuse the fill metric; the
signature test is presence-only, not verification.

## 6. Responsible use

FormLens is a screening aid, not a grader of record: ambiguous fields
should be human-verified (the UI surfaces confidence for exactly this).
No real personal documents were used in development; all fixtures are
synthetic. The repo contains no credentials or API keys.

## 7. Reproducibility

Pinned-style requirements in `requirements.txt`, one-command run
(`bash run.sh`), offline test suite (`pytest tests/`), fixtures generated
by a checked-in script (`sample_inputs/make_fixtures.py`).
