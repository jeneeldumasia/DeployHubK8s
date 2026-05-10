import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from config import settings
from database import (
    close_mongo_connection,
    connect_to_mongo,
    count_projects,
    count_projects_by_status,
    create_project,
    delete_project,
    get_database,
    get_project_by_id,
    get_project_by_normalized_repo_url,
    list_projects,
    update_project,
    utc_now,
)
from models import (
    ApiErrorResponse,
    HealthResponse,
    LogsResponse,
    ProjectActionResponse,
    ProjectCreate,
    ProjectDetail,
    ProjectSummary,
    SystemResponse,
)
from observability import (
    RequestTimer,
    deployhub_active_containers,
    deployhub_deployments_total,
    deployhub_projects_total,
    deployhub_pod_restarts_total,
    log_event,
    metrics_response,
)
from utils.docker import check_docker_available, count_running_deployhub_containers, get_container_logs
from utils.k8s import check_k8s_available, count_running_deployhub_pods, get_pod_logs, get_all_pod_restart_counts  # all async
from utils.analyzer import RepoAnalyzer
from utils.git import GitError, normalize_repo_url, clone_or_update_repo
from worker import DeploymentWorker

worker = DeploymentWorker(
    public_base_url=settings.public_base_url,
    generated_dockerfile_root=settings.generated_dockerfile_root,
    deployment_mode=settings.deployment_mode,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await connect_to_mongo()
    worker.start()
    yield
    await worker.stop()
    await close_mongo_connection()


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def record_request_metrics(request, call_next):
    timer = RequestTimer(request.method, request.url.path)
    response = await call_next(request)
    timer.observe(response.status_code)
    return response


def serialize_project_summary(document: dict) -> ProjectSummary:
    return ProjectSummary(
        id=str(document["_id"]),
        repo_url=document["repo_url"],
        context_path=document.get("context_path", ""),
        service_name=document.get("service_name"),
        status=document["status"],
        project_type=document.get("project_type", "unknown"),
        assigned_port=document.get("assigned_port"),
        service_url=document.get("service_url"),
        last_error=document.get("last_error"),
        container_id=document.get("container_id"),
        image_tag=document.get("image_tag"),
        created_at=document["created_at"],
        updated_at=document["updated_at"],
        last_deployed_at=document.get("last_deployed_at"),
    )


def serialize_project_detail(document: dict) -> ProjectDetail:
    return ProjectDetail(
        **serialize_project_summary(document).model_dump(),
        normalized_repo_url=document["normalized_repo_url"],
        repo_path=document.get("repo_path"),
        dockerfile_path=document.get("dockerfile_path"),
        container_name=document.get("container_name"),
    )


async def get_runtime_logs(project: dict) -> list[str]:
    if settings.deployment_mode == "k8s":
        container_name = project.get("container_name")
        if not container_name:
            return []
        return await get_pod_logs(container_name)
    container_id = project.get("container_id")
    if not container_id:
        return []
    return await get_container_logs(container_id)


@app.get("/health", response_model=HealthResponse, responses={500: {"model": ApiErrorResponse}})
async def healthcheck() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/ready", response_model=HealthResponse, responses={500: {"model": ApiErrorResponse}})
async def readiness() -> HealthResponse:
    await get_database().command("ping")
    if settings.deployment_mode == "k8s":
        k8s_available = await check_k8s_available()
        return HealthResponse(status="ready", details={"mongodb": "connected", "k8s": "connected" if k8s_available else "unavailable"})
    else:
        docker_available = await check_docker_available()
        return HealthResponse(status="ready", details={"mongodb": "connected", "docker": "connected" if docker_available else "unavailable"})


@app.post("/api/analyze")
async def analyze_repository(request: dict):
    repo_url = request.get("repo_url")
    if not repo_url:
        raise HTTPException(status_code=400, detail="repo_url is required")
    
    try:
        temp_id = "analysis-" + str(hash(repo_url))[:8]
        repo_path = await clone_or_update_repo(temp_id, repo_url)
        
        analyzer = RepoAnalyzer(repo_path)
        services = analyzer.analyze()
        
        return {"services": [s.__dict__ for s in services]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/projects", response_model=ProjectSummary, responses={400: {"model": ApiErrorResponse}})
async def create_project_endpoint(payload: ProjectCreate) -> ProjectSummary:
    try:
        normalized_repo_url = normalize_repo_url(str(payload.repo_url))
    except GitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    context_path = payload.context_path or ""
    existing = await get_project_by_url_and_path(normalized_repo_url, context_path)
    if existing:
        return serialize_project_summary(existing)

    project_id = str(uuid.uuid4())[:8]
    document = {
        "id": project_id,
        "repo_url": str(payload.repo_url),
        "normalized_repo_url": normalized_repo_url,
        "context_path": context_path,
        "service_name": payload.service_name,
        "status": "queued",
        "dockerfile_path": None,
        "image_tag": None,
        "container_id": None,
        "container_name": None,
        "assigned_port": None,
        "service_url": None,
        "build_logs": [],
        "last_error": None,
        "created_at": now,
        "updated_at": now,
        "last_deployed_at": None,
    }
    project_id = await create_project(document)
    project = await get_project_by_id(project_id)
    deployhub_projects_total.set(await count_projects())
    log_event("project_created", project_id=project_id, repo_url=str(payload.repo_url))
    return serialize_project_summary(project)


@app.get("/api/projects", response_model=list[ProjectSummary])
async def list_projects_endpoint() -> list[ProjectSummary]:
    projects = await list_projects()
    return [serialize_project_summary(project) for project in projects]


@app.get("/api/projects/{project_id}", response_model=ProjectDetail, responses={404: {"model": ApiErrorResponse}})
async def get_project_endpoint(project_id: str) -> ProjectDetail:
    project = await get_project_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return serialize_project_detail(project)


async def queue_deployment(project_id: str, action: str) -> ProjectActionResponse:
    project = await get_project_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if project["status"] == "deleting":
        raise HTTPException(status_code=409, detail="Project is being deleted")

    if not await worker.enqueue(project_id, action=action):
        return ProjectActionResponse(message="Deployment already queued", project_id=project_id, status=project["status"])

    await update_project(project_id, {"status": "queued", "last_error": None})
    deployhub_deployments_total.labels(action=action).inc()
    log_event("deployment_queued", project_id=project_id, action=action)
    return ProjectActionResponse(message=f"{action.title()} queued", project_id=project_id, status="queued")


@app.post("/api/deploy/{project_id}", response_model=ProjectActionResponse, responses={404: {"model": ApiErrorResponse}})
async def deploy_project_endpoint(project_id: str) -> ProjectActionResponse:
    return await queue_deployment(project_id, action="deploy")


@app.post("/api/redeploy/{project_id}", response_model=ProjectActionResponse, responses={404: {"model": ApiErrorResponse}})
async def redeploy_project_endpoint(project_id: str) -> ProjectActionResponse:
    return await queue_deployment(project_id, action="redeploy")


@app.post("/api/webhooks/github/{project_id}")
async def github_webhook(project_id: str, request: Request):
    github_event = request.headers.get("X-GitHub-Event")
    if github_event == "ping":
        return {"message": "pong"}
    
    if github_event != "push":
        return {"message": f"Ignoring GitHub event: {github_event}"}

    project = await get_project_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Queue a redeployment automatically
    await queue_deployment(project_id, action="redeploy")
    log_event("webhook_received", project_id=project_id, event=github_event)
    return {"message": "Redeployment queued via GitHub webhook"}


@app.post("/api/stop/{project_id}", response_model=ProjectActionResponse, responses={404: {"model": ApiErrorResponse}})
async def stop_project_endpoint(project_id: str) -> ProjectActionResponse:
    try:
        result = await worker.stop_project(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    log_event("project_stopped", project_id=project_id)
    return ProjectActionResponse(message=result["message"], project_id=project_id, status=result["status"])


@app.delete("/api/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT, responses={404: {"model": ApiErrorResponse}})
async def delete_project_endpoint(project_id: str) -> Response:
    project = await get_project_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project_id in worker.active_project_ids:
        raise HTTPException(status_code=409, detail="Project is currently building and cannot be deleted")

    await update_project(project_id, {"status": "deleting"})
    await worker.delete_project_resources(project)
    await delete_project(project_id)
    deployhub_projects_total.set(await count_projects())
    log_event("project_deleted", project_id=project_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/api/logs/{project_id}", response_model=LogsResponse)
async def get_logs_endpoint(project_id: str) -> LogsResponse:
    project = await get_project_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return LogsResponse(
        project_id=project_id,
        status=project.get("status", "failed"),
        last_error=project.get("last_error"),
        updated_at=project.get("updated_at"),
        build_logs=project.get("build_logs", []),
        runtime_logs=await get_runtime_logs(project),
    )


@app.get("/api/logs/{project_id}/stream")
async def stream_logs_endpoint(project_id: str) -> StreamingResponse:
    project = await get_project_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    async def event_stream():
        last_payload: str | None = None
        while True:
            current_project = await get_project_by_id(project_id)
            if not current_project:
                payload = {"project_id": project_id, "status": "failed", "build_logs": [], "runtime_logs": []}
            else:
                payload = {
                    "project_id": project_id,
                    "status": current_project.get("status"),
                    "last_error": current_project.get("last_error"),
                    "updated_at": current_project.get("updated_at").isoformat() if current_project.get("updated_at") else None,
                    "build_logs": current_project.get("build_logs", []),
                    "runtime_logs": await get_runtime_logs(current_project),
                }

            serialized = json.dumps(payload)
            if serialized != last_payload:
                last_payload = serialized
                yield f"data: {serialized}\n\n"

            if payload.get("status") in {"failed", "running", "stopped"}:
                await asyncio.sleep(2)
            else:
                await asyncio.sleep(1)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@app.get("/api/system", response_model=SystemResponse)
async def get_system_endpoint() -> SystemResponse:
    mongodb_available = True
    try:
        await get_database().command("ping")
    except Exception:
        mongodb_available = False

    if settings.deployment_mode == "k8s":
        running_container_count = await count_running_deployhub_pods()
        env_available = await check_k8s_available()
    else:
        running_container_count = await count_running_deployhub_containers()
        env_available = await check_docker_available()

    deployhub_active_containers.set(running_container_count)
    deployhub_projects_total.set(await count_projects())
    return SystemResponse(
        backend_version=settings.backend_version,
        docker_available=env_available,
        mongodb_available=mongodb_available,
        project_count=await count_projects(),
        running_container_count=running_container_count,
        active_deployments=worker.active_count(),
        queued_deployments=await count_projects_by_status("queued"),
    )


@app.get("/metrics")
async def metrics_endpoint() -> Response:
    deployhub_projects_total.set(await count_projects())
    if settings.deployment_mode == "k8s":
        deployhub_active_containers.set(await count_running_deployhub_pods())
        # Refresh per-pod restart counts
        restart_counts = await get_all_pod_restart_counts()
        for pod_name, count in restart_counts.items():
            deployhub_pod_restarts_total.labels(pod_name=pod_name).set(count)
    else:
        deployhub_active_containers.set(await count_running_deployhub_containers())
    metrics_payload, content_type = await metrics_response()
    return Response(content=metrics_payload, media_type=content_type)


@app.get("/api/projects/{project_id}/health")
async def get_project_health_endpoint(project_id: str):
    """
    Returns the live health status of a deployed project's pod.
    Checks pod phase, container readiness, and restart count.
    """
    project = await get_project_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if settings.deployment_mode != "k8s":
        raise HTTPException(status_code=400, detail="Health endpoint only available in k8s mode")

    container_name = project.get("container_name")
    if not container_name or project.get("status") not in ("running", "failed"):
        return {"project_id": project_id, "status": project.get("status"), "pod": None}

    from utils.k8s import get_pod_restart_count
    restart_count = await get_pod_restart_count(container_name)
    deployhub_pod_restarts_total.labels(pod_name=container_name).set(restart_count)

    return {
        "project_id": project_id,
        "status": project.get("status"),
        "service_url": project.get("service_url"),
        "pod": {
            "name": container_name,
            "restart_count": restart_count,
        },
    }
