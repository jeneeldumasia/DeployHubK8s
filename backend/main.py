import asyncio
import json
import signal
import time as _time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Response, Request, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from config import settings
from database import (
    append_deployment_history,
    close_mongo_connection,
    connect_to_mongo,
    count_projects,
    count_projects_by_status,
    create_project,
    delete_project,
    get_database,
    get_project_by_id,
    get_project_by_normalized_repo_url,
    get_project_by_url_and_path,
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
from security import verify_github_signature
from utils.docker import check_docker_available, count_running_deployhub_containers, get_container_logs
from utils.k8s import check_k8s_available, count_running_deployhub_pods, get_pod_logs, get_all_pod_restart_counts
from utils.analyzer import RepoAnalyzer
from utils.git import GitError, normalize_repo_url, clone_or_update_repo
from worker import DeploymentWorker

# ── Rate limiter (#15) ────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])

def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(status_code=429, content={"detail": f"Rate limit exceeded: {exc.detail}"})

# ── WebSocket connection manager (#17) ────────────────────────────────────────
class _WSManager:
    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, project_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.setdefault(project_id, []).append(ws)

    def disconnect(self, project_id: str, ws: WebSocket) -> None:
        conns = self._connections.get(project_id, [])
        if ws in conns:
            conns.remove(ws)

    async def broadcast(self, project_id: str, payload: dict) -> None:
        dead: list[WebSocket] = []
        for ws in list(self._connections.get(project_id, [])):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(project_id, ws)

ws_manager = _WSManager()

# ── TTL cache for expensive system/metrics endpoints ─────────────────────────
class _TTLCache:
    def __init__(self, ttl: float = 5.0) -> None:
        self._ttl = ttl
        self._cache: dict = {}
        self._lock = asyncio.Lock()

    async def get_or_set(self, key: str, coro_factory):
        async with self._lock:
            entry = self._cache.get(key)
            if entry and (_time.monotonic() - entry["ts"]) < self._ttl:
                return entry["value"]
        value = await coro_factory()
        async with self._lock:
            self._cache[key] = {"value": value, "ts": _time.monotonic()}
        return value

_cache = _TTLCache(ttl=5.0)

# ── Worker ────────────────────────────────────────────────────────────────────
worker = DeploymentWorker(
    public_base_url=settings.public_base_url,
    generated_dockerfile_root=settings.generated_dockerfile_root,
    deployment_mode=settings.deployment_mode,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await connect_to_mongo()
    worker.start()

    loop = asyncio.get_running_loop()

    async def _handle_signal(sig: signal.Signals) -> None:
        log_event("app_shutdown_signal", signal=sig.name, active_deployments=worker.active_count())
        await worker.stop()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(_handle_signal(s)))
        except NotImplementedError:
            pass  # Windows

    try:
        yield
    finally:
        await worker.stop()
        await close_mongo_connection()
        log_event("app_shutdown_complete")


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def record_request_metrics(request: Request, call_next):
    timer = RequestTimer(request.method, request.url.path)
    response = await call_next(request)
    timer.observe(response.status_code)
    return response


@app.middleware("http")
async def log_slow_and_error_requests(request: Request, call_next):
    request_id = str(uuid.uuid4())[:8]
    t0 = _time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        log_event("http_error", request_id=request_id, method=request.method,
                  path=request.url.path, error=str(exc), error_type=type(exc).__name__)
        raise
    duration_ms = int((_time.perf_counter() - t0) * 1000)
    if response.status_code >= 400 or duration_ms > 2000:
        log_event("http_request", request_id=request_id, method=request.method,
                  path=request.url.path, status=response.status_code,
                  duration_ms=duration_ms,
                  level="error" if response.status_code >= 500 else "warn")
    response.headers["X-Request-ID"] = request_id
    return response


# ── Serializers ───────────────────────────────────────────────────────────────
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
        previous_image_tag=document.get("previous_image_tag"),
        created_at=document["created_at"],
        updated_at=document["updated_at"],
        last_deployed_at=document.get("last_deployed_at"),
        env_vars=document.get("env_vars", {}),
    )


def serialize_project_detail(document: dict) -> ProjectDetail:
    return ProjectDetail(
        **serialize_project_summary(document).model_dump(),
        normalized_repo_url=document["normalized_repo_url"],
        repo_path=document.get("repo_path"),
        dockerfile_path=document.get("dockerfile_path"),
        container_name=document.get("container_name"),
        deployment_history=document.get("deployment_history", []),
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


# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health", response_model=HealthResponse)
async def healthcheck() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/ready", response_model=HealthResponse)
async def readiness() -> HealthResponse:
    await get_database().command("ping")
    if settings.deployment_mode == "k8s":
        k8s_ok = await check_k8s_available()
        return HealthResponse(status="ready", details={"mongodb": "connected", "k8s": "connected" if k8s_ok else "unavailable"})
    docker_ok = await check_docker_available()
    return HealthResponse(status="ready", details={"mongodb": "connected", "docker": "connected" if docker_ok else "unavailable"})


# ── Analyze ───────────────────────────────────────────────────────────────────
@app.post("/api/analyze")
@limiter.limit("30/minute")
async def analyze_repository(request: Request) -> dict:
    body = await request.json()
    repo_url = body.get("repo_url")
    if not repo_url:
        raise HTTPException(status_code=400, detail="repo_url is required")
    try:
        normalized_url = normalize_repo_url(str(repo_url))
        repo_slug = normalized_url.rstrip("/").split("/")[-1].replace(".git", "")
        temp_id = f"_analyze_{abs(hash(normalized_url)) % 100000}"
        repo_path = await clone_or_update_repo(temp_id, normalized_url)
        analyzer = RepoAnalyzer(repo_path, repo_name=repo_slug)
        services = analyzer.analyze()
        for svc in services:
            if not svc.name or "_analyze_" in svc.name or svc.name == temp_id:
                svc.name = repo_slug
        return {"services": [s.__dict__ for s in services]}
    except GitError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ── Projects ──────────────────────────────────────────────────────────────────
@app.post("/api/projects", response_model=ProjectSummary)
@limiter.limit("20/minute")
async def create_project_endpoint(request: Request, payload: ProjectCreate) -> ProjectSummary:
    try:
        normalized_repo_url = normalize_repo_url(str(payload.repo_url))
    except GitError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    context_path = payload.context_path or ""
    existing = await get_project_by_url_and_path(normalized_repo_url, context_path)
    if existing:
        return serialize_project_summary(existing)

    project_id = str(uuid.uuid4())[:8]
    now = utc_now()
    document = {
        "id": project_id,
        "repo_url": str(payload.repo_url),
        "normalized_repo_url": normalized_repo_url,
        "context_path": context_path,
        "service_name": payload.service_name,
        "env_vars": payload.env_vars,
        "status": "queued",
        "dockerfile_path": None,
        "image_tag": None,
        "previous_image_tag": None,
        "container_id": None,
        "container_name": None,
        "assigned_port": None,
        "service_url": None,
        "build_logs": [],
        "last_error": None,
        "deployment_history": [],
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
@limiter.limit("60/minute")
async def list_projects_endpoint(request: Request) -> list[ProjectSummary]:
    projects = await list_projects()
    return [serialize_project_summary(p) for p in projects]


@app.get("/api/projects/{project_id}", response_model=ProjectDetail)
async def get_project_endpoint(project_id: str) -> ProjectDetail:
    project = await get_project_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return serialize_project_detail(project)


@app.get("/api/projects/{project_id}/history")
async def get_project_history(project_id: str) -> dict:
    """Return the deployment history for a project (last 50 deployments)."""
    project = await get_project_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return {
        "project_id": project_id,
        "service_name": project.get("service_name") or project.get("repo_url"),
        "deployment_history": project.get("deployment_history", []),
    }


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
    # Notify WebSocket subscribers
    await ws_manager.broadcast(project_id, {"type": "status_update", "status": "queued"})
    return ProjectActionResponse(message=f"{action.title()} queued", project_id=project_id, status="queued")


@app.post("/api/deploy/{project_id}", response_model=ProjectActionResponse)
async def deploy_project_endpoint(project_id: str) -> ProjectActionResponse:
    return await queue_deployment(project_id, action="deploy")


@app.post("/api/redeploy/{project_id}", response_model=ProjectActionResponse)
async def redeploy_project_endpoint(project_id: str) -> ProjectActionResponse:
    return await queue_deployment(project_id, action="redeploy")


@app.post("/api/webhooks/github/{project_id}")
@limiter.limit("100/hour")
async def github_webhook(project_id: str, request: Request) -> dict:
    await verify_github_signature(request)
    github_event = request.headers.get("X-GitHub-Event")
    if github_event == "ping":
        return {"message": "pong"}
    if github_event != "push":
        return {"message": f"Ignoring GitHub event: {github_event}"}
    project = await get_project_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    await queue_deployment(project_id, action="redeploy")
    log_event("webhook_received", project_id=project_id, event=github_event)
    return {"message": "Redeployment queued via GitHub webhook"}


@app.post("/api/stop/{project_id}", response_model=ProjectActionResponse)
async def stop_project_endpoint(project_id: str) -> ProjectActionResponse:
    try:
        result = await worker.stop_project(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    log_event("project_stopped", project_id=project_id)
    await ws_manager.broadcast(project_id, {"type": "status_update", "status": "stopped"})
    return ProjectActionResponse(message=result["message"], project_id=project_id, status=result["status"])


@app.delete("/api/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
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


# ── Logs ──────────────────────────────────────────────────────────────────────
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
            current = await get_project_by_id(project_id)
            if not current:
                payload = {"project_id": project_id, "status": "failed", "build_logs": [], "runtime_logs": []}
            else:
                payload = {
                    "project_id": project_id,
                    "status": current.get("status"),
                    "last_error": current.get("last_error"),
                    "updated_at": current.get("updated_at").isoformat() if current.get("updated_at") else None,
                    "build_logs": current.get("build_logs", []),
                    "runtime_logs": await get_runtime_logs(current),
                }
            serialized = json.dumps(payload)
            if serialized != last_payload:
                last_payload = serialized
                yield f"data: {serialized}\n\n"
            await asyncio.sleep(2 if payload.get("status") in {"failed", "running", "stopped"} else 1)

    return StreamingResponse(event_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


# ── WebSocket real-time updates (#17) ─────────────────────────────────────────
@app.websocket("/ws/projects/{project_id}")
async def websocket_project(websocket: WebSocket, project_id: str) -> None:
    """
    Real-time status updates for a project.
    The client connects and receives JSON messages whenever the project status changes.
    Falls back to SSE stream if WebSocket is unavailable.
    """
    await ws_manager.connect(project_id, websocket)
    try:
        # Send current state immediately on connect
        project = await get_project_by_id(project_id)
        if project:
            await websocket.send_json({
                "type": "status_update",
                "status": project.get("status"),
                "service_url": project.get("service_url"),
                "last_error": project.get("last_error"),
            })
        # Keep alive — client can send pings
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(project_id, websocket)


# ── System & Metrics ──────────────────────────────────────────────────────────
@app.get("/api/system", response_model=SystemResponse)
async def get_system_endpoint() -> SystemResponse:
    async def _fetch():
        mongodb_available = True
        try:
            await get_database().command("ping")
        except Exception:
            mongodb_available = False
        if settings.deployment_mode == "k8s":
            running, env_ok = await asyncio.gather(count_running_deployhub_pods(), check_k8s_available())
        else:
            running, env_ok = await asyncio.gather(count_running_deployhub_containers(), check_docker_available())
        project_count = await count_projects()
        queued_count = await count_projects_by_status("queued")
        deployhub_active_containers.set(running)
        deployhub_projects_total.set(project_count)
        return {
            "backend_version": settings.backend_version,
            "docker_available": env_ok,
            "mongodb_available": mongodb_available,
            "project_count": project_count,
            "running_container_count": running,
            "active_deployments": worker.active_count(),
            "queued_deployments": queued_count,
        }
    data = await _cache.get_or_set("system", _fetch)
    return SystemResponse(**{**data, "active_deployments": worker.active_count()})


@app.get("/metrics")
async def metrics_endpoint() -> Response:
    async def _fetch():
        deployhub_projects_total.set(await count_projects())
        if settings.deployment_mode == "k8s":
            pod_count, restart_counts = await asyncio.gather(
                count_running_deployhub_pods(), get_all_pod_restart_counts())
            deployhub_active_containers.set(pod_count)
            for pod_name, count in restart_counts.items():
                deployhub_pod_restarts_total.labels(pod_name=pod_name).set(count)
        else:
            deployhub_active_containers.set(await count_running_deployhub_containers())
        payload, content_type = await metrics_response()
        return payload, content_type
    payload, content_type = await _cache.get_or_set("metrics", _fetch)
    return Response(content=payload, media_type=content_type)


@app.get("/api/projects/{project_id}/health")
async def get_project_health_endpoint(project_id: str) -> dict:
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
        "pod": {"name": container_name, "restart_count": restart_count},
    }
