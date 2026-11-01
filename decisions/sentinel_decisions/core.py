"""Request building, transport, threshold policy and logging for the Decisions API."""

from __future__ import annotations

import base64
import json
import logging
import os
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger("sentinel_decisions")

MODEL = "gpt-6-luna"
PROMPT_CACHE_KEY = "sentinel-v1"
PKG_DIR = Path(__file__).resolve().parent
DECISIONS_DIR = PKG_DIR.parent
REPO_ROOT = DECISIONS_DIR.parent

DEFAULT_THRESHOLDS = {"auto": 0.85, "review": 0.55}
DEFAULT_TIMEOUT_S = 2.0

LogSink = Callable[[dict[str, Any]], None]
_log_sink: LogSink | None = None
_lock = threading.Lock()


class DecisionTimeout(Exception):
    pass


# ---------- config + question sets ----------


@lru_cache(maxsize=1)
def site_config() -> dict[str, Any]:
    path = Path(os.environ.get("SENTINEL_SITE_CONFIG", REPO_ROOT / "config" / "site.yaml"))
    try:
        return yaml.safe_load(path.read_text()) or {}
    except FileNotFoundError:
        log.warning("site config %s not found; using default thresholds", path)
        return {}


def thresholds(question: str) -> dict[str, float]:
    t = site_config().get("thresholds", {}).get(question)
    return dict(t) if isinstance(t, dict) else dict(DEFAULT_THRESHOLDS)


def timeout_s() -> float:
    env = os.environ.get("SENTINEL_DECISION_TIMEOUT_S")
    if env:
        return float(env)
    return float(site_config().get("thresholds", {}).get("decision_timeout_s", DEFAULT_TIMEOUT_S))


def questions_dir() -> Path:
    return Path(os.environ.get("SENTINEL_QUESTIONS_DIR", DECISIONS_DIR / "questions"))


@lru_cache(maxsize=32)
def question_def(name: str) -> dict[str, Any]:
    return json.loads((questions_dir() / f"{name}.json").read_text())


@lru_cache(maxsize=1)
def shared_context() -> str:
    return json.loads((questions_dir() / "_shared_context.json").read_text())["text"]


# ---------- request building ----------


def _mime(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def image_part(data: bytes, detail: str = "auto") -> dict[str, Any]:
    b64 = base64.b64encode(data).decode()
    return {
        "type": "input_image",
        "image_url": f"data:{_mime(data)};base64,{b64}",
        "detail": detail,
    }


def text_part(text: str) -> dict[str, Any]:
    return {"type": "input_text", "text": text}


def build_question(
    qdef: dict[str, Any],
    instruction_images: list[tuple[str, bytes]] | None = None,
    choices: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    q: dict[str, Any] = {"type": qdef["type"], "name": qdef["name"]}
    if instruction_images:
        parts: list[dict[str, Any]] = [text_part(qdef["instructions"])]
        for caption, img in instruction_images:
            parts += [text_part(caption), image_part(img)]
        q["instructions"] = parts
    else:
        q["instructions"] = qdef["instructions"]
    if qdef["type"] == "choice":
        q["choices"] = choices if choices is not None else qdef["choices"]
    elif qdef["type"] == "score":
        q["levels"] = qdef["levels"]
    return q


def build_request(
    name: str,
    images: list[bytes] | None = None,
    json_data: Any = None,
    text: str | None = None,
    instruction_images: list[tuple[str, bytes]] | None = None,
    choices: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Shared context (cache prefix) first, then this request's evidence, then the question."""
    qdef = question_def(name)
    evidence: list[dict[str, Any]] = [text_part(f"Evidence: {qdef['input_text']}")]
    if text is not None:
        evidence.append(text_part(text))
    evidence += [image_part(img) for img in images or []]
    if json_data is not None:
        evidence.append({"type": "input_json", "data": json_data})
    return {
        "model": MODEL,
        "input": [
            {
                "role": "developer",
                "content": [
                    {
                        **text_part(shared_context()),
                        "prompt_cache_breakpoint": {"mode": "explicit"},
                    }
                ],
            },
            {"role": "user", "content": evidence},
        ],
        "questions": [build_question(qdef, instruction_images, choices)],
        "prompt_cache_key": PROMPT_CACHE_KEY,
    }


# ---------- transport ----------

_client: Any = None


def _get_client() -> Any:
    global _client
    with _lock:
        if _client is None:
            from openai import OpenAI

            _client = OpenAI(max_retries=0)
        return _client


def transport(payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    """POST /v1/decisions. Raises DecisionTimeout on timeout. Tests monkeypatch this."""
    import openai

    client = _get_client()
    try:
        if hasattr(client, "decisions"):
            resp = client.decisions.create(**payload, timeout=timeout)
            return resp.model_dump() if hasattr(resp, "model_dump") else dict(resp)
        return client.post("/decisions", body=payload, cast_to=dict, options={"timeout": timeout})
    except openai.APITimeoutError as e:
        raise DecisionTimeout(str(e)) from e


# ---------- policy ----------


def policy_for(question: str, answer: dict[str, Any]) -> tuple[Any, float | None, str]:
    """Return (value, confidence, policy) for one raw answer."""
    kind = answer.get("type")
    if kind == "predicate":
        value = conf = float(answer["probability"])
    elif kind == "choice":
        value, conf = answer.get("choice"), answer.get("confidence")
        if value == "unclear":
            return value, conf, "unclear"
    elif kind == "score":
        value, conf = answer.get("score"), answer.get("confidence")
    else:  # refusal, timeout, error, unknown
        return None, None, "unclear"
    if conf is None:
        return value, None, "unclear"
    t = thresholds(question)
    if conf >= t["auto"]:
        pol = "auto"
    elif conf >= t["review"]:
        pol = "review"
    else:
        pol = "ignore"
    return value, float(conf), pol


# ---------- logging ----------


def set_log_sink(sink: LogSink | None) -> None:
    """Register a callable that receives every decisions_log row (dict)."""
    global _log_sink
    _log_sink = sink


def logs_dir() -> Path:
    return Path(os.environ.get("SENTINEL_DECISIONS_LOG_DIR", DECISIONS_DIR / "logs"))


def _db_insert(row: dict[str, Any]) -> None:
    url = os.environ.get("DATABASE_URL")
    if not url:
        return
    try:
        import psycopg  # type: ignore[import-not-found]
    except ImportError:
        return
    try:
        with psycopg.connect(url, connect_timeout=2) as conn:
            conn.execute(
                "INSERT INTO decisions_log (question, latency_s, input_tokens, cached_tokens, answer, policy)"
                " VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    row["question"],
                    row["latency_s"],
                    row["input_tokens"],
                    row["cached_tokens"],
                    json.dumps(row["answer"]),
                    row["policy"],
                ),
            )
    except Exception as e:  # noqa: BLE001 - logging must never break a decision
        log.warning("decisions_log insert failed: %s", e)


def log_row(row: dict[str, Any]) -> None:
    try:
        d = logs_dir()
        d.mkdir(parents=True, exist_ok=True)
        day = datetime.now(UTC).strftime("%Y-%m-%d")
        with _lock, open(d / f"decisions-{day}.jsonl", "a") as f:
            f.write(json.dumps(row) + "\n")
    except OSError as e:
        log.warning("decisions jsonl log failed: %s", e)
    if _log_sink is not None:
        try:
            _log_sink(row)
        except Exception as e:  # noqa: BLE001
            log.warning("decisions log_sink failed: %s", e)
    _db_insert(row)


# ---------- one call ----------


def ask(name: str, **request_kwargs: Any) -> dict[str, Any]:
    """Run one question end to end. Returns the fields of a `Decision`."""
    payload = build_request(name, **request_kwargs)
    t0 = time.monotonic()
    usage: dict[str, Any] = {}
    try:
        resp = transport(payload, timeout_s())
        usage = resp.get("usage") or {}
        answers = resp.get("answers") or []
        answer = next(
            (a for a in answers if a.get("name") == name),
            answers[0] if answers else {"type": "error", "error": "no answers"},
        )
    except DecisionTimeout:
        answer = {"type": "timeout", "name": name, "timeout_s": timeout_s()}
    except Exception as e:  # noqa: BLE001 - any API failure -> unclear
        log.warning("decision %s failed: %s", name, e)
        answer = {
            "type": "error",
            "name": name,
            "error": f"{type(e).__name__}: {e}"[:500],
        }
    latency = time.monotonic() - t0
    value, conf, pol = policy_for(name, answer)
    details = usage.get("input_tokens_details") or {}
    log_row(
        {
            "ts": datetime.now(UTC).isoformat(),
            "question": name,
            "question_version": question_def(name).get("version"),
            "latency_s": round(latency, 4),
            "input_tokens": usage.get("input_tokens"),
            "cached_tokens": details.get("cached_tokens"),
            "cache_write_tokens": details.get("cache_write_tokens"),
            "answer": answer,
            "policy": pol,
        }
    )
    return {
        "question": name,
        "answer": answer,
        "value": value,
        "confidence": conf,
        "policy": pol,
        "latency_s": latency,
        "usage": usage,
    }
