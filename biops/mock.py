"""Offline stand-ins for both platforms (BIOPS_MOCK=1).

Lets the whole pipeline run in CI, in a demo, or on a laptop with no Tableau
or MicroStrategy licence. Set BIOPS_MOCK_FAIL=1 to simulate an unloaded
project and see the alerting path.
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

from biops.base import job, result

_EPOCH = date(2026, 1, 1)
_CONTENT = {
    "tableau": [
        ("workbook", "wb-001", "Seller Performance", "Marketplace", "2026-09-28T14:02:00Z"),
        ("workbook", "wb-002", "Finance Close Pack", "Finance", "2026-09-30T09:15:00Z"),
        ("workbook", "wb-003", "Legacy Shipping KPIs", "Operations", "2025-01-10T08:00:00Z"),
        ("datasource", "ds-001", "orders_extract", "Marketplace", "2026-10-01T02:10:00Z"),
    ],
    "microstrategy": [
        ("report", "rp-001", "Daily GMV by Region", "Enterprise Reporting", "2026-09-29T11:00:00.000+0000"),
        ("dossier", "do-001", "Executive Scorecard", "Enterprise Reporting", "2026-09-12T16:40:00.000+0000"),
        ("report", "rp-002", "2023 Promo Lift (old)", "Marketing Analytics", "2024-11-03T10:00:00.000+0000"),
    ],
}
# (view id, name, parent workbook, views gained per day)
_VIEWS = [
    ("vw-001", "Overview", "wb-001", 42),
    ("vw-002", "Top Sellers", "wb-001", 17),
    ("vw-003", "Month End", "wb-002", 9),
    ("vw-004", "Carrier Scorecard", "wb-003", 0),
]


class MockClient:
    def __init__(self, platform: str):
        self.platform = platform
        self.fail = os.environ.get("BIOPS_MOCK_FAIL", "") not in ("", "0")

    def connect(self) -> None: ...

    def close(self) -> None: ...

    def health(self) -> list[dict]:
        p = self.platform
        if p == "tableau":
            return [
                result(p, "server_reachable", True, "version 2025.1.4 (mock)", 38),
                result(p, "pat_sign_in", True, "site id mock-site", 121),
            ]
        loaded = not self.fail
        return [
            result(p, "library_reachable", True, "iServer 11.5.0 (mock)", 44),
            result(p, "login", True, "logged in as svc_biops", 96),
            result(p, "node:mstr-node-1", True, "running"),
            result(p, "project:Enterprise Reporting@mstr-node-1", True, "loaded"),
            result(p, "project:Marketing Analytics@mstr-node-1", loaded, "loaded" if loaded else "unloaded"),
        ]

    def inventory(self) -> list[dict]:
        return [
            {"platform": self.platform, "object_type": t, "object_id": i, "name": n, "project": pr,
             "owner": "svc_biops", "updated_at": u}
            for t, i, n, pr, u in _CONTENT[self.platform]
        ]

    def usage(self, as_of: date | None = None) -> list[dict]:
        if self.platform != "tableau":
            return []
        days = ((as_of or date.today()) - _EPOCH).days
        return [
            {"platform": "tableau", "object_id": i, "name": n, "parent_id": wb, "total_views": max(days, 0) * rate}
            for i, n, wb, rate in _VIEWS
        ]

    def backup(self, dest: Path) -> list[dict]:
        dest.mkdir(parents=True, exist_ok=True)
        out = []
        if self.platform == "tableau":
            for t, i, n, _, _ in _CONTENT["tableau"]:
                if t == "workbook":
                    path = dest / f"{n.replace(' ', '_')}_{i}.twbx"
                    path.write_bytes(b"mock workbook " + i.encode())
                    out.append(job("tableau", n, True, "downloaded", str(path)))
        else:
            path = dest / "Enterprise_Reporting_manifest.json"
            path.write_text(json.dumps(self.inventory(), indent=2))
            out.append(job(self.platform, "Enterprise Reporting", True, "3 objects", str(path)))
        return out

    def refresh(self, targets: list[str]) -> list[dict]:
        targets = targets or (["ds-001"] if self.platform == "tableau" else ["proj-1:cube-001"])
        return [job(self.platform, t, True, "queued (mock)") for t in targets]
