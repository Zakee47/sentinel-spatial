from __future__ import annotations

import json
from typing import Any

import pytest

import sentinel_decisions as sd
from sentinel_decisions import core

JPEG = b"\xff\xd8\xff\xe0fakejpeg"
PNG = b"\x89PNG\r\n\x1a\nfakepng"


class FakeTransport:
    def __init__(self, response: dict[str, Any] | Exception) -> None:
        self.response = response
        self.calls: list[tuple[dict[str, Any], float]] = []

    def __call__(self, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        self.calls.append((payload, timeout))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def resp(answer: dict[str, Any], cached: int = 0) -> dict[str, Any]:
    return {
        "answers": [answer],
        "model": "gpt-6-luna",
        "usage": {
            "input_tokens": 1500,
            "input_tokens_details": {"cached_tokens": cached, "cache_write_tokens": 0},
        },
    }


def choice(name: str, value: str, conf: float) -> dict[str, Any]:
    return {
        "type": "choice",
        "name": name,
        "choice": value,
        "confidence": conf,
        "probabilities": [],
    }


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.delenv("SENTINEL_DECISIONS_MOCK", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SENTINEL_DECISION_TIMEOUT_S", raising=False)
    monkeypatch.setenv("SENTINEL_DECISIONS_LOG_DIR", str(tmp_path / "logs"))
    core.set_log_sink(None)


def fake(monkeypatch: pytest.MonkeyPatch, response: dict[str, Any] | Exception) -> FakeTransport:
    t = FakeTransport(response)
    monkeypatch.setattr(core, "transport", t)
    return t


# ---------- policy ----------


@pytest.mark.parametrize(
    ("conf", "policy"),
    [
        (0.95, "auto"),
        (0.85, "auto"),
        (0.84, "review"),
        (0.55, "review"),
        (0.54, "ignore"),
        (0.1, "ignore"),
    ],
)
def test_bay_issue_choice_policy_uses_site_thresholds(
    monkeypatch: pytest.MonkeyPatch, conf: float, policy: str
) -> None:
    fake(monkeypatch, resp(choice("bay_issue", "empty", conf)))
    d = sd.bay_issue(JPEG)
    assert (d.value, d.confidence, d.policy) == ("empty", conf, policy)


@pytest.mark.parametrize(("p", "policy"), [(0.9, "auto"), (0.6, "review"), (0.2, "ignore")])
def test_predicate_policy(monkeypatch: pytest.MonkeyPatch, p: float, policy: str) -> None:
    fake(
        monkeypatch,
        resp({"type": "predicate", "name": "holding_product", "probability": p}),
    )
    d = sd.holding_product(JPEG, JPEG)
    assert d.value == p and d.confidence == p and d.policy == policy


def test_reach_outcome_thresholds_differ(monkeypatch: pytest.MonkeyPatch) -> None:
    fake(monkeypatch, resp(choice("reach_outcome", "in_basket", 0.82)))
    assert sd.reach_outcome(JPEG, JPEG, JPEG).policy == "auto"  # reach_outcome auto=0.80


def test_choice_unclear_value_is_unclear(monkeypatch: pytest.MonkeyPatch) -> None:
    fake(monkeypatch, resp(choice("reach_outcome", "unclear", 0.99)))
    assert sd.reach_outcome(JPEG, JPEG, JPEG).policy == "unclear"


def test_score(monkeypatch: pytest.MonkeyPatch) -> None:
    fake(
        monkeypatch,
        resp({"type": "score", "name": "issue_severity", "score": 2.3, "confidence": 0.7}),
    )
    d = sd.issue_severity(JPEG, {"choice": "empty"})
    assert d.value == 2.3 and d.policy == "review"


# ---------- refusal / timeout / error ----------


def test_refusal_is_unclear(monkeypatch: pytest.MonkeyPatch) -> None:
    fake(monkeypatch, resp({"type": "refusal", "name": "bay_issue"}))
    d = sd.bay_issue(JPEG)
    assert d.policy == "unclear" and d.value is None and d.confidence is None
    assert d.to_event_decision() == {
        "question": "bay_issue",
        "answer": {"type": "refusal", "name": "bay_issue"},
        "policy": "unclear",
    }


def test_timeout_is_unclear_and_uses_config_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    t = fake(monkeypatch, core.DecisionTimeout("slow"))
    d = sd.drone_next_action(JPEG, {"bay": "bay-B-01"})
    assert d.policy == "unclear" and d.answer["type"] == "timeout"
    assert t.calls[0][1] == 2.0  # config/site.yaml decision_timeout_s


def test_sdk_timeout_maps_to_decision_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx
    import openai

    class Client:
        class decisions:
            @staticmethod
            def create(**_: Any) -> Any:
                raise openai.APITimeoutError(request=httpx.Request("POST", "https://x/v1/decisions"))

    monkeypatch.setattr(core, "_client", Client())
    with pytest.raises(core.DecisionTimeout):
        core.transport({"model": "m"}, 0.1)
    d = sd.bay_issue(JPEG)
    assert d.policy == "unclear" and d.answer["type"] == "timeout"


def test_api_error_is_unclear(monkeypatch: pytest.MonkeyPatch) -> None:
    fake(monkeypatch, RuntimeError("500"))
    d = sd.bay_issue(JPEG)
    assert d.policy == "unclear" and d.answer["type"] == "error"


# ---------- request shape ----------


def test_bay_issue_request_shape_with_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    t = fake(monkeypatch, resp(choice("bay_issue", "ok", 0.9)))
    sd.bay_issue(JPEG, reference_jpeg=PNG)
    payload, _ = t.calls[0]
    assert payload["model"] == "gpt-6-luna"
    dev, user = payload["input"]
    assert dev["role"] == "developer" and dev["content"][0]["prompt_cache_breakpoint"] == {"mode": "explicit"}
    imgs = [p for p in user["content"] if p["type"] == "input_image"]
    assert len(imgs) == 1 and imgs[0]["image_url"].startswith("data:image/jpeg;base64,")
    (q,) = payload["questions"]
    assert q["type"] == "choice" and q["name"] == "bay_issue"
    assert [c["value"] for c in q["choices"]] == [
        "ok",
        "low_stock",
        "empty",
        "misplaced",
        "label_issue",
        "obstruction",
        "other",
    ]
    assert isinstance(q["instructions"], list)
    assert q["instructions"][-1]["image_url"].startswith("data:image/png;base64,")


def test_bay_issue_without_reference_has_string_instructions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    t = fake(monkeypatch, resp(choice("bay_issue", "ok", 0.9)))
    sd.bay_issue(JPEG)
    assert isinstance(t.calls[0][0]["questions"][0]["instructions"], str)


def test_shared_prefix_identical_and_long(monkeypatch: pytest.MonkeyPatch) -> None:
    t = fake(monkeypatch, resp(choice("x", "ok", 0.9)))
    sd.bay_issue(JPEG)
    sd.reach_outcome(JPEG, JPEG, JPEG)
    a, b = (c[0]["input"][0] for c in t.calls)
    assert a == b
    assert len(a["content"][0]["text"]) > 4500  # ~>1024 tokens
    assert t.calls[0][0]["prompt_cache_key"] == "sentinel-v1"


def test_json_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    t = fake(monkeypatch, resp(choice("drone_next_action", "next_bay", 0.9)))
    sd.drone_next_action(JPEG, {"current_bay": "bay-B-02", "battery_pct": 80})
    parts = t.calls[0][0]["input"][1]["content"]
    assert {
        "type": "input_json",
        "data": {"patrol_state": {"current_bay": "bay-B-02", "battery_pct": 80}},
    } in parts
    q = t.calls[0][0]["questions"][0]
    assert {c["value"] for c in q["choices"]} == {
        "next_bay",
        "move_closer",
        "rescan",
        "flag_and_continue",
        "return_home",
        "abort",
    }


def test_score_levels_and_multi_images(monkeypatch: pytest.MonkeyPatch) -> None:
    t = fake(
        monkeypatch,
        resp(
            {
                "type": "score",
                "name": "engagement_level",
                "score": 1.0,
                "confidence": 0.9,
            }
        ),
    )
    sd.engagement_level([JPEG, JPEG, JPEG])
    payload = t.calls[0][0]
    assert [lv["label"] for lv in payload["questions"][0]["levels"]] == [
        "passing",
        "glancing",
        "browsing",
        "comparing",
    ]
    assert sum(p["type"] == "input_image" for p in payload["input"][1]["content"]) == 3


def test_ask_intent_builds_choices_from_intents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    t = fake(monkeypatch, resp(choice("ask_intent", "underperforming_shelf", 0.9)))
    intents = [
        {"value": "underperforming_shelf", "description": "Which shelf sold worst"},
        {"value": "open_tasks", "description": "List tasks"},
    ]
    d = sd.ask_intent("which shelf underperformed?", intents)
    q = t.calls[0][0]["questions"][0]
    assert q["choices"] == intents and d.value == "underperforming_shelf"
    assert any("which shelf underperformed?" in p.get("text", "") for p in t.calls[0][0]["input"][1]["content"])


def test_ask_intent_empty_intents_no_call(monkeypatch: pytest.MonkeyPatch) -> None:
    t = fake(monkeypatch, resp(choice("ask_intent", "x", 0.9)))
    assert sd.ask_intent("hi", []).policy == "unclear" and not t.calls


# ---------- logging + mock ----------


def test_logging_jsonl_and_sink(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    fake(monkeypatch, resp(choice("bay_issue", "empty", 0.9), cached=1300))
    rows: list[dict[str, Any]] = []
    sd.set_log_sink(rows.append)
    d = sd.bay_issue(JPEG)
    assert d.usage["input_tokens_details"]["cached_tokens"] == 1300
    assert rows[0]["question"] == "bay_issue" and rows[0]["cached_tokens"] == 1300 and rows[0]["policy"] == "auto"
    (f,) = (tmp_path / "logs").glob("*.jsonl")
    assert json.loads(f.read_text().splitlines()[0])["input_tokens"] == 1500


def test_broken_sink_does_not_break_decision(monkeypatch: pytest.MonkeyPatch) -> None:
    fake(monkeypatch, resp(choice("bay_issue", "ok", 0.9)))

    def boom(_: dict[str, Any]) -> None:
        raise ValueError("db down")

    sd.set_log_sink(boom)
    assert sd.bay_issue(JPEG).policy == "auto"


def test_mock_mode_makes_no_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SENTINEL_DECISIONS_MOCK", "1")
    t = fake(monkeypatch, resp(choice("x", "ok", 0.9)))
    assert sd.bay_issue(JPEG).value == "ok"
    assert sd.reach_outcome(JPEG, JPEG, JPEG).value == "back_on_shelf"
    assert sd.ask_intent("q", [{"value": "a", "description": "b"}]).value == "a"
    assert not t.calls
