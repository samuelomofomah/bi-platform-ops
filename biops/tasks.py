"""The four operations, written once and run against whichever platforms are configured."""
from __future__ import annotations

import hashlib
import logging
from datetime import date
from pathlib import Path

from biops import aws
from biops.config import Settings
from biops.mock import MockClient
from biops.mstr import MstrClient
from biops.store import Store
from biops.tableau import TableauClient

log = logging.getLogger("biops")


def build_clients(s: Settings) -> list:
    if s.mock:
        return [MockClient("tableau"), MockClient("microstrategy")]
    clients = []
    if s.tableau_url:
        clients.append(
            TableauClient(s.tableau_url, s.tableau_site, s.tableau_pat_name, s.tableau_pat_secret, s.tableau_backup_project)
        )
    if s.mstr_url:
        clients.append(MstrClient(s.mstr_url, s.mstr_user, s.mstr_password, s.mstr_login_mode, s.mstr_cluster_check))
    if not clients:
        raise SystemExit("Nothing to do: set TABLEAU_URL and/or MSTR_URL, or BIOPS_MOCK=1 for a dry run.")
    return clients


def _targets(s: Settings, platform: str) -> list[str]:
    return s.tableau_refresh_datasources if platform == "tableau" else s.mstr_refresh_cubes


def run_health(s: Settings, store: Store) -> bool:
    rows = []
    for client in build_clients(s):
        try:
            rows += client.health()
        finally:
            client.close()
    store.add_health(rows)
    failed = [r for r in rows if r["status"] == "fail"]
    for r in rows:
        log.log(logging.ERROR if r["status"] == "fail" else logging.INFO,
                "%-13s %-45s %-4s %s", r["platform"], r["check_name"], r["status"], r["detail"])
    if failed:
        body = "\n".join(f"{r['platform']} / {r['check_name']}: {r['detail']}" for r in failed)
        aws.alert(s.sns_topic_arn, f"[{s.env}] BI platform health: {len(failed)} check(s) failing", body)
    return not failed


def run_collect(s: Settings, store: Store, as_of: date) -> bool:
    """Snapshot what content exists and how much it is used."""
    ok = True
    for client in build_clients(s):
        try:
            client.connect()
            inventory, usage = client.inventory(), client.usage(as_of)
            store.add_inventory(as_of.isoformat(), inventory)
            store.add_usage(as_of.isoformat(), usage)
            log.info("%-13s %d objects, %d usage rows for %s", client.platform, len(inventory), len(usage), as_of)
        except Exception as exc:
            ok = False
            log.error("%-13s collect failed: %s: %s", client.platform, type(exc).__name__, exc)
        finally:
            client.close()
    return ok


def run_backup(s: Settings, store: Store, as_of: date) -> bool:
    ok = True
    for client in build_clients(s):
        dest = Path(s.backup_dir) / s.env / as_of.isoformat() / client.platform
        try:
            client.connect()
            rows = client.backup(dest)
        except Exception as exc:
            ok = False
            log.error("%-13s backup failed: %s: %s", client.platform, type(exc).__name__, exc)
            continue
        finally:
            client.close()
        files = []
        for r in rows:
            if r["status"] == "ok" and r["path"]:
                path = Path(r["path"])
                r["bytes"] = path.stat().st_size
                r["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
                files.append(path)
        store.add_jobs("backup", rows)
        aws.upload_backups(s.s3_bucket, f"{s.env}/{as_of.isoformat()}/{client.platform}", files)
        bad = sum(r["status"] == "fail" for r in rows)
        ok = ok and not bad
        log.info("%-13s backed up %d item(s), %d failed -> %s", client.platform, len(files), bad, dest)
    return ok


def run_refresh(s: Settings, store: Store) -> bool:
    ok = True
    for client in build_clients(s):
        targets = _targets(s, client.platform)
        if not targets and not s.mock:
            log.info("%-13s no refresh targets configured, skipping", client.platform)
            continue
        try:
            client.connect()
            rows = client.refresh(targets)
        except Exception as exc:
            ok = False
            log.error("%-13s refresh failed: %s: %s", client.platform, type(exc).__name__, exc)
            continue
        finally:
            client.close()
        store.add_jobs("refresh", rows)
        for r in rows:
            log.log(logging.ERROR if r["status"] == "fail" else logging.INFO,
                    "%-13s %-40s %-4s %s", r["platform"], r["target"], r["status"], r["detail"])
        ok = ok and all(r["status"] == "ok" for r in rows)
    return ok
