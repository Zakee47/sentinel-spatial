"""Run bay_issue (+ issue_severity when an issue is found) on sample bay photos against the REAL API.

python demo.py                      # samples/bay_full.jpg + samples/bay_empty.jpg, reference = bay_full.jpg
python demo.py a.jpg b.jpg --ref r.jpg
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import sentinel_decisions as sd

HERE = Path(__file__).resolve().parent


def fmt(d: sd.Decision) -> str:
    u = d.usage or {}
    det = u.get("input_tokens_details") or {}
    probs = d.answer.get("probabilities")
    top = ""
    if probs:
        top = " probs=" + ", ".join(
            f"{p.get('label', p['value'])}:{p['probability']:.2f}" for p in probs if p["probability"] >= 0.03
        )
    conf = "-" if d.confidence is None else f"{d.confidence:.2f}"
    return (
        f"{d.question:<15} value={d.value!s:<10} conf={conf} policy={d.policy:<7} "
        f"latency={d.latency_s:.2f}s tokens={u.get('input_tokens')} cached={det.get('cached_tokens')}{top}"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "images",
        nargs="*",
        default=[
            str(HERE / "samples/bay_full.jpg"),
            str(HERE / "samples/bay_empty.jpg"),
        ],
    )
    ap.add_argument(
        "--ref",
        default=str(HERE / "samples/bay_full.jpg"),
        help="reference photo of the bay ('' = none)",
    )
    args = ap.parse_args()
    if sd.is_mock():
        print("SENTINEL_DECISIONS_MOCK=1: mock answers, no API calls")
    elif not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not set")
    ref = Path(args.ref).read_bytes() if args.ref else None
    for path in args.images:
        img = Path(path).read_bytes()
        print(f"\n== {Path(path).name} (reference: {Path(args.ref).name if ref else 'none'})")
        d = sd.bay_issue(img, ref)
        print(fmt(d))
        if d.value not in (None, "ok"):
            print(fmt(sd.issue_severity(img, d.answer)))


if __name__ == "__main__":
    main()
