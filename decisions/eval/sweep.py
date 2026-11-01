"""Label/threshold sweep: run one question over a labelled CSV and print precision/recall per threshold.

CSV columns: path,label   (paths relative to the CSV file are fine)
- predicate questions: label is 1/0 (or true/false); the score is the answer's probability.
- choice questions: label is the correct choice value; pass --positive VALUE to treat that value as
  the positive class (score = its probability). Default positive: every value except --negative (ok).

    python eval/sweep.py --question bay_issue --csv eval/sample_labels.csv --ref samples/bay_full.jpg
"""

from __future__ import annotations

import argparse
import csv
import os
from pathlib import Path
from typing import Any

from sentinel_decisions import core

TRUE = {"1", "true", "yes", "y", "t"}


def positive_score(answer: dict[str, Any], positive: str | None, negative: str) -> float | None:
    kind = answer.get("type")
    if kind == "predicate":
        return float(answer["probability"])
    if kind == "choice":
        probs = {p["value"]: p["probability"] for p in answer.get("probabilities") or []}
        if not probs:
            return None
        if positive:
            return float(probs.get(positive, 0.0))
        return float(1.0 - probs.get(negative, 0.0))
    return None


def is_positive(label: str, qtype: str, positive: str | None, negative: str) -> bool:
    if qtype == "predicate":
        return label.strip().lower() in TRUE
    return label == positive if positive else label != negative


def sweep(rows: list[tuple[float | None, bool]], thresholds: list[float]) -> list[dict[str, Any]]:
    out = []
    for t in thresholds:
        tp = sum(1 for s, y in rows if s is not None and s >= t and y)
        fp = sum(1 for s, y in rows if s is not None and s >= t and not y)
        fn = sum(1 for s, y in rows if (s is None or s < t) and y)
        prec = tp / (tp + fp) if tp + fp else float("nan")
        rec = tp / (tp + fn) if tp + fn else float("nan")
        out.append(
            {
                "threshold": t,
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "precision": prec,
                "recall": rec,
            }
        )
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--question",
        required=True,
        help="question name, e.g. bay_issue or holding_product",
    )
    ap.add_argument("--csv", required=True)
    ap.add_argument("--positive", default=None, help="choice value counted as positive")
    ap.add_argument(
        "--negative",
        default="ok",
        help="choice value counted as negative when --positive is unset",
    )
    ap.add_argument(
        "--ref",
        default=None,
        help="reference image put in the question instructions (bay_issue)",
    )
    ap.add_argument("--thresholds", default="0.3,0.4,0.5,0.55,0.6,0.7,0.8,0.85,0.9,0.95")
    args = ap.parse_args()

    if os.environ.get("SENTINEL_DECISIONS_MOCK") == "1":
        raise SystemExit("sweep needs the real API; unset SENTINEL_DECISIONS_MOCK")
    qtype = core.question_def(args.question)["type"]
    if qtype == "score":
        raise SystemExit("score questions are not supported by the sweep")
    csv_path = Path(args.csv)
    ref = (
        [
            (
                core.question_def(args.question).get("reference_text", "Reference image:"),
                Path(args.ref).read_bytes(),
            )
        ]
        if args.ref
        else None
    )
    rows: list[tuple[float | None, bool]] = []
    with csv_path.open() as f:
        for rec in csv.DictReader(f):
            p = Path(rec["path"])
            img = (p if p.is_absolute() or p.exists() else csv_path.parent / p).read_bytes()
            r = core.ask(args.question, images=[img], instruction_images=ref)
            s = positive_score(r["answer"], args.positive, args.negative)
            y = is_positive(rec["label"], qtype, args.positive, args.negative)
            rows.append((s, y))
            shown = "-" if s is None else f"{s:.2f}"
            print(
                f"{rec['path']:<40} label={rec['label']:<10} answer={r['value']!s:<10} score={shown} latency={r['latency_s']:.2f}s"
            )
    print(f"\n{args.question}: n={len(rows)} positives={sum(y for _, y in rows)}")
    print(f"{'threshold':>9} {'tp':>3} {'fp':>3} {'fn':>3} {'precision':>9} {'recall':>6}")
    for m in sweep(rows, [float(x) for x in args.thresholds.split(",")]):
        print(
            f"{m['threshold']:>9.2f} {m['tp']:>3} {m['fp']:>3} {m['fn']:>3} {m['precision']:>9.2f} {m['recall']:>6.2f}"
        )
    t = core.thresholds(args.question)
    print(f"current site.yaml thresholds for {args.question}: auto={t['auto']} review={t['review']}")


if __name__ == "__main__":
    main()
