-- bi-platform-ops operational store.
-- SQLite by default so the project runs anywhere; the DDL is plain enough to
-- move to Postgres (swap the date() / datetime() calls for now() - interval).
-- Point a Tableau workbook or a MicroStrategy dossier at these views to get
-- the "BI on BI" monitoring dashboard.

CREATE TABLE IF NOT EXISTS health_check (
    checked_at  TEXT    NOT NULL,              -- UTC, ISO 8601
    env         TEXT    NOT NULL,
    platform    TEXT    NOT NULL,              -- tableau | microstrategy
    check_name  TEXT    NOT NULL,
    status      TEXT    NOT NULL CHECK (status IN ('ok', 'fail')),
    latency_ms  INTEGER,
    detail      TEXT
);
CREATE INDEX IF NOT EXISTS ix_health_time ON health_check (env, platform, checked_at);

CREATE TABLE IF NOT EXISTS content_inventory (
    snapshot_date TEXT NOT NULL,
    env           TEXT NOT NULL,
    platform      TEXT NOT NULL,
    object_type   TEXT NOT NULL,               -- workbook | datasource | report | dossier
    object_id     TEXT NOT NULL,
    name          TEXT,
    project       TEXT,
    owner         TEXT,
    updated_at    TEXT,
    PRIMARY KEY (snapshot_date, env, platform, object_id)
);

CREATE TABLE IF NOT EXISTS usage_snapshot (
    snapshot_date TEXT    NOT NULL,
    env           TEXT    NOT NULL,
    platform      TEXT    NOT NULL,
    object_id     TEXT    NOT NULL,            -- the view
    name          TEXT,
    parent_id     TEXT,                        -- the workbook it belongs to
    total_views   INTEGER NOT NULL,            -- cumulative, as the API reports it
    PRIMARY KEY (snapshot_date, env, platform, object_id)
);

CREATE TABLE IF NOT EXISTS job_log (
    ran_at   TEXT NOT NULL,
    env      TEXT NOT NULL,
    task     TEXT NOT NULL,                    -- backup | refresh | publish
    platform TEXT NOT NULL,
    target   TEXT NOT NULL,
    status   TEXT NOT NULL CHECK (status IN ('ok', 'fail')),
    detail   TEXT,
    path     TEXT,
    bytes    INTEGER,
    sha256   TEXT
);

-- Current state: the most recent result of every check.
CREATE VIEW IF NOT EXISTS v_latest_health AS
SELECT h.env, h.platform, h.check_name, h.status, h.latency_ms, h.detail, h.checked_at
FROM health_check h
JOIN (
    SELECT env, platform, check_name, MAX(checked_at) AS checked_at
    FROM health_check
    GROUP BY env, platform, check_name
) latest
  ON  latest.env = h.env
  AND latest.platform = h.platform
  AND latest.check_name = h.check_name
  AND latest.checked_at = h.checked_at;

-- SLA view: share of passing checks per platform over the last 7 days.
CREATE VIEW IF NOT EXISTS v_availability_7d AS
SELECT env,
       platform,
       COUNT(*)                                                             AS checks,
       ROUND(100.0 * SUM(CASE WHEN status = 'ok' THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct_ok,
       CAST(ROUND(AVG(NULLIF(latency_ms, 0))) AS INTEGER)                   AS avg_latency_ms
FROM health_check
WHERE checked_at >= datetime('now', '-7 days')
GROUP BY env, platform;

-- The API only gives lifetime view counts, so daily usage is today minus the
-- previous snapshot. LAG() does that per view without a self-join.
CREATE VIEW IF NOT EXISTS v_daily_views AS
SELECT u.snapshot_date,
       u.env,
       u.platform,
       i.project,
       i.name AS workbook,
       u.name AS view_name,
       u.total_views
         - LAG(u.total_views) OVER (PARTITION BY u.env, u.platform, u.object_id ORDER BY u.snapshot_date)
         AS views_that_day
FROM usage_snapshot u
LEFT JOIN content_inventory i
  ON  i.snapshot_date = u.snapshot_date
  AND i.env = u.env
  AND i.platform = u.platform
  AND i.object_id = u.parent_id;

-- Clean-up candidates: content in the latest snapshot untouched for 180+ days.
CREATE VIEW IF NOT EXISTS v_stale_content AS
SELECT env, platform, project, object_type, name, owner, substr(updated_at, 1, 10) AS last_updated
FROM content_inventory
WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM content_inventory)
  AND substr(updated_at, 1, 10) < date('now', '-180 days');

-- Last 20 backup / refresh / publish results, newest first.
CREATE VIEW IF NOT EXISTS v_recent_jobs AS
SELECT ran_at, env, task, platform, target, status, detail, bytes
FROM job_log
ORDER BY ran_at DESC
LIMIT 20;
