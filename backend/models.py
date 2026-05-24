from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl


ProjectStatus = Literal["created", "queued", "building", "running", "stopped", "failed", "deleting"]
ProjectType = Literal["node", "python", "static", "go", "rust", "java", "ruby", "php", "unknown"]


class DeploymentRecord(BaseModel):
    """Single entry in a project's deployment history."""
    timestamp: datetime
    action: str
    status: Literal["success", "failed", "rolled_back"]
    image_tag: str | None = None
    duration_seconds: float | None = None
    error: str | None = None


class ProjectCreate(BaseModel):
    repo_url: HttpUrl
    context_path: str = ""
    service_name: str | None = None
    env_vars: dict[str, str] = Field(default_factory=dict)
    webhook_secret: str | None = None   # per-project HMAC secret for GitHub webhooks


class ApiErrorResponse(BaseModel):
    detail: str


class ProjectRecord(BaseModel):
    id: str = Field(alias="_id")
    repo_url: str
    normalized_repo_url: str
    context_path: str = ""
    service_name: str | None = None
    status: ProjectStatus = "created"
    project_type: ProjectType = "unknown"
    repo_path: str | None = None
    dockerfile_path: str | None = None
    image_tag: str | None = None
    previous_image_tag: str | None = None
    container_id: str | None = None
    container_name: str | None = None
    assigned_port: int | None = None
    service_url: str | None = None
    build_logs: list[str] = Field(default_factory=list)
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime
    last_deployed_at: datetime | None = None
    env_vars: dict[str, str] = Field(default_factory=dict)
    deployment_history: list[DeploymentRecord] = Field(default_factory=list)
    webhook_secret: str | None = None         # per-project HMAC secret (server-side only)
    webhook_secret_hash: str | None = None    # SHA-256 hash of per-project webhook secret
    last_good_image: str | None = None        # ECR image URI of last successful deploy (for rollback)
    health_path: str | None = None
    container_port: int | None = None


class ProjectSummary(BaseModel):
    id: str
    repo_url: str
    context_path: str
    service_name: str | None
    status: ProjectStatus
    project_type: ProjectType
    assigned_port: int | None
    service_url: str | None
    last_error: str | None
    container_id: str | None
    image_tag: str | None
    previous_image_tag: str | None = None
    updated_at: datetime
    created_at: datetime
    last_deployed_at: datetime | None
    env_vars: dict[str, str] = Field(default_factory=dict)
    last_good_image: str | None = None
    has_webhook_secret: bool = False   # True if webhook_secret_hash is set


class ProjectDetail(ProjectSummary):
    normalized_repo_url: str
    repo_path: str | None
    dockerfile_path: str | None
    container_name: str | None
    deployment_history: list[DeploymentRecord] = Field(default_factory=list)


class ProjectActionResponse(BaseModel):
    message: str
    project_id: str
    status: ProjectStatus


class LogsResponse(BaseModel):
    project_id: str
    status: ProjectStatus
    last_error: str | None = None
    updated_at: datetime | None = None
    build_logs: list[str]
    runtime_logs: list[str]


class SystemResponse(BaseModel):
    backend_version: str
    docker_available: bool
    mongodb_available: bool
    project_count: int
    running_container_count: int
    active_deployments: int
    queued_deployments: int
    queue_depth: int = 0
    max_concurrent_builds: int = 3


class HealthResponse(BaseModel):
    status: str
    details: dict[str, Any] = Field(default_factory=dict)
