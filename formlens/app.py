"""FormLens web server: upload a form photo, get per-field analysis."""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import aws_store, db, pipeline

BASE = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("FORMLENS_DATA", BASE / "data"))
DB = DATA / "formlens.db"
ANNOTATED = DATA / "annotated"
WEB = BASE / "web"
SAMPLES = BASE / "sample_inputs"

app = FastAPI(title="FormLens")

if WEB.exists():
    app.mount("/static", StaticFiles(directory=WEB), name="static")
if SAMPLES.exists():
    app.mount("/samples", StaticFiles(directory=SAMPLES), name="samples")

MAX_UPLOAD = 12 * 1024 * 1024
ALLOWED = {"image/png", "image/jpeg", "image/webp"}


# ------------------------------------------------------------------ pages
@app.get("/")
def home():
    index = WEB / "index.html"
    if index.exists():
        return FileResponse(index)
    return HTMLResponse("<html><body><h1>FormLens backend</h1>"
                        "<p>API is live at <code>/api/status</code>.</p></body></html>")


# ------------------------------------------------------------------ helpers
def _read_upload(up: UploadFile) -> bytes:
    if up.content_type not in ALLOWED and not (up.filename or "").lower().endswith(
            (".png", ".jpg", ".jpeg", ".webp")):
        raise HTTPException(400, f"Unsupported file type: {up.content_type}. "
                                 "Upload a PNG, JPG, or WebP image.")
    data = up.file.read()
    if not data:
        raise HTTPException(400, "Empty file.")
    if len(data) > MAX_UPLOAD:
        raise HTTPException(400, "File too large (max 12 MB).")
    return data


def _store(filename: str, result: dict, aws_result: dict) -> int:
    ANNOTATED.mkdir(parents=True, exist_ok=True)
    conn = db.connect(DB)
    try:
        cur = conn.execute(
            "INSERT INTO analyses (filename, fields, summary, annotated_path,"
            " aws, created_at) VALUES (?,?,?,?,?,?)",
            (filename, json.dumps(result["fields"]),
             json.dumps(result["summary"]), "",
             json.dumps(aws_result), db.now()))
        conn.commit()
        aid = cur.lastrowid
        path = ANNOTATED / f"{aid}.png"
        path.write_bytes(result["annotated_png"])
        conn.execute("UPDATE analyses SET annotated_path=? WHERE id=?",
                     (str(path), aid))
        conn.commit()
        return aid
    finally:
        conn.close()


def _row_to_public(r) -> dict:
    fields = json.loads(r["fields"])
    summary = json.loads(r["summary"])
    return {
        "id": r["id"], "filename": r["filename"],
        "fields": fields, "summary": summary,
        "aws": json.loads(r["aws"] or "{}"),
        "created_at": r["created_at"],
        "annotated_url": f"/api/analyses/{r['id']}/annotated.png",
    }


def _analyze_upload(up: UploadFile) -> dict:
    data = _read_upload(up)
    try:
        result = pipeline.analyze(data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # never 500 on a bad image
        raise HTTPException(422, f"Analysis failed: {type(e).__name__}")
    aws_result = aws_store.upload_png(
        result["annotated_png"], f"formlens/{db.now():.0f}.png")
    aid = _store(up.filename or "upload", result, aws_result)
    conn = db.connect(DB)
    try:
        row = conn.execute("SELECT * FROM analyses WHERE id=?",
                           (aid,)).fetchone()
    finally:
        conn.close()
    return _row_to_public(row)


# ------------------------------------------------------------------ API
@app.get("/api/status")
def status():
    import cv2
    conn = db.connect(DB)
    try:
        n = conn.execute("SELECT COUNT(*) FROM analyses").fetchone()[0]
    finally:
        conn.close()
    return {"analyses": n, "opencv": cv2.__version__,
            "aws": aws_store.status()}


@app.post("/api/analyze")
def analyze_single(file: UploadFile = File(...)):
    return _analyze_upload(file)


@app.post("/api/analyze/batch")
def analyze_batch(files: list[UploadFile] = File(...)):
    if not files:
        raise HTTPException(400, "No files uploaded.")
    if len(files) > 20:
        raise HTTPException(400, "Batch limit is 20 files.")
    results, errors = [], []
    for up in files:
        try:
            results.append(_analyze_upload(up))
        except HTTPException as e:
            errors.append({"filename": up.filename, "error": e.detail})
    checked = sum(r["summary"]["checkboxes_checked"] for r in results)
    return {"results": results, "errors": errors,
            "summary": {"files": len(results), "failed": len(errors),
                        "total_fields": sum(r["summary"]["total_fields"]
                                            for r in results),
                        "checkboxes_checked": checked}}


@app.get("/api/analyses")
def list_analyses(q: str = Query("", max_length=80),
                 from_ts: float = Query(0),
                 to_ts: float = Query(0),
                 min_fields: int = Query(0, ge=0)):
    conn = db.connect(DB)
    try:
        rows = conn.execute(
            "SELECT * FROM analyses ORDER BY created_at DESC LIMIT 200").fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        if q and q.lower() not in (r["filename"] or "").lower():
            continue
        if from_ts and r["created_at"] < from_ts:
            continue
        if to_ts and r["created_at"] > to_ts:
            continue
        pub = _row_to_public(r)
        if min_fields and pub["summary"]["total_fields"] < min_fields:
            continue
        pub.pop("fields")  # list view stays light
        out.append(pub)
    return out


@app.get("/api/analyses/{aid}")
def get_analysis(aid: int):
    conn = db.connect(DB)
    try:
        row = conn.execute("SELECT * FROM analyses WHERE id=?",
                           (aid,)).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(404, "Analysis not found.")
    return _row_to_public(row)


@app.get("/api/analyses/{aid}/annotated.png")
def annotated_png(aid: int):
    conn = db.connect(DB)
    try:
        row = conn.execute("SELECT annotated_path, filename FROM analyses"
                           " WHERE id=?", (aid,)).fetchone()
    finally:
        conn.close()
    if not row or not Path(row["annotated_path"]).exists():
        raise HTTPException(404, "Annotated image not found.")
    return FileResponse(row["annotated_path"], media_type="image/png",
                        filename=f"formlens-{aid}-annotated.png")


@app.get("/api/analyses/{aid}/report.json")
def report_json(aid: int):
    conn = db.connect(DB)
    try:
        row = conn.execute("SELECT * FROM analyses WHERE id=?",
                           (aid,)).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(404, "Analysis not found.")
    pub = _row_to_public(row)
    return {
        "tool": "FormLens",
        "note": "Per-field computer-vision analysis. Advisory output; "
                "verify ambiguous fields manually.",
        **pub,
    }


@app.delete("/api/analyses/{aid}")
def delete_analysis(aid: int):
    conn = db.connect(DB)
    try:
        row = conn.execute("SELECT annotated_path FROM analyses WHERE id=?",
                           (aid,)).fetchone()
        conn.execute("DELETE FROM analyses WHERE id=?", (aid,))
        conn.commit()
    finally:
        conn.close()
    if not row:
        raise HTTPException(404, "Analysis not found.")
    try:
        Path(row["annotated_path"]).unlink(missing_ok=True)
    except OSError:
        pass
    return {"ok": True}


@app.get("/api/gallery")
def gallery():
    items = []
    if SAMPLES.exists():
        for p in sorted(SAMPLES.glob("*.png")):
            truth = p.with_suffix(".json")
            items.append({
                "name": p.name,
                "url": f"/samples/{p.name}",
                "truth": json.loads(truth.read_text()) if truth.exists() else None,
            })
    return items
