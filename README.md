# FormLens

Upload a photo of a paper form — get every field read back, with confidence.

FormLens is a computer-vision form analyzer built for the **OpenCV AI
Competition 2026** (powered by AWS). It takes a photo or scan of a paper
form and, using **OpenCV 5**, straightens the page (perspective
rectification), finds checkboxes, reads multiple-choice OMR bubbles, and
checks the signature box — returning per-field verdicts with confidence
scores, an annotated output image, and an exportable JSON report.

## The problem

Paper forms are still everywhere: exam OMR sheets, consent forms, surveys,
registration paperwork. Checking them by hand is slow and error-prone, and
most OMR tools demand a rigid pre-registered template. FormLens reads
**arbitrary** form layouts with generic contour analysis — no template
registration step.

## Features

- **Upload & analyze** — drop in a PNG/JPG/WebP photo of a form.
- **OpenCV 5 pipeline** — document rectification (largest quad →
  `getPerspectiveTransform`), adaptive Gaussian thresholding (robust to
  shadows/uneven light), contour-based field detection.
- **Checkboxes** — square-contour detection, checked/unchecked via
  center-region fill ratio.
- **OMR bubbles** — circularity filtering, row grouping, darkest-bubble
  selection with intensity-gap confidence.
- **Signature box** — wide-rectangle detection, ink density via
  connected-component filtering (speckle-robust).
- **Per-field confidence** — every reading carries a confidence score from
  its distance to the decision threshold. Fields below 75% confidence are
  flagged **"review"** for human verification instead of being silently
  trusted (uncertainty-first UX).
- **Annotated output** — color-coded boxes + labels drawn on the rectified
  page; downloadable PNG.
- **Batch mode** — up to 20 forms, per-file breakdown, summary stats.
- **History with filters** — search, date range, minimum field count;
  revisit, download, export, delete.
- **Sample gallery** — one-click analysis of the built-in synthetic fixtures.
- **JSON report export** — full per-field record per analysis.
- **AWS hook** — annotated images upload to S3 automatically when
  `FORMLENS_S3_BUCKET` is set and AWS credentials are available; otherwise
  the app runs fully in local mode and says so honestly.

## Tech stack

- **Vision:** OpenCV 5 (`opencv-python-headless`), NumPy — pure contour /
  morphology pipeline, no ML model, no template coordinates.
- **Backend:** FastAPI, SQLite (stdlib `sqlite3`), vanilla JS frontend.
- **Cloud:** optional S3 upload via `boto3` (guarded import; never required).
- **Tests:** pytest, fully offline.

## Quickstart

```bash
cd formlens
bash run.sh
# open http://127.0.0.1:8000
```

`run.sh` creates `.venv` on first run and installs `requirements.txt`.
Analysis data lives in `data/` (override with `FORMLENS_DATA`).

To enable the AWS path:

```bash
export FORMLENS_S3_BUCKET=my-bucket   # plus valid AWS credentials
bash run.sh
```

To run the tests:

```bash
.venv/bin/python -m pytest tests/ -q
```

## API overview

| Method | Path | Description |
| ------ | ---- | ----------- |
| `GET` | `/api/status` | Analysis count, OpenCV version, AWS mode |
| `POST` | `/api/analyze` | multipart `file` → full analysis |
| `POST` | `/api/analyze/batch` | up to 20 files → results + summary |
| `GET` | `/api/analyses` | history (`q`, `from_ts`, `to_ts`, `min_fields`) |
| `GET` | `/api/analyses/{id}` | full analysis record |
| `GET` | `/api/analyses/{id}/annotated.png` | downloadable annotated image |
| `GET` | `/api/analyses/{id}/report.json` | exportable JSON report |
| `DELETE` | `/api/analyses/{id}` | delete analysis |
| `GET` | `/api/gallery` | built-in sample forms + ground truth |

## Honesty notes

- **All test fixtures are self-authored synthetic forms** (computer-drawn in
  `sample_inputs/make_fixtures.py`), clearly labeled as such. No real
  documents, no scraped data, no real people's handwriting.
- **No accuracy claims** beyond the fixture results reported in REPORT.md.
  The pipeline has not been evaluated on real-world forms.
- **AWS:** this build has no AWS account access; the S3 path is implemented
  and documented but not deployed. See REPORT.md.
- Output is advisory — ambiguous fields should be verified by a human.

## License

MIT — see [LICENSE](LICENSE).
