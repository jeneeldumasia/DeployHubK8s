"""
API integration tests using FastAPI TestClient.
MongoDB and k8s are mocked — no real infrastructure needed.
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

# ── Patch heavy I/O before importing main ────────────────────────────────────
# motor / kubernetes clients are not available in CI without a real cluster.

_mock_db_module = MagicMock()
_mock_db_module.connect_to_mongo = AsyncMock()
_mock_db_module.close_mongo_connection = AsyncMock()
_mock_db_module.count_projects = AsyncMock(return_value=0)
_mock_db_module.count_projects_by_status = AsyncMock(return_value=0)
_mock_db_module.list_projects = AsyncMock(return_value=[])
_mock_db_module.get_project_by_id = AsyncMock(return_value=None)
_mock_db_module.get_project_by_url_and_path = AsyncMock(return_value=None)
_mock_db_module.get_project_by_normalized_repo_url = AsyncMock(return_value=None)
_mock_db_module.create_project = AsyncMock(return_value="abc12345")
_mock_db_module.update_project = AsyncMock()
_mock_db_module.delete_project = AsyncMock(return_value=True)
_mock_db_module.append_build_log = AsyncMock()
_mock_db_module.append_deployment_history = AsyncMock()
_mock_db_module.get_deployment_stats = AsyncMock(return_value={
    "total": 0, "successful": 0, "failed": 0, "rolled_back": 0, "avg_duration_seconds": None
})
_mock_db_module.utc_now = MagicMock(return_value=__import__("datetime").datetime.utcnow())

_mock_db_module.get_database = MagicMock(return_value=MagicMock(
    command=AsyncMock(return_value={"ok": 1})
))

sys.modules["database"] = _mock_db_module

# Patch k8s utils
_mock_k8s = MagicMock()
_mock_k8s.check_k8s_available = AsyncMock(return_value=True)
_mock_k8s.count_running_deployhub_pods = AsyncMock(return_value=0)
_mock_k8s.get_pod_logs = AsyncMock(return_value=[])
_mock_k8s.get_all_pod_restart_counts = AsyncMock(return_value={})
_mock_k8s.get_pod_restart_count = AsyncMock(return_value=0)
sys.modules["utils.k8s"] = _mock_k8s

# Patch docker utils
_mock_docker = MagicMock()
_mock_docker.check_docker_available = AsyncMock(return_value=True)
_mock_docker.count_running_deployhub_containers = AsyncMock(return_value=0)
_mock_docker.get_container_logs = AsyncMock(return_value=[])
sys.modules["utils.docker"] = _mock_docker


# Patch git utils
_mock_git = MagicMock()
_mock_git.normalize_repo_url = MagicMock(side_effect=lambda u: u)
_mock_git.clone_or_update_repo = AsyncMock(return_value=Path("/tmp/repo"))
_mock_git.GitError = Exception
sys.modules["utils.git"] = _mock_git

# Patch worker
_mock_worker_cls = MagicMock()
_mock_worker_instance = MagicMock()
_mock_worker_instance.start = MagicMock()
_mock_worker_instance.stop = AsyncMock()
_mock_worker_instance.active_count = MagicMock(return_value=0)
_mock_worker_instance.queued_count = MagicMock(return_value=0)
_mock_worker_instance.active_project_ids = set()
_mock_worker_instance.enqueue = AsyncMock(return_value=True)
_mock_worker_cls.return_value = _mock_worker_instance
sys.modules["worker"] = MagicMock(DeploymentWorker=_mock_worker_cls)

from main import app  # noqa: E402 — must come after mocks

client = TestClient(app, raise_server_exceptions=False)


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_health_returns_200():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_ready_does_not_crash():
    """
    /ready may return 200 (healthy) or 503 (dependency unavailable).
    Either is acceptable — we just verify it doesn't 500.
    """
    resp = client.get("/ready")
    assert resp.status_code in (200, 503)


def test_list_projects_returns_list():
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_create_project_missing_body_returns_422():
    resp = client.post("/api/projects", json={})
    assert resp.status_code == 422


def test_webhook_nonexistent_project_returns_404():
    """
    Posting to a webhook for a project that doesn't exist should 404.
    get_project_by_id is mocked to return None.
    """
    resp = client.post(
        "/api/webhooks/github/nonexistent",
        headers={"X-GitHub-Event": "push", "Content-Type": "application/json"},
        content=b"{}",
    )
    assert resp.status_code == 404


def test_stats_endpoint_returns_dict():
    resp = client.get("/api/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "successful" in data
    assert "failed" in data
