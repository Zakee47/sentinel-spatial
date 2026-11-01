"""asyncpg pool, schema bootstrap (db/schema.sql) and seeding."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

import asyncpg

from . import seed
from .config import SCHEMA_PATH

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://sentinel:sentinel@localhost:5432/sentinel"
)

EVENT_COLS = (
    "event_id", "ts", "site_id", "zone_id", "type", "product_id", "x", "y", "z",
    "source", "track_id", "decision", "confidence", "crop_ref", "payload",
)  # fmt: skip
TASK_COLS = (
    "task_id",
    "created_at",
    "zone_id",
    "kind",
    "severity",
    "status",
    "source_event",
    "assignee",
    "note",
)


async def _init_conn(conn: asyncpg.Connection) -> None:
    for t in ("jsonb", "json"):
        await conn.set_type_codec(
            t, encoder=json.dumps, decoder=json.loads, schema="pg_catalog"
        )


async def connect() -> asyncpg.Pool:
    pool = await asyncpg.create_pool(
        DATABASE_URL, init=_init_conn, min_size=1, max_size=10
    )
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA_PATH.read_text())
        await seed_db(conn)
    return pool


async def seed_db(conn: asyncpg.Connection) -> None:
    await conn.executemany(
        "INSERT INTO products (product_id, name, brand, barcode, price_gbp, zone_id) VALUES ($1,$2,$3,$4,$5,$6)"
        " ON CONFLICT (product_id) DO NOTHING",
        [
            (
                p["product_id"],
                p["name"],
                p["brand"],
                p["barcode"],
                p["price_gbp"],
                p["zone_id"],
            )
            for p in seed.products()
        ],
    )
    await conn.executemany(
        "INSERT INTO sales (ts_hour, product_id, units) VALUES ($1,$2,$3) ON CONFLICT DO NOTHING",
        seed.sales_today(),
    )


def iso(ts: datetime | None) -> str | None:
    if ts is None:
        return None
    return ts.astimezone(UTC).isoformat().replace("+00:00", "Z")


def row_to_event(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    d["ts"] = iso(d["ts"])
    return d


def row_to_task(row: asyncpg.Record) -> dict[str, Any]:
    d = dict(row)
    d["created_at"] = iso(d["created_at"])
    return d
