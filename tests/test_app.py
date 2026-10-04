"""Offline API tests for FormLens (no network, no AWS)."""
import cv2
import pytest
from fastapi.testclient import TestClient

from formlens import app as appmod
from sample_inputs.make_fixtures import draw_form, SPECS

client = TestClient(appmod.app)


def png_bytes(name):
    spec = next(s for s in SPECS if s[0] == name)
    img, _ = draw_form(spec)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


def upload(name="form_clean"):
    return client.post("/api/analyze",
                       files={"file": (f"{name}.png", png_bytes(name),
                                       "image/png")})


def test_status():
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    assert "opencv" in body and "aws" in body
    assert body["aws"]["mode"] == "local-only"  # no AWS creds in test env


def test_analyze_roundtrip():
    r = upload()
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["total_fields"] > 0
    assert body["annotated_url"].endswith("/annotated.png")
    for f in body["fields"]:
        assert {"id", "kind", "value", "confidence", "bbox"} <= set(f)
    # annotated download
    img = client.get(body["annotated_url"])
    assert img.status_code == 200
    assert img.headers["content-type"] == "image/png"
    # report export
    rep = client.get(f"/api/analyses/{body['id']}/report.json")
    assert rep.status_code == 200
    assert rep.json()["tool"] == "FormLens"
    # detail view
    det = client.get(f"/api/analyses/{body['id']}")
    assert det.status_code == 200


def test_analyze_rejects_non_image():
    r = client.post("/api/analyze",
                    files={"file": ("x.txt", b"hello", "text/plain")})
    assert r.status_code == 400


def test_analyze_rejects_garbage_png():
    r = client.post("/api/analyze",
                    files={"file": ("x.png", b"\x89PNGjunk", "image/png")})
    assert r.status_code in (400, 422)


def test_batch():
    r = client.post("/api/analyze/batch", files=[
        ("files", ("a.png", png_bytes("form_clean"), "image/png")),
        ("files", ("b.png", png_bytes("form_shadow"), "image/png")),
    ])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["files"] == 2
    assert body["summary"]["failed"] == 0
    assert len(body["results"]) == 2


def test_batch_reports_bad_file():
    r = client.post("/api/analyze/batch", files=[
        ("files", ("a.png", png_bytes("form_clean"), "image/png")),
        ("files", ("bad.txt", b"nope", "text/plain")),
    ])
    assert r.status_code == 200
    body = r.json()
    assert body["summary"]["files"] == 1
    assert body["summary"]["failed"] == 1
    assert body["errors"][0]["filename"] == "bad.txt"


def test_history_filters():
    upload("form_clean")
    upload("form_shadow")
    all_items = client.get("/api/analyses").json()
    assert len(all_items) >= 2
    q = client.get("/api/analyses", params={"q": "form_shadow"}).json()
    assert all(i["filename"] == "form_shadow.png" for i in q) and q
    mf = client.get("/api/analyses", params={"min_fields": 9999}).json()
    assert mf == []


def test_delete():
    aid = upload("form_messy").json()["id"]
    assert client.delete(f"/api/analyses/{aid}").status_code == 200
    assert client.get(f"/api/analyses/{aid}").status_code == 404


def test_gallery_lists_fixtures():
    # gallery reads from the real sample_inputs dir
    r = client.get("/api/gallery")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
