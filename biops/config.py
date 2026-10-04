"""All settings come from environment variables, so the same image runs
unchanged in dev, QA and prod and secrets stay in the CI credential store."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _list(name: str) -> list[str]:
    return [x.strip() for x in os.environ.get(name, "").split(",") if x.strip()]


@dataclass(frozen=True)
class Settings:
    env: str = "dev"
    mock: bool = False
    db_path: str = "biops.db"
    backup_dir: str = "backups"
    s3_bucket: str = ""
    sns_topic_arn: str = ""

    tableau_url: str = ""
    tableau_site: str = ""  # contentUrl; empty string = Default site
    tableau_pat_name: str = ""
    tableau_pat_secret: str = ""
    tableau_backup_project: str = ""  # optional: only back up this project
    tableau_refresh_datasources: list[str] = field(default_factory=list)

    mstr_url: str = ""  # e.g. https://host/MicroStrategyLibrary
    mstr_user: str = ""
    mstr_password: str = ""
    mstr_login_mode: int = 1  # 1 = standard, 16 = LDAP, 8 = guest
    mstr_cluster_check: bool = True  # needs an administrator privilege; set MSTR_CLUSTER_CHECK=0 to skip
    mstr_refresh_cubes: list[str] = field(default_factory=list)  # "projectId:cubeId"

    @classmethod
    def from_env(cls) -> Settings:
        e = os.environ.get
        return cls(
            env=e("BIOPS_ENV", "dev"),
            mock=e("BIOPS_MOCK", "") not in ("", "0", "false"),
            db_path=e("BIOPS_DB", "biops.db"),
            backup_dir=e("BIOPS_BACKUP_DIR", "backups"),
            s3_bucket=e("BIOPS_S3_BUCKET", ""),
            sns_topic_arn=e("BIOPS_SNS_TOPIC_ARN", ""),
            tableau_url=e("TABLEAU_URL", ""),
            tableau_site=e("TABLEAU_SITE", ""),
            tableau_pat_name=e("TABLEAU_PAT_NAME", ""),
            tableau_pat_secret=e("TABLEAU_PAT_SECRET", ""),
            tableau_backup_project=e("TABLEAU_BACKUP_PROJECT", ""),
            tableau_refresh_datasources=_list("TABLEAU_REFRESH_DATASOURCES"),
            mstr_url=e("MSTR_URL", ""),
            mstr_user=e("MSTR_USER", ""),
            mstr_password=e("MSTR_PASSWORD", ""),
            mstr_login_mode=int(e("MSTR_LOGIN_MODE") or 1),
            mstr_cluster_check=e("MSTR_CLUSTER_CHECK", "") not in ("0", "false"),
            mstr_refresh_cubes=_list("MSTR_REFRESH_CUBES"),
        )
