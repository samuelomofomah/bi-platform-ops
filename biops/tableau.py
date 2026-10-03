"""Tableau Server / Tableau Cloud client over the REST API.

Raw REST (not the tableauserverclient SDK) is used for everything except
publishing, so the HTTP calls are visible and easy to mock in tests.
Auth is a Personal Access Token, which needs REST API 3.6+ (Tableau 2019.4+).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Iterator

import requests

from biops.base import job, safe_name, timed_check

P = "tableau"


class TableauClient:
    platform = P

    def __init__(self, url, site, pat_name, pat_secret, backup_project="", timeout=30, session=None):
        self.base = url.rstrip("/")
        self.site = site
        self.pat_name, self.pat_secret = pat_name, pat_secret
        self.backup_project = backup_project
        self.timeout = timeout
        self.http = session or requests.Session()
        self.http.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
        self.api_version = "3.6"  # replaced by whatever the server reports
        self.site_id: str | None = None

    # --- session -----------------------------------------------------------
    def server_info(self) -> dict:
        r = self.http.get(f"{self.base}/api/2.4/serverinfo", timeout=self.timeout)
        r.raise_for_status()
        info = r.json()["serverInfo"]
        self.api_version = info["restApiVersion"]
        return info

    def connect(self) -> None:
        if self.site_id:
            return
        self.server_info()
        body = {
            "credentials": {
                "personalAccessTokenName": self.pat_name,
                "personalAccessTokenSecret": self.pat_secret,
                "site": {"contentUrl": self.site},
            }
        }
        r = self.http.post(f"{self.base}/api/{self.api_version}/auth/signin", json=body, timeout=self.timeout)
        r.raise_for_status()
        cred = r.json()["credentials"]
        self.site_id = cred["site"]["id"]
        self.http.headers["X-Tableau-Auth"] = cred["token"]

    def close(self) -> None:
        if not self.site_id:
            return
        try:
            self.http.post(f"{self.base}/api/{self.api_version}/auth/signout", timeout=self.timeout)
        finally:
            self.site_id = None
            self.http.headers.pop("X-Tableau-Auth", None)

    def _site(self, path: str) -> str:
        return f"{self.base}/api/{self.api_version}/sites/{self.site_id}/{path}"

    def _paged(self, path: str, inner: str, params: dict | None = None) -> Iterator[dict]:
        """Tableau wraps lists as {"workbooks": {"workbook": [...]}} plus a pagination block."""
        outer, page, size = path.split("/")[-1], 1, 100
        while True:
            r = self.http.get(
                self._site(path), params={"pageSize": size, "pageNumber": page, **(params or {})}, timeout=self.timeout
            )
            r.raise_for_status()
            data = r.json()
            items = data.get(outer, {}).get(inner, [])
            yield from items
            total = int(data.get("pagination", {}).get("totalAvailable", 0))
            if not items or page * size >= total:
                return
            page += 1

    # --- the five operations ------------------------------------------------
    def health(self) -> list[dict]:
        def reachable() -> str:
            return "version " + self.server_info()["productVersion"]["value"]

        def sign_in() -> str:
            self.connect()
            return f"site id {self.site_id}, REST API {self.api_version}"

        return [timed_check(P, "server_reachable", reachable), timed_check(P, "pat_sign_in", sign_in)]

    def inventory(self) -> list[dict]:
        rows = []
        for kind in ("workbook", "datasource"):
            for it in self._paged(kind + "s", kind):
                rows.append(
                    {
                        "platform": P,
                        "object_type": kind,
                        "object_id": it["id"],
                        "name": it.get("name", ""),
                        "project": it.get("project", {}).get("name", ""),
                        "owner": it.get("owner", {}).get("id", ""),
                        "updated_at": it.get("updatedAt", ""),
                    }
                )
        return rows

    def usage(self, as_of: date | None = None) -> list[dict]:
        """Cumulative view counts per view. Daily numbers are derived in SQL (v_daily_views)."""
        rows = []
        for v in self._paged("views", "view", {"includeUsageStatistics": "true"}):
            rows.append(
                {
                    "platform": P,
                    "object_id": v["id"],
                    "name": v.get("name", ""),
                    "parent_id": v.get("workbook", {}).get("id", ""),
                    "total_views": int(v.get("usage", {}).get("totalViewCount", 0)),
                }
            )
        return rows

    def backup(self, dest: Path) -> list[dict]:
        """Download every workbook (optionally one project) as .twb/.twbx."""
        dest.mkdir(parents=True, exist_ok=True)
        out = []
        for wb in self._paged("workbooks", "workbook"):
            if self.backup_project and wb.get("project", {}).get("name") != self.backup_project:
                continue
            try:
                r = self.http.get(
                    self._site(f"workbooks/{wb['id']}/content"), headers={"Accept": "*/*"}, stream=True, timeout=300
                )
                r.raise_for_status()
                ext = ".twbx" if ".twbx" in r.headers.get("Content-Disposition", "") else ".twb"
                path = dest / f"{safe_name(wb['name'])}_{wb['id'][:8]}{ext}"
                with open(path, "wb") as fh:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        fh.write(chunk)
                out.append(job(P, wb["name"], True, "downloaded", str(path)))
            except Exception as exc:  # one bad workbook must not stop the backup
                out.append(job(P, wb.get("name", wb["id"]), False, f"{type(exc).__name__}: {exc}"))
        return out

    def refresh(self, targets: list[str]) -> list[dict]:
        """Queue an extract refresh for each published data source id."""
        out = []
        for ds_id in targets:
            try:
                r = self.http.post(self._site(f"datasources/{ds_id}/refresh"), json={}, timeout=self.timeout)
                r.raise_for_status()
                out.append(job(P, ds_id, True, "queued job " + r.json().get("job", {}).get("id", "?")))
            except Exception as exc:
                out.append(job(P, ds_id, False, f"{type(exc).__name__}: {exc}"))
        return out


def publish_workbook(url: str, site: str, pat_name: str, pat_secret: str, path: Path, project_name: str) -> str:
    """Publish (overwrite) a .twb/.twbx into a project. Used by the CI promote job.

    Publishing is a multipart upload, so this one call uses Tableau's own SDK.
    """
    import tableauserverclient as TSC  # imported lazily: only the promote job needs it

    auth = TSC.PersonalAccessTokenAuth(pat_name, pat_secret, site_id=site)
    server = TSC.Server(url, use_server_version=True)
    with server.auth.sign_in(auth):
        project = next((p for p in TSC.Pager(server.projects) if p.name == project_name), None)
        if project is None:
            raise SystemExit(f"Tableau project not found: {project_name}")
        item = server.workbooks.publish(TSC.WorkbookItem(project_id=project.id), str(path), TSC.Server.PublishMode.Overwrite)
        return item.id
