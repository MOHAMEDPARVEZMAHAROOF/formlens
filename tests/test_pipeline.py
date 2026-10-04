"""Offline tests for the FormLens OpenCV pipeline.

Fixtures are self-authored synthetic forms (see sample_inputs/make_fixtures.py),
never real documents. Assertions check detection behavior on those fixtures.
"""
import cv2
import numpy as np
import pytest

from formlens import pipeline
from sample_inputs.make_fixtures import draw_form, SPECS


def fixture_png(name):
    spec = next(s for s in SPECS if s[0] == name)
    img, truth = draw_form(spec)
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes(), truth


def test_decode_rejects_non_image():
    with pytest.raises(ValueError):
        pipeline.analyze(b"this is not an image")


def test_decode_rejects_tiny_image():
    tiny = np.full((50, 50, 3), 255, np.uint8)
    ok, buf = cv2.imencode(".png", tiny)
    with pytest.raises(ValueError):
        pipeline.analyze(buf.tobytes())


def test_clean_form_fields():
    data, truth = fixture_png("form_clean")
    out = pipeline.analyze(data)
    fields = out["fields"]
    by_kind = {}
    for f in fields:
        by_kind.setdefault(f["kind"], []).append(f)
    # 4 checkboxes, 2 checked
    assert len(by_kind.get("checkbox", [])) == 4, [f["bbox"] for f in by_kind.get("checkbox", [])]
    checked = [f for f in by_kind["checkbox"] if f["value"] == "checked"]
    assert len(checked) == 2
    # 3 bubble questions with the drawn answers
    bubbles = sorted(by_kind.get("bubble_group", []), key=lambda f: f["label"])
    assert len(bubbles) == 3
    expected = ["ABCD"[a] for a in truth["bubble_answers"]]
    assert [b["value"] for b in bubbles] == expected
    # signature present
    sig = by_kind.get("signature", [])
    assert len(sig) == 1 and sig[0]["value"] == "present"
    assert out["summary"]["rectified"] is True


def test_rotated_form_no_signature():
    data, truth = fixture_png("form_rotated")
    out = pipeline.analyze(data)
    by_kind = {}
    for f in out["fields"]:
        by_kind.setdefault(f["kind"], []).append(f)
    assert len(by_kind.get("checkbox", [])) == 4
    checked = [f for f in by_kind["checkbox"] if f["value"] == "checked"]
    assert len(checked) == 3
    sig = by_kind.get("signature", [])
    assert len(sig) == 1 and sig[0]["value"] == "absent"


def test_shadow_form_signature_present():
    data, _ = fixture_png("form_shadow")
    out = pipeline.analyze(data)
    sig = [f for f in out["fields"] if f["kind"] == "signature"]
    assert sig and sig[0]["value"] == "present"


def test_confidence_bounds():
    data, _ = fixture_png("form_clean")
    out = pipeline.analyze(data)
    for f in out["fields"]:
        assert 0.5 <= f["confidence"] <= 1.0, f


def test_annotated_png_valid():
    data, _ = fixture_png("form_clean")
    out = pipeline.analyze(data)
    arr = np.frombuffer(out["annotated_png"], np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    assert img is not None
    assert img.shape[1] == pipeline.WARP_W and img.shape[0] == pipeline.WARP_H


def test_summary_counts_consistent():
    data, _ = fixture_png("form_messy")
    out = pipeline.analyze(data)
    s = out["summary"]
    assert s["total_fields"] == len(out["fields"])
    assert s["checkboxes"] + s["bubble_questions"] + (
        1 if s["signature"] != "not_found" else 0) == s["total_fields"]


def test_ambiguity_flags_low_confidence_fields():
    data, _ = fixture_png("form_messy")
    out = pipeline.analyze(data)
    for f in out["fields"]:
        assert "ambiguous" in f, f
        assert f["ambiguous"] == (f["confidence"] < pipeline.AMBIGUITY_T), f
    flagged = [f for f in out["fields"] if f["ambiguous"]]
    assert out["summary"]["needs_review"] == len(flagged)
    # the unanswered bubble row and the borderline signature must be flagged
    kinds = {(f["kind"], f["value"]) for f in flagged}
    assert ("bubble_group", "none") in kinds
    assert ("signature", "absent") in kinds
