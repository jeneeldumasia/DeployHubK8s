"""Best-effort ECR image cleanup when a project is deleted."""

from __future__ import annotations

import asyncio
from functools import partial

import boto3
from botocore.exceptions import ClientError

from config import settings
from observability import log_event


def _delete_ecr_images_sync(project_id: str) -> dict:
    registry = settings.ecr_registry.rstrip("/")
    if ".dkr.ecr." not in registry:
        return {"status": "skipped", "reason": "not_ecr"}

    repo_name = registry.split("/")[-1]
    ecr = boto3.client("ecr", region_name=settings.aws_region)
    try:
        resp = ecr.batch_delete_image(
            repositoryName=repo_name,
            imageIds=[{"imageTag": project_id}],
        )
        deleted = resp.get("imageIds", [])
        failures = resp.get("failures", [])
        return {"status": "ok", "deleted": len(deleted), "failures": len(failures)}
    except ClientError as exc:
        return {"status": "error", "error": str(exc)}


async def delete_project_ecr_images(project_id: str) -> None:
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, partial(_delete_ecr_images_sync, project_id))
    if result.get("status") == "ok":
        log_event("ecr_cleanup_success", project_id=project_id, deleted=result.get("deleted", 0))
    elif result.get("status") == "error":
        log_event("ecr_cleanup_failed", project_id=project_id, error=result.get("error"))
    else:
        log_event("ecr_cleanup_skipped", project_id=project_id, reason=result.get("reason"))
