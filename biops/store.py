"""Thin SQLite layer. All the interesting SQL lives in sql/schema.sql."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = Path(__file__).resolve().parent.parent / "sql" / "schema.sql"


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class Store:
    def __init__(self, path: str, env: str):
        if path != ":memory:":
            Path(path).resolve().parent.mkdir(parents=True, exist_ok=True)
        self.env = env
        self.db = sqlite3.connect(path)
        self.db.executescript(SCHEMA.read_text())

    def add_health(self, rows: list[dict]) -> None:
        now = utcnow()
        self.db.executemany(
            "INSERT INTO health_check VALUES (:t, :e, :platform, :check_name, :status, :latency_ms, :detail)",
            [{**r, "t": now, "e": self.env} for r in rows],
        )
        self.db.commit()

    def add_inventory(self, snapshot_date: str, rows: list[dict]) -> None:
        # INSERT OR REPLACE makes a re-run on the same day idempotent.
        self.db.executemany(
            "INSERT OR REPLACE INTO content_inventory VALUES "
            "(:d, :e, :platform, :object_type, :object_id, :name, :project, :owner, :updated_at)",
            [{**r, "d": snapshot_date, "e": self.env} for r in rows],
        )
        self.db.commit()

    def add_usage(self, snapshot_date: str, rows: list[dict]) -> None:
        self.db.executemany(
            "INSERT OR REPLACE INTO usage_snapshot VALUES "
            "(:d, :e, :platform, :object_id, :name, :parent_id, :total_views)",
            [{**r, "d": snapshot_date, "e": self.env} for r in rows],
        )
        self.db.commit()

    def add_jobs(self, task: str, rows: list[dict]) -> None:
        now = utcnow()
        self.db.executemany(
            "INSERT INTO job_log VALUES (:t, :e, :task, :platform, :target, :status, :detail, :path, :bytes, :sha256)",
            [{"bytes": None, "sha256": None, **r, "t": now, "e": self.env, "task": task} for r in rows],
        )
        self.db.commit()

    def query(self, sql: str) -> tuple[list[str], list[tuple]]:
        cur = self.db.execute(sql)
        return [c[0] for c in cur.description], cur.fetchall()
