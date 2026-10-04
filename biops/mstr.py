"""MicroStrategy / Strategy ONE client over the Library REST API.

Base URL is the Library web app, e.g. https://host/MicroStrategyLibrary.
Login returns an X-MSTR-AuthToken header plus a session cookie; project-scoped
calls also need an X-MSTR-ProjectID header. Browse every endpoint on your own
environment at <base>/api-docs.
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import requests

from biops.base import job, result, safe_name, timed_check

P = "microstrategy"
OBJECT_TYPES = {3: "report", 55: "dossier"}  # 3 = reports and cubes, 55 = documents and dossiers


class MstrClient:
    platform = P

    def __init__(self, url, user, password, login_mode=1, cluster_check=True, timeout=30, session=None):
        self.base = url.rstrip("/")
        self.user, self.password, self.login_mode = user, password, login_mode
        self.cluster_check = cluster_check
        self.timeout = timeout
        self.http = session or requests.Session()
        self.http.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
        self.token: str | None = None

    # --- session -----------------------------------------------------------
    def connect(self) -> None:
        if self.token:
            return
        body = {"username": self.user, "password": self.password, "loginMode": self.login_mode}
        r = self.http.post(f"{self.base}/api/auth/login", json=body, timeout=self.timeout)
        r.raise_for_status()
        self.token = r.headers["X-MSTR-AuthToken"]
        self.http.headers["X-MSTR-AuthToken"] = self.token

    def close(self) -> None:
        if not self.token:
            return
        try:
            self.http.post(f"{self.base}/api/auth/logout", timeout=self.timeout)
        finally:
            self.token = None
            self.http.headers.pop("X-MSTR-AuthToken", None)

    def _get(self, path: str, project_id: str | None = None, **params) -> dict | list:
        headers = {"X-MSTR-ProjectID": project_id} if project_id else {}
        r = self.http.get(f"{self.base}{path}", headers=headers, params=params, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def projects(self) -> list[dict]:
        return self._get("/api/projects")

    def _search(self, project_id: str, type_code: int) -> Iterator[dict]:
        offset, limit = 0, 200
        while True:
            data = self._get("/api/searches/results", project_id, type=type_code, limit=limit, offset=offset)
            items = data.get("result", [])
            yield from items
            offset += limit
            if not items or offset >= int(data.get("totalItems", 0)):
                return

    # --- the five operations ------------------------------------------------
    def health(self) -> list[dict]:
        def reachable() -> str:
            # /api/status reports uptime and whether Library has an Intelligence Server behind it.
            status = self._get("/api/status")
            if not status.get("isIServerConfigured", True):
                raise RuntimeError("Library is up but no Intelligence Server is configured")
            return "up " + str(status.get("upTimeText", "(uptime not reported)"))

        def login() -> str:
            self.connect()
            return f"logged in as {self.user or 'guest'}"

        checks = [timed_check(P, "library_reachable", reachable), timed_check(P, "login", login)]
        if checks[-1]["status"] != "ok" or not self.cluster_check:
            return checks
        try:  # cluster view: is every node running and every project loaded on it?
            nodes = self._get("/api/monitors/iServer/nodes").get("nodes", [])
        except Exception as exc:
            return checks + [result(P, "cluster_monitor", False, f"{type(exc).__name__}: {exc}")]
        for node in nodes:
            name, status = node.get("name", "?"), node.get("status", "unknown")
            checks.append(result(P, f"node:{name}", status == "running", status))
            for proj in node.get("projects", []):
                pstatus = proj.get("status", "unknown")
                checks.append(result(P, f"project:{proj.get('name', '?')}@{name}", pstatus == "loaded", pstatus))
        return checks

    def inventory(self) -> list[dict]:
        rows = []
        for proj in self.projects():
            for code, label in OBJECT_TYPES.items():
                for it in self._search(proj["id"], code):
                    rows.append(
                        {
                            "platform": P,
                            "object_type": label,
                            "object_id": it["id"],
                            "name": it.get("name", ""),
                            "project": proj.get("name", ""),
                            "owner": it.get("owner", {}).get("name", ""),
                            "updated_at": it.get("dateModified", ""),
                        }
                    )
        return rows

    def usage(self, as_of: date | None = None) -> list[dict]:
        """Not available over REST: run history lives in Platform Analytics (a SQL
        warehouse). See README > Next steps for how to wire that in."""
        return []

    def backup(self, dest: Path) -> list[dict]:
        """Write a JSON manifest of every report/dossier per project.

        This is a content inventory to diff or rebuild from, not a full restore
        point: a real MicroStrategy backup is the metadata database dump plus
        migration packages.
        """
        dest.mkdir(parents=True, exist_ok=True)
        by_project: dict[str, list[dict]] = {}
        for row in self.inventory():
            by_project.setdefault(row["project"], []).append(row)
        out = []
        for project, rows in by_project.items():
            path = dest / f"{safe_name(project)}_manifest.json"
            path.write_text(json.dumps(rows, indent=2))
            out.append(job(P, project, True, f"{len(rows)} objects", str(path)))
        return out

    def refresh(self, targets: list[str]) -> list[dict]:
        """Republish Intelligent Cubes. Each target is 'projectId:cubeId'."""
        out = []
        for target in targets:
            try:
                project_id, cube_id = target.split(":", 1)
                r = self.http.post(
                    f"{self.base}/api/v2/cubes/{cube_id}", headers={"X-MSTR-ProjectID": project_id}, timeout=self.timeout
                )
                r.raise_for_status()
                out.append(job(P, target, True, f"publish accepted (HTTP {r.status_code})"))
            except Exception as exc:
                out.append(job(P, target, False, f"{type(exc).__name__}: {exc}"))
        return out
