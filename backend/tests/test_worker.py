"""
Tests for the deployment worker and framework detector.
"""
import ast
import json
import sys
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Make sure the backend package root is on sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Detector tests ────────────────────────────────────────────────────────────

def _make_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    """Write a dict of {relative_path: content} into tmp_path."""
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp_path


def test_detect_node_via_package_json(tmp_path):
    from utils.detector import detect_project_type

    _make_repo(tmp_path, {
        "package.json": json.dumps({"name": "my-app", "scripts": {"start": "node index.js"}}),
    })
    project_type, metadata = detect_project_type(tmp_path)
    assert project_type == "node"
    assert metadata["has_package_json"] is True
    assert "start" in metadata["node_scripts"]


def test_detect_python_via_requirements(tmp_path):
    from utils.detector import detect_project_type

    _make_repo(tmp_path, {"requirements.txt": "fastapi==0.115.0\nuvicorn\n"})
    project_type, metadata = detect_project_type(tmp_path)
    assert project_type == "python"
    assert metadata["has_requirements_txt"] is True


def test_detect_static_via_index_html(tmp_path):
    from utils.detector import detect_project_type

    _make_repo(tmp_path, {"index.html": "<html><body>hello</body></html>"})
    project_type, _ = detect_project_type(tmp_path)
    assert project_type == "static"


def test_detect_unknown_empty_dir(tmp_path):
    from utils.detector import detect_project_type

    project_type, _ = detect_project_type(tmp_path)
    assert project_type == "unknown"


# ── AST check: no bare except in worker.py ───────────────────────────────────

def test_no_bare_except_in_worker():
    """
    Bare `except:` clauses swallow KeyboardInterrupt and SystemExit.
    This AST walk ensures none exist in worker.py.
    """
    worker_path = Path(__file__).parent.parent / "worker.py"
    tree = ast.parse(worker_path.read_text(encoding="utf-8"))

    bare_excepts = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ExceptHandler) and node.type is None
    ]
    assert bare_excepts == [], (
        f"Found {len(bare_excepts)} bare except clause(s) in worker.py at lines: "
        + ", ".join(str(e.lineno) for e in bare_excepts)
    )


# ── Worker deploy() calls create_namespaced_pod ───────────────────────────────

@pytest.mark.asyncio
async def test_deploy_calls_create_pod(tmp_path):
    """
    Smoke-test that deploy() in k8s mode calls create_pod (which wraps
    create_namespaced_pod). We mock all I/O so no real cluster is needed.
    """
    from worker import DeploymentWorker

    worker = DeploymentWorker(
        public_base_url="http://1.2.3.4",
        generated_dockerfile_root=str(tmp_path / "dockerfiles"),
        deployment_mode="k8s",
    )

    fake_project = {
        "_id": "abc12345",
        "repo_url": "https://github.com/test/repo",
        "normalized_repo_url": "https://github.com/test/repo",
        "context_path": "",
        "service_name": "test",
        "project_type": "node",
        "image_tag": None,
        "previous_image_tag": None,
        "container_name": None,
        "container_id": None,
        "assigned_port": None,
        "service_url": None,
        "env_vars": {},
        "status": "queued",
        "build_logs": [],
        "last_error": None,
        "deployment_history": [],
    }

    # Build a minimal repo so the detector finds something
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "package.json").write_text(
        json.dumps({"scripts": {"start": "node index.js"}}), encoding="utf-8"
    )
    (repo_dir / "index.js").write_text("console.log('hi')", encoding="utf-8")
    (repo_dir / "package-lock.json").write_text("{}", encoding="utf-8")

    with (
        patch("worker.get_project_by_id", new=AsyncMock(return_value=fake_project)),
        patch("worker.update_project", new=AsyncMock()),
        patch("worker.append_build_log", new=AsyncMock()),
        patch("worker.append_deployment_history", new=AsyncMock()),
        patch("worker.clone_or_update_repo", new=AsyncMock(return_value=repo_dir)),
        patch("worker.get_occupied_node_ports", new=AsyncMock(return_value=[])),
        patch("worker.create_ingress", new=AsyncMock(return_value={"status": "success"})),
        patch("worker.delete_pod", new=AsyncMock()),
        patch("worker.delete_ingress", new=AsyncMock()),
        patch("worker.wait_for_pod_running", new=AsyncMock(return_value={"status": "running"})),
        patch("utils.buildkit.build_image", new=AsyncMock(return_value={"status": "success", "logs": ""})),
        patch("worker.create_pod", new=AsyncMock(return_value={"status": "success"})) as mock_create_pod,
    ):
        # Patch settings so ecr_registry is set
        import config
        config.settings.ecr_registry = "123456789.dkr.ecr.us-east-1.amazonaws.com"
        config.settings.port_range_start = 3100
        config.settings.port_range_end = 3999

        # Patch health check to pass immediately
        worker._health_check_pod = AsyncMock()

        await worker.deploy("abc12345", action="deploy")

        mock_create_pod.assert_called_once()
        call_kwargs = mock_create_pod.call_args
        assert call_kwargs is not None, "create_pod was never called"
