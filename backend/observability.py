import json
import logging
import time
from typing import Any

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

logger = logging.getLogger("deployhub")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
logger.setLevel(logging.INFO)
logger.propagate = False

deployhub_projects_total = Gauge("deployhub_projects_total", "Total projects stored in MongoDB")
deployhub_deployments_total = Counter("deployhub_deployments_total", "Total deployment requests", ["action"])
deployhub_deployment_failures_total = Counter(
    "deployhub_deployment_failures_total", "Total failed deployments", ["phase"]
)
deployhub_active_containers = Gauge("deployhub_active_containers", "Running DeployHub-managed containers")
deployhub_deployment_duration_seconds = Histogram(
    "deployhub_deployment_duration_seconds", "Deployment duration in seconds", ["action"]
)
http_requests_total = Counter("http_requests_total", "HTTP requests handled", ["method", "path", "status_code"])
http_request_duration_seconds = Histogram(
    "http_request_duration_seconds", "HTTP request duration in seconds", ["method", "path"]
)

# Health check & rollback metrics
deployhub_health_check_failures_total = Counter(
    "deployhub_health_check_failures_total",
    "Post-deployment health check failures that triggered rollback",
    ["reason"],
)
deployhub_pod_restarts_total = Gauge(
    "deployhub_pod_restarts_total",
    "Total container restart count for a deployed pod",
    ["pod_name"],
)
deployhub_deployment_success_total = Counter(
    "deployhub_deployment_success_total",
    "Total successful deployments (passed health check)",
    ["action"],
)


def log_event(event: str, **fields: Any) -> None:
    payload = {"event": event, **fields}
    logger.info(json.dumps(payload, default=str))


async def metrics_response() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST


class RequestTimer:
    def __init__(self, method: str, path: str) -> None:
        self.method = method
        self.path = path
        self.start = time.perf_counter()

    def observe(self, status_code: int) -> None:
        elapsed = time.perf_counter() - self.start
        http_requests_total.labels(method=self.method, path=self.path, status_code=str(status_code)).inc()
        http_request_duration_seconds.labels(method=self.method, path=self.path).observe(elapsed)
