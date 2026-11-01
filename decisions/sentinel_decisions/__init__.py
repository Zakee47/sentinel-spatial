"""Sentinel wrapper around the OpenAI Decisions API (POST /v1/decisions, model gpt-6-luna).

CONTRACT: these signatures are fixed. The decisions/ workstream replaces the mock bodies with
real calls; perception/ and drone/ import them as-is. Every function returns a `Decision`.
Set SENTINEL_DECISIONS_MOCK=1 for deterministic fake answers (no network).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Literal

Policy = Literal["auto", "review", "ignore", "unclear"]


@dataclass
class Decision:
    question: str
    answer: dict[str, Any]  # raw answer object from the API (type, probability/value/score, ...)
    value: Any  # convenience: probability (predicate), chosen value (choice) or score (score)
    confidence: float | None
    policy: Policy  # from config/site.yaml thresholds; refusal/timeout -> "unclear"
    latency_s: float
    usage: dict[str, Any] = field(default_factory=dict)

    def to_event_decision(self) -> dict[str, Any]:
        return {"question": self.question, "answer": self.answer, "policy": self.policy}


def is_mock() -> bool:
    return os.environ.get("SENTINEL_DECISIONS_MOCK") == "1"


def _mock(question: str, value: Any, confidence: float = 0.9) -> Decision:
    return Decision(question, {"type": "mock", "value": value}, value, confidence, "auto", 0.0)


def holding_product(hand_jpeg: bytes, shelf_jpeg: bytes) -> Decision:
    """predicate: is the shopper holding a product taken from this shelf?"""
    return _mock("holding_product", 0.9)


def reach_outcome(before_jpeg: bytes, after_jpeg: bytes, hand_jpeg: bytes) -> Decision:
    """choice: in_basket | back_on_shelf | still_holding | unclear"""
    return _mock("reach_outcome", "back_on_shelf")


def engagement_level(crops_jpeg: list[bytes]) -> Decision:
    """score: passing < glancing < browsing < comparing"""
    return _mock("engagement_level", 2.0)


def bay_issue(bay_jpeg: bytes, reference_jpeg: bytes | None = None) -> Decision:
    """choice: ok | low_stock | empty | misplaced | label_issue | obstruction | other"""
    return _mock("bay_issue", "ok")


def issue_severity(bay_jpeg: bytes, bay_issue_answer: dict[str, Any]) -> Decision:
    """score: none < minor < act_today < act_now (separate request, only when bay_issue != ok)"""
    return _mock("issue_severity", 2.0)


def drone_next_action(bay_jpeg: bytes, patrol_state: dict[str, Any]) -> Decision:
    """choice: next_bay | move_closer | rescan | flag_and_continue | return_home | abort.
    Advisory only: drone/'s safety supervisor validates before the flight loop executes it."""
    return _mock("drone_next_action", "next_bay")


def ask_intent(question: str, intents: list[dict[str, str]]) -> Decision:
    """choice over the given intents [{value, description}] for the 'Ask Sentinel' box."""
    return _mock("ask_intent", intents[0]["value"] if intents else "unknown")
