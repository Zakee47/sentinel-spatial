"""Decision worker: runs the Decisions API calls in a background thread.

The flight loop submits a job and later polls `result()`; it never blocks on the network.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

import sentinel_decisions as sd

log = logging.getLogger("drone.decide")
SEVERITY = ["none", "minor", "act_today", "act_now"]
ISSUES = ("ok", "low_stock", "empty", "misplaced", "label_issue", "obstruction", "other")


@dataclass
class BayVerdict:
    bay_id: str
    issue: str  # ok | low_stock | empty | misplaced | label_issue | obstruction | other | unclear
    severity: str  # none | minor | act_today | act_now
    severity_score: float
    next_action: str
    confidence: float | None
    policy: str
    decision: dict[str, Any]  # bay_issue decision for the event
    latency_s: float
    sim_truth_used: bool = False


def severity_label(value: Any) -> tuple[str, float]:
    if isinstance(value, str) and value in SEVERITY:
        return value, float(SEVERITY.index(value))
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "minor", 1.0
    idx = max(0, min(3, round(v)))
    return SEVERITY[idx], v


def inspect_bay(bay_id: str, jpeg: bytes, reference: bytes | None, patrol_state: dict[str, Any],
                truth: str | None = None) -> BayVerdict:
    t0 = time.monotonic()
    d = sd.bay_issue(jpeg, reference)
    issue = str(d.value)
    used_truth = False
    # Mock decisions always answer "ok". In SIM + mock mode we substitute the simulator's ground
    # truth so the demo shows findings; clearly labelled in the decision answer.
    if sd.is_mock() and truth is not None and d.answer.get("type") == "mock":
        issue, used_truth = truth, True
        d = sd.Decision("bay_issue", {"type": "sim_truth", "value": truth}, truth, 0.95, "auto", d.latency_s)
    if d.policy == "unclear" or issue not in ISSUES:
        issue = "unclear"
    sev, score = "none", 0.0
    if issue not in ("ok", "unclear"):
        sev, score = severity_label(sd.issue_severity(jpeg, d.answer).value)
    nxt = sd.drone_next_action(jpeg, {**patrol_state, "bay": bay_id, "issue": issue})
    return BayVerdict(bay_id, issue, sev, score, str(nxt.value), d.confidence, d.policy,
                      d.to_event_decision(), time.monotonic() - t0, used_truth)


class DecisionWorker:
    def __init__(self) -> None:
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="decide")
        self._fut: Future[BayVerdict] | None = None
        self._lock = threading.Lock()

    def submit(self, *args: Any, **kw: Any) -> None:
        with self._lock:
            self._fut = self._pool.submit(inspect_bay, *args, **kw)

    def result(self) -> BayVerdict | Exception | None:
        """Non-blocking: verdict, the exception it raised, or None if still running."""
        with self._lock:
            f = self._fut
        if f is None or not f.done():
            return None
        exc = f.exception()
        return exc if exc is not None else f.result()

    def clear(self) -> None:
        with self._lock:
            self._fut = None

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
