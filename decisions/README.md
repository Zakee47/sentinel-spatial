# decisions/ — Sentinel wrapper around the OpenAI Decisions API (W2)

`sentinel_decisions` calls `POST /v1/decisions` (model `gpt-6-luna`) for every judgement call. Signatures and the
`Decision` dataclass in `sentinel_decisions/__init__.py` are the fixed contract; perception/ and drone/ import them as-is.

```bash
pip install -e 'decisions[dev]'            # add [db] for decisions_log inserts via DATABASE_URL
cd decisions
python -m pytest -q                       # HTTP mocked: policy, refusal, timeout, request shape, logging
python demo.py                            # REAL API: bay_issue on samples/bay_full.jpg + bay_empty.jpg
python eval/sweep.py --question bay_issue --csv eval/sample_labels.csv --ref samples/bay_full.jpg
SENTINEL_DECISIONS_MOCK=1 python demo.py  # no network, deterministic answers
```

```python
import sentinel_decisions as sd

d = sd.bay_issue(bay_jpeg, reference_jpeg=ref_jpeg)  # -> Decision(value="empty", confidence=0.71, policy="review", ...)
event["decision"] = d.to_event_decision()
```

## How it works
| Function | Type | Evidence (`input`) | Question extras |
| --- | --- | --- | --- |
| `holding_product(hand, shelf)` | predicate | hand crop, shelf crop | |
| `reach_outcome(before, after, hand)` | choice | 3 crops | |
| `engagement_level(crops)` | score | crop sequence | levels passing→comparing |
| `bay_issue(bay, reference=None)` | choice | bay crop | reference photo as an image part in `instructions` |
| `issue_severity(bay, bay_issue_answer)` | score | bay crop + `input_json` | |
| `drone_next_action(bay, patrol_state)` | choice | bay crop + `input_json` | advisory only; drone/'s supervisor validates |
| `ask_intent(question, intents)` | choice | question text | choices built from the passed intents |

- **Question sets:** versioned JSON in `questions/<name>.json` (`version`, `instructions`, `choices`/`levels`). Edit there, bump `version`; the version is logged with every call.
- **Prompt caching:** every request starts with the same developer message (`questions/_shared_context.json`, ~1.3k tokens: site, privacy, label definitions) marked with an explicit `prompt_cache_breakpoint`, plus `prompt_cache_key="sentinel-v1"`. Cached tokens are in `Decision.usage["input_tokens_details"]["cached_tokens"]` and in the logs.
- **Policy** (`config/site.yaml` → `thresholds`): `confidence ≥ auto` → `auto`, `≥ review` → `review`, else `ignore`. Predicates use `probability`; choice/score use the answer's `confidence`. Questions without thresholds in site.yaml use 0.85/0.55. A choice of `unclear`, a refusal, a timeout (`decision_timeout_s`, 2.0 s, no retries) or any API error → `unclear` (never raises).
- **Logging:** every call appends a JSON line to `decisions/logs/decisions-YYYY-MM-DD.jsonl` (gitignored), calls the optional sink from `sd.set_log_sink(callable)` (row dict matching `decisions_log`), and inserts into `decisions_log` when `DATABASE_URL` is set and `psycopg` is installed. Logging failures never break a decision.
- **Env:** `OPENAI_API_KEY`, `SENTINEL_DECISIONS_MOCK=1`, optional `SENTINEL_DECISION_TIMEOUT_S`, `SENTINEL_SITE_CONFIG`, `SENTINEL_QUESTIONS_DIR`, `SENTINEL_DECISIONS_LOG_DIR`, `DATABASE_URL`.
- Question JSON and site.yaml are located relative to the source tree, so install with `pip install -e`.

## Samples
`samples/make_samples.py` draws synthetic rack-bay photos (`full`, `empty`, `low_stock`, `misplaced`) used by the demo and the sweep.
