#!/usr/bin/env python3
"""Honest evaluation: run the pipeline on the synthetic fixtures and compare
against their ground-truth JSON sidecars. Prints per-fixture and overall
field-level accuracy. These are self-authored synthetic fixtures, NOT real
documents — the numbers measure fixture performance only."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from formlens.pipeline import analyze

ROOT = Path(__file__).resolve().parent.parent / "sample_inputs"
LETTER = {"A": 0, "B": 1, "C": 2, "D": 3}


def evaluate(name):
    gt = json.loads((ROOT / f"{name}.json").read_text())
    res = analyze((ROOT / f"{name}.png").read_bytes())
    fields = res["fields"]
    checks = [f for f in fields if f["kind"] == "checkbox"]
    bubbles = [f for f in fields if f["kind"] == "bubble_group"]
    sig = next((f for f in fields if f["kind"] == "signature"), None)

    total = correct = 0
    rows = []
    for i, f in enumerate(checks):
        total += 1
        want = i in gt["checkboxes_checked"]
        got = f["value"] == "checked"
        ok = want == got
        correct += ok
        rows.append((f"checkbox {i + 1}", ok, f["confidence"]))
    for i, f in enumerate(bubbles):
        total += 1
        want = gt["bubble_answers"][i] if i < len(gt["bubble_answers"]) else None
        got = LETTER.get(f["value"])
        ok = want == got
        correct += ok
        rows.append((f"bubble Q{i + 1}", ok, f["confidence"]))
    total += 1
    ok = (sig is not None and
          (sig["value"] == "present") == gt["signature_present"])
    correct += ok
    rows.append(("signature", ok, sig["confidence"] if sig else 0.0))
    amb = sum(1 for f in fields if f["ambiguous"])
    return {"fixture": name, "correct": correct, "total": total,
            "rectified": res["summary"]["rectified"],
            "ambiguous": amb, "rows": rows}


def main():
    names = ["form_clean", "form_rotated", "form_shadow", "form_messy"]
    results = [evaluate(n) for n in names]
    tc = sum(r["correct"] for r in results)
    tt = sum(r["total"] for r in results)
    print(f"{'fixture':<14}{'fields':>8}{'correct':>9}{'rectified':>11}{'review':>8}")
    for r in results:
        print(f"{r['fixture']:<14}{r['total']:>8}{r['correct']:>9}"
              f"{str(r['rectified']):>11}{r['ambiguous']:>8}")
    print(f"{'TOTAL':<14}{tt:>8}{tc:>9}"
          f"{'':>11}{'':>8}")
    print(f"\nfield-level accuracy on synthetic fixtures: {tc}/{tt} "
          f"({100.0 * tc / tt:.1f}%)")
    for r in results:
        bad = [lbl for lbl, ok, _ in r["rows"] if not ok]
        if bad:
            print(f"  {r['fixture']}: MISSED -> {', '.join(bad)}")
    (ROOT.parent / "scripts" / "eval_results.json").write_text(
        json.dumps([{k: r[k] for k in ("fixture", "correct", "total",
                                      "rectified", "ambiguous")} for r in results],
                   indent=2))


if __name__ == "__main__":
    main()
