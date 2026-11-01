-- Sentinel event store (PostgreSQL). Brief section 5.4, plus products / decisions_log.
CREATE TABLE IF NOT EXISTS events (
  event_id     TEXT PRIMARY KEY,            -- ULID
  ts           TIMESTAMPTZ NOT NULL,        -- UTC
  site_id      TEXT NOT NULL,
  zone_id      TEXT NOT NULL,
  type         TEXT NOT NULL,               -- pass_by | look | interest | pick_up | put_back | kept | bay_issue | hazard | task | patrol
  product_id   TEXT,
  x            DOUBLE PRECISION,            -- metres, twin frame
  y            DOUBLE PRECISION,
  z            DOUBLE PRECISION,
  source       TEXT NOT NULL,               -- 'camera-1' | 'drone-1' | 'pos' | 'agent' | 'sim'
  track_id     TEXT,
  decision     JSONB,
  confidence   DOUBLE PRECISION,
  crop_ref     TEXT,
  payload      JSONB
);
CREATE INDEX IF NOT EXISTS events_zone_ts ON events (zone_id, ts);
CREATE INDEX IF NOT EXISTS events_type_ts ON events (type, ts);

CREATE TABLE IF NOT EXISTS tasks (
  task_id      TEXT PRIMARY KEY,
  created_at   TIMESTAMPTZ NOT NULL,
  zone_id      TEXT NOT NULL,
  kind         TEXT NOT NULL,               -- restock | move | fix_label | hazard | review
  severity     DOUBLE PRECISION,
  status       TEXT NOT NULL DEFAULT 'open',-- open | in_progress | done | dismissed
  source_event TEXT REFERENCES events(event_id),
  assignee     TEXT,
  note         TEXT
);

CREATE TABLE IF NOT EXISTS sales (
  ts_hour      TIMESTAMPTZ NOT NULL,
  product_id   TEXT NOT NULL,
  units        INTEGER NOT NULL,
  PRIMARY KEY (ts_hour, product_id)
);

CREATE TABLE IF NOT EXISTS products (       -- mocked catalogue (20 SKUs)
  product_id   TEXT PRIMARY KEY,            -- 'SKU-001'
  name         TEXT NOT NULL,
  brand        TEXT NOT NULL,
  barcode      TEXT,
  price_gbp    DOUBLE PRECISION,
  zone_id      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions_log (
  id           BIGSERIAL PRIMARY KEY,
  ts           TIMESTAMPTZ NOT NULL DEFAULT now(),
  question     TEXT NOT NULL,               -- holding_product | reach_outcome | bay_issue | ...
  latency_s    DOUBLE PRECISION,
  input_tokens INTEGER,
  cached_tokens INTEGER,
  answer       JSONB,
  policy       TEXT                         -- auto | review | ignore | unclear
);
