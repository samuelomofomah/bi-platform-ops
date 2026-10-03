"""Optional AWS hooks: ship backups to S3 and raise alerts through SNS.
Both are no-ops unless the bucket / topic is configured, and boto3 is only
imported when needed. Credentials come from the runner's IAM role."""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("biops.aws")


def upload_backups(bucket: str, prefix: str, paths: list[Path]) -> None:
    if not bucket or not paths:
        return
    import boto3

    s3 = boto3.client("s3")
    for path in paths:
        key = f"{prefix}/{path.name}"
        s3.upload_file(str(path), bucket, key, ExtraArgs={"ServerSideEncryption": "AES256"})
        log.info("uploaded s3://%s/%s", bucket, key)


def alert(topic_arn: str, subject: str, message: str) -> None:
    if not topic_arn:
        return
    import boto3

    boto3.client("sns").publish(TopicArn=topic_arn, Subject=subject[:100], Message=message)
    log.info("alert sent to %s", topic_arn)
