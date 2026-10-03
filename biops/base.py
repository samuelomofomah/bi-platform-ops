"""Shared helpers. Every platform client exposes the same five methods
(health, inventory, usage, backup, refresh) so tasks.py never needs to know
which BI tool it is talking to."""
from __future__ import annotations

import re
import time
from typing import Callable


def result(platform: str, name: str, ok: bool, detail: str = "", latency_ms: int = 0) -> dict:
    return {
        "platform": platform,
        "check_name": name,
        "status": "ok" if ok else "fail",
        "latency_ms": latency_ms,
        "detail": str(detail)[:500],
    }


def timed_check(platform: str, name: str, fn: Callable[[], str]) -> dict:
    """Run fn, time it, and turn any exception into a failed check row."""
    start = time.perf_counter()
    try:
        detail, ok = fn() or "", True
    except Exception as exc:  # a health check must never crash the run
        detail, ok = f"{type(exc).__name__}: {exc}", False
    return result(platform, name, ok, detail, int((time.perf_counter() - start) * 1000))


def job(platform: str, target: str, ok: bool, detail: str = "", path: str = "") -> dict:
    return {
        "platform": platform,
        "target": target,
        "status": "ok" if ok else "fail",
        "detail": str(detail)[:500],
        "path": path,
    }


def safe_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_") or "unnamed"
