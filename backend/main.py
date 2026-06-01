import asyncio
import json
import signal
import time as _time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

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
    get_deployment_stats,
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
from security import (
    generate_webhook_secret,
    hash_webhook_secret,
    verify_github_signature,
    verify_project_webhook_signature,
)
from utils.ecr_cleanup import delete_project_ecr_images
from utils.docker import check_docker_available, count_running_deployhub_containers, get_container_logs
from utils.k8s import (
    check_k8s_available,
    count_running_deployhub_deployments,
    get_all_deployment_restart_counts,
    get_namespace_resources,
    get_deployment_logs,
    get_pod_status,
)
from utils.analyzer import RepoAnalyzer
from utils.git import GitError, normalize_repo_url, clone_or_update_repo
from dependencies import limiter, ws_manager, _cache, redis_client

def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(status_code=429, content={"error": "Too many requests, slow down."})


async def _reconcile_pod_states() -> None:
    """
    On startup, find all projects marked 'running' in MongoDB and verify
    their pods still exist in k8s. Bare Pods are not rescheduled after a
    node restart — without this, the UI shows stale 'running' status forever.
    """
    await asyncio.sleep(10)  # give k8s client time to initialise
    try:
        from utils.k8s import _get_k8s_client
        from kubernetes.client.rest import ApiException
        running_projects = await list_projects()
        for project in running_projects:
            if project.get("status") != "running":
                continue
            container_name = project.get("container_name")
            if not container_name:
                continue
            try:
                loop = asyncio.get_running_loop()
                v1 = await loop.run_in_executor(None, _get_k8s_client)
                await loop.run_in_executor(
                    None,
                    lambda: v1.read_namespaced_pod(name=container_name, namespace=settings.apps_namespace)
                )
            except ApiException as e:
                if e.status == 404:
                    project_id = str(project["_id"])
                    await update_project(project_id, {
                        "status": "failed",
                        "last_error": "Pod not found after restart — redeploy to restore",
                    })
                    log_event("pod_reconciled_missing", project_id=project_id, pod=container_name)
            except Exception:
                pass  # reconciliation is best-effort
    except Exception as exc:
        log_event("reconciliation_error", error=str(exc))


@asynccontextmanager
async def lifespan(_: FastAPI):
    await connect_to_mongo()

    # ── Startup reconciliation ────────────────────────────────────────────────
    # Bare Pods (unlike Deployments) are not rescheduled after a node restart.
    # On startup, check every project marked "running" in MongoDB and verify
    # its pod actually exists in k8s. If not, mark it "failed" so the UI
    # reflects reality instead of showing stale "running" status.
    if settings.deployment_mode == "k8s":
        asyncio.create_task(_reconcile_pod_states())

    loop = asyncio.get_running_loop()

    async def _handle_signal(sig: signal.Signals) -> None:
        log_event("app_shutdown_signal", signal=sig.name)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda s=sig: asyncio.create_task(_handle_signal(s)))
        except NotImplementedError:
            pass  # Windows

    try:
        yield
    finally:
        await close_mongo_connection()
        log_event("app_shutdown_complete")


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)

# Setup OpenTelemetry Tracing
resource = Resource(attributes={"service.name": "deployhub-backend"})
provider = TracerProvider(resource=resource)
processor = BatchSpanProcessor(OTLPSpanExporter(endpoint="http://jaeger:4317", insecure=True))
provider.add_span_processor(processor)
trace.set_tracer_provider(provider)
FastAPIInstrumentor.instrument_app(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from routers import system
app.include_router(system.router)


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
        last_good_image=document.get("last_good_image"),
        has_webhook_secret=bool(document.get("webhook_secret") or document.get("webhook_secret_hash")),
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
        return await get_deployment_logs(container_name)
    container_id = project.get("container_id")
    if not container_id:
        return []
    return await get_container_logs(container_id)


# ── Health endpoints moved to routers/system.py ─────────────────────────────


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
@limiter.limit("10/minute")
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
    
    # Automatically queue the initial deployment on creation
    await redis_client.rpush("deployhub_queue", json.dumps({"project_id": project_id, "action": "deploy"}))
    await ws_manager.broadcast(project_id, {"type": "status_update", "status": "queued"})
    await redis_client.publish(f"logs:{project_id}", "status_update")
    deployhub_deployments_total.labels(action="deploy").inc()
    log_event("deployment_queued", project_id=project_id, action="deploy")

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


@app.get("/api/projects/{project_id}/resources")
async def get_project_resources(project_id: str) -> dict:
    project = await get_project_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if settings.deployment_mode != "k8s":
        raise HTTPException(status_code=400, detail="Resource metrics are only available in k8s mode")
    pod_name = project.get("container_name")
    if not pod_name:
        raise HTTPException(status_code=404, detail="No deployed pod for this project")
    return await get_namespace_resources(pod_name)


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
    
    # Distributed lock to prevent rapid-fire duplicate API requests
    lock_key = f"lock:queue:{project_id}"
    acquired = await redis_client.set(lock_key, "1", nx=True, ex=5)
    if not acquired:
        raise HTTPException(status_code=429, detail="Deployment already queued recently")

    # Check if already queued or building
    if project.get("status") in ("queued", "building") and action != "stop" and action != "delete":
        raise HTTPException(status_code=409, detail=f"Project is already {project.get('status')}")

    await update_project(project_id, {"status": "queued", "last_error": None})
    await redis_client.rpush("deployhub_queue", json.dumps({"project_id": project_id, "action": action}))
    
    deployhub_deployments_total.labels(action=action).inc()
    log_event("deployment_queued", project_id=project_id, action=action)
    # Notify WebSocket subscribers
    await ws_manager.broadcast(project_id, {"type": "status_update", "status": "queued"})
    # Notify Redis Pub/Sub so clients listening to SSE immediately see the state change
    await redis_client.publish(f"logs:{project_id}", "status_update")
    return ProjectActionResponse(message=f"{action.title()} queued", project_id=project_id, status="queued")


@app.post("/api/deploy/{project_id}", response_model=ProjectActionResponse)
@limiter.limit("10/minute")
async def deploy_project_endpoint(request: Request, project_id: str) -> ProjectActionResponse:
    return await queue_deployment(project_id, action="deploy")


@app.post("/api/redeploy/{project_id}", response_model=ProjectActionResponse)
@limiter.limit("10/minute")
async def redeploy_project_endpoint(request: Request, project_id: str, magic: bool = False) -> ProjectActionResponse:
    action = "redeploy_magic" if magic else "redeploy"
    return await queue_deployment(project_id, action=action)


@app.post("/api/projects/{project_id}/rollback", response_model=ProjectActionResponse)
async def rollback_project(project_id: str) -> ProjectActionResponse:
    """Re-deploy the last known-good image without rebuilding."""
    project = await get_project_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not project.get("last_good_image"):
        raise HTTPException(status_code=409, detail="No previous successful deploy found.")
    if project.get("status") == "building":
        raise HTTPException(status_code=409, detail="Build in progress — wait before rolling back.")
    
    await update_project(project_id, {"status": "queued"})
    await redis_client.rpush("deployhub_queue", json.dumps({"project_id": project_id, "action": "rollback"}))
    await redis_client.publish(f"logs:{project_id}", "status_update")
    log_event("rollback_queued", project_id=project_id)
    return ProjectActionResponse(message="Rollback queued", project_id=project_id, status="queued")


@app.post("/api/webhooks/github/{project_id}")
@limiter.limit("10/minute")
async def github_webhook(request: Request, project_id: str) -> dict:
    github_event = request.headers.get("X-GitHub-Event")
    if github_event == "ping":
        return {"message": "pong"}
    if github_event != "push":
        return {"message": f"Ignoring GitHub event: {github_event}"}
    project = await get_project_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    body = await request.body()
    project_secret = project.get("webhook_secret")
    if project_secret:
        verify_project_webhook_signature(
            body, request.headers.get("X-Hub-Signature-256", ""), project_secret
        )
    elif settings.github_webhook_secret:
        signature_header = request.headers.get("X-Hub-Signature-256", "")
        import hashlib
        import hmac

        expected = "sha256=" + hmac.new(
            settings.github_webhook_secret.encode(), body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature_header, expected):
            log_event("webhook_sig_invalid", project_id=project_id)
            raise HTTPException(status_code=403, detail="Invalid webhook signature")
    await queue_deployment(project_id, action="redeploy")
    log_event("webhook_received", project_id=project_id, event=github_event)
    return {"message": "Redeployment queued via GitHub webhook"}


@app.post("/api/projects/{project_id}/webhook-secret")
async def set_webhook_secret(project_id: str) -> dict:
    """Generate and store a new per-project webhook secret. Returns plaintext once."""
    project = await get_project_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    new_secret = generate_webhook_secret()
    await update_project(project_id, {
        "webhook_secret": new_secret,
        "webhook_secret_hash": hash_webhook_secret(new_secret),
    })
    log_event("webhook_secret_rotated", project_id=project_id)
    return {"secret": new_secret, "note": "Save this — it will not be shown again."}


@app.post("/api/stop/{project_id}", response_model=ProjectActionResponse)
async def stop_project_endpoint(project_id: str) -> ProjectActionResponse:
    project = await get_project_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.get("status") == "building":
        raise HTTPException(status_code=409, detail="Project is currently building and cannot be stopped")
    
    await redis_client.rpush("deployhub_queue", json.dumps({"project_id": project_id, "action": "stop"}))
    log_event("project_stop_queued", project_id=project_id)
    await ws_manager.broadcast(project_id, {"type": "status_update", "status": "stopping"})
    await redis_client.publish(f"logs:{project_id}", "status_update")
    return ProjectActionResponse(message="Stop queued", project_id=project_id, status="stopping")


@app.delete("/api/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project_endpoint(project_id: str) -> Response:
    project = await get_project_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.get("status") == "building":
        raise HTTPException(status_code=409, detail="Project is currently building and cannot be deleted")
    await update_project(project_id, {"status": "deleting"})
    
    # Enqueue deletion logic to the builder worker
    await redis_client.rpush("deployhub_queue", json.dumps({"project_id": project_id, "action": "delete"}))
    await redis_client.publish(f"logs:{project_id}", "status_update")
    
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
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(f"logs:{project_id}")
        
        # Send initial state
        current = await get_project_by_id(project_id)
        if current:
            payload = {
                "project_id": project_id,
                "status": current.get("status"),
                "last_error": current.get("last_error"),
                "updated_at": current.get("updated_at").isoformat() if current.get("updated_at") else None,
                "build_logs": current.get("build_logs", []),
                "runtime_logs": await get_runtime_logs(current),
            }
            yield f"data: {json.dumps(payload)}\n\n"

        # Wait for pubsub events
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            
            # Message received means something updated in the db
            current = await get_project_by_id(project_id)
            if not current:
                yield "data: {\"event\": \"deleted\"}\n\n"
                return

            payload = {
                "project_id": project_id,
                "status": current.get("status"),
                "last_error": current.get("last_error"),
                "updated_at": current.get("updated_at").isoformat() if current.get("updated_at") else None,
                "build_logs": current.get("build_logs", []),
                "runtime_logs": await get_runtime_logs(current),
            }
            yield f"data: {json.dumps(payload)}\n\n"
            
            proj_status = payload.get("status")
            if proj_status in {"failed", "stopped", "deleting", "running"}:
                break

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


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


# ── System & Metrics endpoints moved to routers/system.py ────────────────────


@app.get("/api/projects/{project_id}/health")
async def get_project_health_endpoint(project_id: str) -> dict:
    project = await get_project_by_id(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if settings.deployment_mode != "k8s":
        raise HTTPException(status_code=400, detail="Health endpoint only available in k8s mode")
    container_name = project.get("container_name")
    if not container_name or project.get("status") not in ("running", "failed", "building"):
        return {"project_id": project_id, "status": project.get("status"), "pod": None}
    pod = await get_pod_status(container_name)
    repo_url = project.get("repo_url", "")
    project_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "") if repo_url else container_name
    deployhub_pod_restarts_total.labels(pod_name=container_name, project_name=project_name).set(pod["restart_count"])
    return {
        "project_id": project_id,
        "status": project.get("status"),
        "service_url": project.get("service_url"),
        "pod": {
            "name": container_name,
            "phase": pod["phase"],
            "ready": pod["ready"],
            "restart_count": pod["restart_count"],
            "cpu": pod["cpu"],
            "memory": pod["memory"],
            "events": pod["events"],
        },
    }


# ── Stats endpoint moved to routers/system.py ───────────────────────────────
