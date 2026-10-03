"""Command line entry point: python -m biops <command>.

Every command exits non-zero when something failed, so Jenkins or GitHub
Actions marks the run red without any extra glue.
"""
from __future__ import annotations

import argparse
import csv
import logging
from datetime import date
from pathlib import Path

from biops import tasks
from biops.base import job
from biops.config import Settings
from biops.store import Store

REPORT_VIEWS = ["v_latest_health", "v_availability_7d", "v_daily_views", "v_stale_content", "v_recent_jobs"]


def _print_table(title: str, cols: list[str], rows: list[tuple]) -> None:
    print(f"\n== {title} ==")
    if not rows:
        print("(no rows)")
        return
    cells = [[("" if v is None else str(v))[:48] for v in row] for row in rows]
    widths = [max(len(c), *(len(r[i]) for r in cells)) for i, c in enumerate(cols)]
    print("  ".join(c.ljust(w) for c, w in zip(cols, widths)))
    print("  ".join("-" * w for w in widths))
    for r in cells:
        print("  ".join(v.ljust(w) for v, w in zip(r, widths)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="biops", description="Ops automation for Tableau and MicroStrategy.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("health", help="run platform health checks, alert on failure")
    for name, text in (("collect", "snapshot content inventory and usage"), ("backup", "back up content via REST")):
        p = sub.add_parser(name, help=text)
        p.add_argument("--date", type=date.fromisoformat, default=date.today(), help="snapshot date (YYYY-MM-DD)")
    sub.add_parser("refresh", help="trigger extract refreshes / cube republishes")
    p = sub.add_parser("report", help="print the monitoring views")
    p.add_argument("--csv", type=Path, metavar="DIR", help="also write each view to DIR as CSV (dashboard source)")
    p = sub.add_parser("publish", help="publish a workbook to Tableau (used by the promote job)")
    p.add_argument("workbook", type=Path)
    p.add_argument("--project", required=True)
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s %(message)s", datefmt="%H:%M:%S")
    s = Settings.from_env()
    store = Store(s.db_path, s.env)

    if args.command == "health":
        ok = tasks.run_health(s, store)
    elif args.command == "collect":
        ok = tasks.run_collect(s, store, args.date)
    elif args.command == "backup":
        ok = tasks.run_backup(s, store, args.date)
    elif args.command == "refresh":
        ok = tasks.run_refresh(s, store)
    elif args.command == "publish":
        from biops.tableau import publish_workbook

        wb_id = publish_workbook(s.tableau_url, s.tableau_site, s.tableau_pat_name, s.tableau_pat_secret,
                                 args.workbook, args.project)
        store.add_jobs("publish", [job("tableau", args.workbook.name, True, f"published as {wb_id}")])
        logging.info("published %s to project %s (%s)", args.workbook.name, args.project, wb_id)
        ok = True
    else:
        for view in REPORT_VIEWS:
            cols, rows = store.query(f"SELECT * FROM {view}")
            _print_table(view, cols, rows)
            if args.csv:
                args.csv.mkdir(parents=True, exist_ok=True)
                with open(args.csv / f"{view}.csv", "w", newline="") as fh:
                    csv.writer(fh).writerows([cols, *rows])
        ok = True
    return 0 if ok else 1
