"""Sentinel FastAPI server: implements every REST + WebSocket endpoint in contracts/API.md."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Body, FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict

from . import db, logic
from .config import REPO_ROOT, load_site, raw_site
from .ids import ulid

log = logging.getLogger("sentinel.server")

# --------------------------------------------------------------------------------------------
# Models (contracts/API.md)
# --------------------------------------------------------------------------------------------


class EventIn(BaseModel):
    event_id: str | None = None
    ts: datetime | None = None
    site_id: str | None = None
    zone_id: str
    type: Literal[
        "pass_by",
        "look",
        "interest",
        "pick_up",
        "put_back",
        "kept",
        "bay_issue",
        "hazard",
        "task",
        "patrol",
    ]
    product_id: str | None = None
    x: float | None = None
    y: float | None = None
    z: float | None = None
    source: str = "sim"
    track_id: str | None = None
    decision: dict[str, Any] | None = None
    confidence: float | None = None
    crop_ref: str | None = None
    payload: dict[str, Any] | None = None


class TaskIn(BaseModel):
    zone_id: str
    kind: str
    severity: float | None = None
    source_event: str | None = None
    note: str | None = None
    assignee: str | None = None


class TaskPatch(BaseModel):
    status: str | None = None
    assignee: str | None = None
    note: str | None = None


class ReviewIn(BaseModel):
    verdict: Literal["confirm", "reject"]
    label: str | None = None


class DroneState(BaseModel):
    model_config = ConfigDict(
        extra="allow"
    )  # drone/ may add piloted, flight, fix_source, ...

    ts: str | None = None
    mode: Literal["sim", "live"] = "sim"
    state: Literal[
        "IDLE", "TAKEOFF", "GOTO_BAY", "INSPECT", "DECIDE", "RETURN", "LAND", "HOLD"
    ] = "IDLE"
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    yaw_deg: float = 0.0
    battery_pct: float = 100.0
    current_bay: str | None = None
    last_decision: dict[str, Any] | None = None
    stop_requested: bool = False
    mission_id: str | None = None
    feed_url: str | None = None


class MissionIn(BaseModel):
    bays: list[str]
    reason: str = ""
    requested_by: Literal["agent", "user"] = "user"


class AskIn(BaseModel):
    question: str


class AgentRunIn(BaseModel):
    goal: str


# --------------------------------------------------------------------------------------------
# Hub: WS fan-out, replay recorder, throttled heatmap
# --------------------------------------------------------------------------------------------


class Hub:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()
        self.t0 = time.monotonic()
        self.record_path = os.environ.get("SENTINEL_RECORD") or None
        self._record_fh = None
        self.heatmap_dirty = False

    def start_recording(self) -> None:
        if self.record_path:
            path = Path(self.record_path)
            if not path.is_absolute():
                path = REPO_ROOT / path
            path.parent.mkdir(parents=True, exist_ok=True)
            self._record_fh = path.open("w")
            self.t0 = time.monotonic()
            log.info("recording WS messages to %s", path)

    def close(self) -> None:
        if self._record_fh:
            self._record_fh.close()

    async def broadcast(self, kind: str, data: Any) -> None:
        msg = {"kind": kind, "data": data}
        if self._record_fh:
            self._record_fh.write(
                json.dumps({"t": round(time.monotonic() - self.t0, 3), "msg": msg})
                + "\n"
            )
            self._record_fh.flush()
        text = json.dumps(msg)
        dead = []
        for ws in list(self.clients):
            try:
                await ws.send_text(text)
            except Exception:  # noqa: BLE001 - drop broken sockets
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)


class State:
    def __init__(self) -> None:
        self.pool: Any = None
        self.hub = Hub()
        self.drone = DroneState()
        self.stop_flag = False
        self.missions: list[dict[str, Any]] = []
        self.agent_runs: list[dict[str, Any]] = []


S = State()


def _reset_drone() -> None:
    home = load_site().drone.home_xy
    S.drone = DroneState(ts=db.iso(datetime.now(UTC)), x=home[0], y=home[1])


async def _heatmap_loop() -> None:
    while True:
        await asyncio.sleep(0.5)
        if S.hub.heatmap_dirty and S.pool is not None:
            S.hub.heatmap_dirty = False
            try:
                await S.hub.broadcast("heatmap", await compute_heatmap(None))
            except Exception:
                log.exception("heatmap broadcast failed")


@asynccontextmanager
async def lifespan(_: FastAPI):
    S.pool = await db.connect()
    _reset_drone()
    S.hub.start_recording()
    task = asyncio.create_task(_heatmap_loop())
    try:
        yield
    finally:
        task.cancel()
        S.hub.close()
        await S.pool.close()


app = FastAPI(title="Sentinel server", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


# --------------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------------


def _since(since: str | None) -> datetime:
    if not since:
        return datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        dt = datetime.fromisoformat(since)
    except ValueError as e:
        raise HTTPException(400, f"bad 'since': {since}") from e
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def fetch_events(
    since: datetime | None = None,
    types: list[str] | None = None,
    zone_id: str | None = None,
    source: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    where, args = [], []
    if since is not None:
        args.append(since)
        where.append(f"ts >= ${len(args)}")
    if types:
        args.append(types)
        where.append(f"type = ANY(${len(args)})")
    if zone_id:
        args.append(zone_id)
        where.append(f"zone_id = ${len(args)}")
    if source:
        args.append(source)
        where.append(f"source = ${len(args)}")
    sql = (
        "SELECT * FROM events"
        + (" WHERE " + " AND ".join(where) if where else "")
        + " ORDER BY ts DESC"
    )
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = await S.pool.fetch(sql, *args)
    return [db.row_to_event(r) for r in rows]


async def fetch_products() -> list[dict[str, Any]]:
    rows = await S.pool.fetch("SELECT * FROM products ORDER BY product_id")
    return [dict(r) for r in rows]


async def compute_heatmap(since: str | None) -> dict[str, Any]:
    events = await fetch_events(_since(since), types=["look", "interest"])
    return logic.heatmap(list(reversed(events)))


async def compute_funnel(since: str | None) -> list[dict[str, Any]]:
    since_dt = _since(since)
    events = await fetch_events(since_dt, types=list(logic.FUNNEL_STAGES))
    rows = await S.pool.fetch(
        "SELECT product_id, SUM(units)::int AS units FROM sales WHERE ts_hour >= date_trunc('hour', $1::timestamptz)"
        " GROUP BY product_id",
        since_dt,
    )
    sold = {r["product_id"]: r["units"] for r in rows}
    return logic.funnel(await fetch_products(), events, sold)


async def fetch_tasks(status: str | None = None) -> list[dict[str, Any]]:
    if status:
        rows = await S.pool.fetch(
            "SELECT * FROM tasks WHERE status = $1 ORDER BY created_at DESC", status
        )
    else:
        rows = await S.pool.fetch("SELECT * FROM tasks ORDER BY created_at DESC")
    return [db.row_to_task(r) for r in rows]


# --------------------------------------------------------------------------------------------
# REST
# --------------------------------------------------------------------------------------------


@app.get("/api/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


@app.get("/api/site")
async def site() -> dict[str, Any]:
    return raw_site()


@app.get("/api/products")
async def products() -> list[dict[str, Any]]:
    return await fetch_products()


@app.post("/api/events")
async def post_events(
    body: Annotated[EventIn | list[EventIn], Body()],
) -> dict[str, Any]:
    items = body if isinstance(body, list) else [body]
    site_id = load_site().site_id
    inserted = []
    async with S.pool.acquire() as conn:
        for ev in items:
            d = ev.model_dump()
            d["event_id"] = d["event_id"] or ulid()
            d["ts"] = d["ts"] or datetime.now(UTC)
            if d["ts"].tzinfo is None:
                d["ts"] = d["ts"].replace(tzinfo=UTC)
            d["site_id"] = d["site_id"] or site_id
            await conn.execute(
                f"INSERT INTO events ({', '.join(db.EVENT_COLS)}) VALUES "
                f"({', '.join(f'${i + 1}' for i in range(len(db.EVENT_COLS)))}) ON CONFLICT (event_id) DO NOTHING",
                *[d[c] for c in db.EVENT_COLS],
            )
            if d["decision"]:
                dec = d["decision"]
                await conn.execute(
                    "INSERT INTO decisions_log (ts, question, answer, policy) VALUES ($1,$2,$3,$4)",
                    d["ts"], str(dec.get("question", "")), dec.get("answer"), dec.get("policy"),
                )  # fmt: skip
            d["ts"] = db.iso(d["ts"])
            inserted.append(d)
    for d in inserted:
        await S.hub.broadcast("event", d)
        if d["type"] in ("look", "interest"):
            S.hub.heatmap_dirty = True
    return {"inserted": len(inserted), "event_ids": [d["event_id"] for d in inserted]}


@app.get("/api/events")
async def get_events(
    type: str | None = None,
    zone_id: str | None = None,
    source: str | None = None,
    since: str | None = None,
    limit: int = Query(200, ge=1, le=5000),
) -> list[dict[str, Any]]:
    return await fetch_events(
        _since(since) if since else None,
        types=type.split(",") if type else None,
        zone_id=zone_id,
        source=source,
        limit=limit,
    )


@app.get("/api/heatmap")
async def get_heatmap(since: str | None = None) -> dict[str, Any]:
    return await compute_heatmap(since)


@app.get("/api/funnel")
async def get_funnel(since: str | None = None) -> list[dict[str, Any]]:
    return await compute_funnel(since)


@app.get("/api/tasks")
async def get_tasks(status: str | None = None) -> list[dict[str, Any]]:
    return await fetch_tasks(status)


async def create_task(t: TaskIn) -> dict[str, Any]:
    source_event = t.source_event
    if source_event and not await S.pool.fetchval(
        "SELECT 1 FROM events WHERE event_id=$1", source_event
    ):
        source_event = None  # FK would fail; keep the task anyway
    row = await S.pool.fetchrow(
        "INSERT INTO tasks (task_id, created_at, zone_id, kind, severity, status, source_event, assignee, note)"
        " VALUES ($1,$2,$3,$4,$5,'open',$6,$7,$8) RETURNING *",
        ulid(), datetime.now(UTC), t.zone_id, t.kind, t.severity, source_event, t.assignee, t.note,
    )  # fmt: skip
    task = db.row_to_task(row)
    await S.hub.broadcast("task", task)
    return task


@app.post("/api/tasks")
async def post_task(t: TaskIn) -> dict[str, Any]:
    return await create_task(t)


@app.patch("/api/tasks/{task_id}")
async def patch_task(task_id: str, p: TaskPatch) -> dict[str, Any]:
    fields = {k: v for k, v in p.model_dump().items() if v is not None}
    if fields:
        sets = ", ".join(f"{k} = ${i + 2}" for i, k in enumerate(fields))
        row = await S.pool.fetchrow(
            f"UPDATE tasks SET {sets} WHERE task_id = $1 RETURNING *",
            task_id,
            *fields.values(),
        )
    else:
        row = await S.pool.fetchrow("SELECT * FROM tasks WHERE task_id = $1", task_id)
    if row is None:
        raise HTTPException(404, "task not found")
    task = db.row_to_task(row)
    await S.hub.broadcast("task", task)
    return task


@app.get("/api/review")
async def get_review() -> list[dict[str, Any]]:
    rows = await S.pool.fetch(
        "SELECT * FROM events WHERE decision->>'policy' = 'review' AND (payload IS NULL OR NOT payload ? 'review')"
        " ORDER BY ts DESC LIMIT 200"
    )
    return [db.row_to_event(r) for r in rows]


@app.post("/api/review/{event_id}")
async def post_review(event_id: str, r: ReviewIn) -> dict[str, Any]:
    review = {"verdict": r.verdict, "label": r.label, "ts": db.iso(datetime.now(UTC))}
    row = await S.pool.fetchrow(
        "UPDATE events SET payload = COALESCE(payload, '{}'::jsonb) || jsonb_build_object('review', $2::jsonb)"
        " WHERE event_id = $1 RETURNING *",
        event_id, review,
    )  # fmt: skip
    if row is None:
        raise HTTPException(404, "event not found")
    ev = db.row_to_event(row)
    await S.hub.broadcast("event", ev)
    return ev


# ---- Drone ---------------------------------------------------------------------------------


def _active_mission() -> dict[str, Any] | None:
    return next((m for m in S.missions if m["status"] in ("pending", "active")), None)


@app.get("/api/drone/state")
async def get_drone_state() -> dict[str, Any]:
    return S.drone.model_dump()


@app.post("/api/drone/state")
async def post_drone_state(st: DroneState) -> dict[str, bool]:
    st.ts = st.ts or db.iso(datetime.now(UTC))
    st.stop_requested = S.stop_flag
    m = _active_mission()
    if m and st.mission_id == m["mission_id"] and m["status"] == "pending":
        m["status"] = "active"
    elif m and m["status"] == "active" and st.state == "IDLE" and st.mission_id is None:
        m["status"] = (
            "done"  # dequeued: GET /api/drone/mission now returns the next pending one
        )
    S.drone = st
    await S.hub.broadcast("drone", st.model_dump())
    return {"ok": True}


@app.post("/api/drone/stop")
async def drone_stop() -> dict[str, bool]:
    S.stop_flag = True
    S.drone.stop_requested = True
    for m in S.missions:
        if m["status"] in ("pending", "active"):
            m["status"] = "cancelled"
    await S.hub.broadcast("drone", S.drone.model_dump())
    return {"ok": True}


@app.post("/api/drone/mission")
async def post_mission(m: MissionIn) -> dict[str, Any]:
    site_cfg = load_site()
    bays = {z.id for z in site_cfg.zones_of("rack_bay")}
    mission_id = ulid()
    reason = None
    unknown = [b for b in m.bays if b not in bays]
    if not m.bays:
        reason = "no bays given"
    elif unknown:
        reason = f"unknown bays: {', '.join(unknown)}"
    elif S.drone.battery_pct < site_cfg.drone.min_battery_pct:
        reason = f"battery {S.drone.battery_pct:.0f}% below minimum {site_cfg.drone.min_battery_pct:.0f}%"
    elif _active_mission() is not None:
        reason = "another mission is already pending or active"
    if reason:
        return {"accepted": False, "mission_id": mission_id, "rejected_reason": reason}
    S.stop_flag = False
    S.drone.stop_requested = False
    S.missions.append(
        {
            "mission_id": mission_id,
            "bays": m.bays,
            "reason": m.reason,
            "requested_by": m.requested_by,
            "status": "pending",
            "created_at": db.iso(datetime.now(UTC)),
        }
    )
    return {"accepted": True, "mission_id": mission_id}


@app.get("/api/drone/mission")
async def get_mission() -> dict[str, Any] | None:
    return _active_mission()


# ---- Ask Sentinel / summary ----------------------------------------------------------------

INTENTS: list[dict[str, str]] = [
    {
        "value": "underperforming_shelf",
        "description": "Which shelf/zone/product gets attention but does not convert",
    },
    {
        "value": "low_stock",
        "description": "Empty, low-stock or misplaced bays and restock needs",
    },
    {"value": "open_tasks", "description": "Open staff tasks"},
    {"value": "put_back_rate", "description": "Products shoppers pick up and put back"},
    {"value": "drone_status", "description": "Drone position, state, battery, mission"},
    {"value": "product_location", "description": "Where a product is located"},
    {"value": "other", "description": "Anything else; general shift overview"},
]
_KEYWORDS = [
    ("put_back_rate", r"put[ -]?back|put them back|returned|pick(ed)? up"),
    ("drone_status", r"drone|patrol|battery|fly|flight"),
    ("low_stock", r"stock|empty|restock|misplac|bay|gap"),
    ("open_tasks", r"task|todo|to do|jobs?|outstanding"),
    (
        "underperforming_shelf",
        r"underperform|worst|convert|conversion|attention|shelf|aisle|zone",
    ),
    ("product_location", r"where|locat|find"),
]


def keyword_intent(question: str) -> str:
    q = question.lower()
    for intent, pat in _KEYWORDS:
        if re.search(pat, q):
            return intent
    return "other"


async def pick_intent(question: str) -> str:
    values = {i["value"] for i in INTENTS}
    try:
        import sentinel_decisions as sd

        if not sd.is_mock():
            d = await asyncio.wait_for(
                asyncio.to_thread(sd.ask_intent, question, INTENTS), timeout=6.0
            )
            if d.policy in ("auto", "review") and d.value in values:
                return str(d.value)
    except Exception:
        log.exception("ask_intent failed; falling back to keywords")
    return keyword_intent(question)


def _find_product(question: str, prods: list[dict[str, Any]]) -> dict[str, Any] | None:
    q = question.lower()
    m = re.search(r"sku-?(\d{1,3})", q)
    if m:
        pid = f"SKU-{int(m.group(1)):03d}"
        return next((p for p in prods if p["product_id"] == pid), None)
    best, best_score = None, 0
    for p in prods:
        words = set(re.findall(r"[a-z']+", f"{p['name']} {p['brand']}".lower())) - {
            "of",
            "in",
            "the",
            "g",
            "pack",
        }
        score = sum(1 for w in words if len(w) > 2 and w in q)
        if score > best_score:
            best, best_score = p, score
    return best


async def answer(intent: str, question: str) -> dict[str, Any]:
    if intent == "underperforming_shelf":
        rows = await compute_funnel(None)
        zones = logic.zone_rollup(rows)
        flagged = [r for r in rows if r["flag_high_attention_low_conversion"]]
        looked_zones = {k: v for k, v in zones.items() if v["looked"]}
        if not looked_zones:
            return {
                "answer": "No shelf attention recorded yet today.",
                "data": {"zones": zones, "flagged": []},
            }
        worst_zone, wz = min(looked_zones.items(), key=lambda kv: kv[1]["conversion"])
        text = (
            f"{worst_zone} underperformed: {int(wz['looked'])} looks but only {int(wz['kept'])} "
            f"kept ({wz['conversion']:.0%} look-to-basket)."
        )
        if flagged:
            f = max(flagged, key=lambda r: r["looked"])
            text += (
                f" {f['name']} ({f['product_id']}) is high attention, low conversion: {f['looked']} looks, "
                f"{f['put_back']} put back, {f['sold']} sold."
            )
        return {
            "answer": text,
            "data": {"zone": worst_zone, "zones": zones, "flagged": flagged},
        }
    if intent == "low_stock":
        evs = await fetch_events(_since(None), types=["bay_issue"], limit=200)
        latest: dict[str, dict[str, Any]] = {}
        for e in evs:
            latest.setdefault(e["zone_id"], e)
        issues = [
            e
            for e in latest.values()
            if (e.get("payload") or {}).get("issue") not in (None, "ok")
        ]
        tasks = [
            t for t in await fetch_tasks("open") if t["kind"] in ("restock", "move")
        ]
        if not issues:
            return {
                "answer": "No stock issues found on today's patrols.",
                "data": {"issues": [], "tasks": tasks},
            }
        parts = [
            f"{e['zone_id']} {e['payload']['issue'].replace('_', ' ')}" for e in issues
        ]
        return {
            "answer": f"{len(issues)} bay issue(s): {', '.join(parts)}. {len(tasks)} restock/move task(s) open.",
            "data": {"issues": issues, "tasks": tasks},
        }
    if intent == "open_tasks":
        tasks = await fetch_tasks("open")
        if not tasks:
            return {"answer": "No open tasks.", "data": []}
        parts = [f"{t['kind']} at {t['zone_id']}" for t in tasks[:5]]
        return {
            "answer": f"{len(tasks)} open task(s): {', '.join(parts)}.",
            "data": tasks,
        }
    if intent == "put_back_rate":
        rows = [r for r in await compute_funnel(None) if r["picked_up"]]
        rows.sort(key=lambda r: (r["put_back_rate"], r["picked_up"]), reverse=True)
        if not rows:
            return {"answer": "No pick-ups recorded yet today.", "data": []}
        top = rows[0]
        total_pick = sum(r["picked_up"] for r in rows)
        total_back = sum(r["put_back"] for r in rows)
        return {
            "answer": (
                f"Overall put-back rate is {total_back / total_pick:.0%} ({total_back}/{total_pick}). Highest: "
                f"{top['name']} ({top['product_id']}) at {top['put_back_rate']:.0%} of {top['picked_up']} pick-ups."
            ),
            "data": rows[:5],
        }
    if intent == "drone_status":
        d = S.drone.model_dump()
        m = _active_mission()
        text = f"Drone is {d['state']} at ({d['x']:.1f}, {d['y']:.1f}, {d['z']:.1f}) m, battery {d['battery_pct']:.0f}%"
        text += f", inspecting {d['current_bay']}." if d["current_bay"] else "."
        text += (
            f" Mission {m['mission_id']} ({', '.join(m['bays'])}) is {m['status']}."
            if m
            else " No active mission."
        )
        return {"answer": text, "data": {"drone": d, "mission": m}}
    if intent == "product_location":
        prods = await fetch_products()
        p = _find_product(question, prods)
        if p is None:
            return {
                "answer": "I couldn't match that to a product in the catalogue.",
                "data": None,
            }
        z = load_site().zone(p["zone_id"])
        cx, cy = z.centre if z else (None, None)
        return {
            "answer": f"{p['brand']} {p['name']} ({p['product_id']}) is on {p['zone_id']}, £{p['price_gbp']:.2f}.",
            "data": {**p, "zone_centre_xy": [cx, cy]},
        }
    s = await summary()
    return {"answer": s["text"], "data": s}


@app.post("/api/ask")
async def ask(body: AskIn) -> dict[str, Any]:
    intent = await pick_intent(body.question)
    res = await answer(intent, body.question)
    return {"answer": res["answer"], "intent": intent, "data": res["data"]}


@app.get("/api/summary")
async def summary() -> dict[str, Any]:
    rows = await compute_funnel(None)
    open_tasks = await fetch_tasks("open")
    counts = await S.pool.fetch(
        "SELECT type, COUNT(*)::int AS n FROM events WHERE ts >= $1 GROUP BY type",
        _since(None),
    )
    by_type = {r["type"]: r["n"] for r in counts}
    flagged = [r for r in rows if r["flag_high_attention_low_conversion"]]
    issues = by_type.get("bay_issue", 0)
    review = await S.pool.fetchval(
        "SELECT COUNT(*) FROM events WHERE decision->>'policy'='review' AND (payload IS NULL OR NOT payload ? 'review')"
    )
    text = (
        f"Today: {by_type.get('pass_by', 0)} pass-bys, {by_type.get('look', 0)} looks, "
        f"{by_type.get('pick_up', 0)} pick-ups ({by_type.get('put_back', 0)} put back, {by_type.get('kept', 0)} kept). "
        f"{issues} bay issue(s) from drone patrols; {len(open_tasks)} open task(s); {review} decision(s) awaiting review."
    )
    if flagged:
        text += (
            " Watch: "
            + ", ".join(f"{r['name']} ({r['product_id']})" for r in flagged)
            + " — high attention, low conversion."
        )
    return {
        "text": text,
        "open_tasks": len(open_tasks),
        "events_by_type": by_type,
        "flagged_products": [r["product_id"] for r in flagged],
        "bay_issues": issues,
        "pending_review": review,
        "drone_state": S.drone.state,
    }


# ---- Devin mission agent -------------------------------------------------------------------


def _load_agent():
    agent_dir = str(REPO_ROOT / "agent")
    if agent_dir not in sys.path:
        sys.path.insert(0, agent_dir)
    import sentinel_agent  # type: ignore[import-not-found]

    return sentinel_agent


@app.post("/api/agent/run")
async def agent_run(body: AgentRunIn) -> dict[str, Any]:
    try:
        agent = _load_agent()
    except Exception as e:
        raise HTTPException(
            503,
            f"sentinel_agent is not available (agent/ workstream not installed): {e}",
        ) from e
    api_base = os.environ.get("SENTINEL_PUBLIC_API") or os.environ.get(
        "SENTINEL_API", "http://localhost:8000"
    )
    try:
        res = await asyncio.to_thread(agent.launch, body.goal, api_base)
    except Exception as e:
        raise HTTPException(502, f"sentinel_agent.launch failed: {e}") from e
    run = {
        "session_id": res.get("session_id"),
        "url": res.get("url"),
        "goal": body.goal,
        "status": res.get("status", "running"),
        "created_at": db.iso(datetime.now(UTC)),
    }
    S.agent_runs.insert(0, run)
    return {"session_id": run["session_id"], "url": run["url"]}


@app.get("/api/agent/runs")
async def agent_runs() -> list[dict[str, Any]]:
    return S.agent_runs


# --------------------------------------------------------------------------------------------
# WebSocket
# --------------------------------------------------------------------------------------------


@app.websocket("/ws")
async def ws(websocket: WebSocket) -> None:
    await websocket.accept()
    S.hub.clients.add(websocket)
    try:
        await websocket.send_text(
            json.dumps({"kind": "drone", "data": S.drone.model_dump()})
        )
        while True:
            await websocket.receive_text()  # clients don't send; keep the socket open
    except WebSocketDisconnect:
        pass
    finally:
        S.hub.clients.discard(websocket)
