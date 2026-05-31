import asyncio
import hashlib
from fastapi import APIRouter, HTTPException, Response

from config import settings
from database import get_database, count_projects, count_projects_by_status, get_deployment_stats
from dependencies import _cache
from models import HealthResponse, SystemResponse
from observability import deployhub_active_containers, deployhub_projects_total, deployhub_pod_restarts_total, metrics_response
from utils.docker import check_docker_available, count_running_deployhub_containers
from utils.k8s import check_k8s_available, count_running_deployhub_deployments, get_all_deployment_restart_counts

router = APIRouter()

@router.get("/health", response_model=HealthResponse)
async def healthcheck() -> HealthResponse:
    return HealthResponse(status="ok")

@router.get("/api/stress")
def cpu_stress():
    """Artificially burn CPU to trigger the Horizontal Pod Autoscaler."""
    data = b"deployhub-stress-test"
    for _ in range(1000000):
        data = hashlib.sha256(data).digest()
    return {"status": "stressed", "result": data.hex()}

@router.get("/ready", response_model=HealthResponse)
async def readiness() -> HealthResponse:
    await get_database().command("ping")
    if settings.deployment_mode == "k8s":
        k8s_ok = await check_k8s_available()
        return HealthResponse(status="ready", details={"mongodb": "connected", "k8s": "connected" if k8s_ok else "unavailable"})
    docker_ok = await check_docker_available()
    return HealthResponse(status="ready", details={"mongodb": "connected", "docker": "connected" if docker_ok else "unavailable"})

@router.get("/api/system", response_model=SystemResponse)
async def get_system_endpoint() -> SystemResponse:
    async def _fetch():
        mongodb_available = True
        try:
            await get_database().command("ping")
        except Exception:
            mongodb_available = False
        if settings.deployment_mode == "k8s":
            running, env_ok = await asyncio.gather(count_running_deployhub_deployments(), check_k8s_available())
        else:
            running, env_ok = await asyncio.gather(count_running_deployhub_containers(), check_docker_available())
        project_count = await count_projects()
        queued_count = await count_projects_by_status("queued")
        deployhub_active_containers.set(running)
        deployhub_projects_total.set(project_count)
        active_count = await count_projects_by_status("building")
        return {
            "backend_version": settings.backend_version,
            "docker_available": env_ok,
            "mongodb_available": mongodb_available,
            "project_count": project_count,
            "running_container_count": running,
            "active_deployments": active_count,
            "queued_deployments": queued_count,
            "queue_depth": queued_count + active_count,
            "max_concurrent_builds": settings.max_concurrent_builds,
        }
    data = await _cache.get_or_set("system", _fetch)
    return SystemResponse(**data)

@router.get("/metrics")
async def metrics_endpoint() -> Response:
    async def _fetch():
        deployhub_projects_total.set(await count_projects())
        if settings.deployment_mode == "k8s":
            running_count, restart_counts = await asyncio.gather(
                count_running_deployhub_deployments(), get_all_deployment_restart_counts())
            deployhub_active_containers.set(running_count)
            for pod_name, (count, project_name) in restart_counts.items():
                deployhub_pod_restarts_total.labels(pod_name=pod_name, project_name=project_name).set(count)
        else:
            deployhub_active_containers.set(await count_running_deployhub_containers())
        payload, content_type = await metrics_response()
        return payload, content_type
    payload, content_type = await _cache.get_or_set("metrics", _fetch)
    return Response(content=payload, media_type=content_type)

@router.get("/api/stats")
async def get_stats_endpoint() -> dict:
    stats = await get_deployment_stats()
    by_status = {
        "running":  await count_projects_by_status("running"),
        "failed":   await count_projects_by_status("failed"),
        "stopped":  await count_projects_by_status("stopped"),
        "building": await count_projects_by_status("building"),
        "queued":   await count_projects_by_status("queued"),
    }
    return {**stats, "by_status": by_status}
