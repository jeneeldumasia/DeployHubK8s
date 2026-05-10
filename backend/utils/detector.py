import json
from pathlib import Path

from models import ProjectType


def detect_project_type(repo_path: Path) -> tuple[ProjectType, dict]:
    package_json = repo_path / "package.json"
    requirements = repo_path / "requirements.txt"
    pyproject_toml = repo_path / "pyproject.toml"
    main_py = repo_path / "main.py"
    app_py = repo_path / "app.py"
    dockerfile = repo_path / "Dockerfile"
    package_lock = repo_path / "package-lock.json"
    yarn_lock = repo_path / "yarn.lock"
    pnpm_lock = repo_path / "pnpm-lock.yaml"

    static_candidates = [repo_path / "index.html", repo_path / "dist" / "index.html", repo_path / "build" / "index.html"]

    metadata: dict = {
        "has_dockerfile": dockerfile.exists(),
        "has_package_json": package_json.exists(),
        "has_requirements_txt": requirements.exists(),
        "has_pyproject_toml": pyproject_toml.exists(),
        "has_package_lock": package_lock.exists(),
        "has_yarn_lock": yarn_lock.exists(),
        "has_pnpm_lock": pnpm_lock.exists(),
    }

    if package_json.exists():
        scripts = {}
        package_data = {}
        try:
            package_data = json.loads(package_json.read_text(encoding="utf-8"))
            scripts = package_data.get("scripts", {})
        except (OSError, json.JSONDecodeError):
            scripts = {}
            package_data = {}
        metadata["node_scripts"] = scripts
        metadata["is_monorepo"] = (
            (repo_path / "packages").exists() or (repo_path / "apps").exists() or "workspaces" in package_data
        )
        return "node", metadata

    if requirements.exists() or pyproject_toml.exists() or main_py.exists() or app_py.exists():
        metadata["python_entrypoint"] = detect_python_entrypoint(repo_path, main_py, app_py)
        return "python", metadata

    for static_path in static_candidates:
        if static_path.exists():
            metadata["static_root"] = "." if static_path.parent == repo_path else str(static_path.parent.relative_to(repo_path))
            return "static", metadata

    return "unknown", metadata


def detect_python_entrypoint(repo_path: Path, main_py: Path, app_py: Path) -> str | None:
    if main_py.exists():
        main_contents = main_py.read_text(encoding="utf-8", errors="replace")
        if "FastAPI(" in main_contents and "app =" in main_contents:
            return "uvicorn"
        if "Flask(" in main_contents and "app =" in main_contents:
            return "main_py"
        return "main_py"

    if app_py.exists():
        app_contents = app_py.read_text(encoding="utf-8", errors="replace")
        if "FastAPI(" in app_contents and "app =" in app_contents:
            return "app_uvicorn"
        if "Flask(" in app_contents and "app =" in app_contents:
            return "app_py"
        return "app_py"

    if (repo_path / "pyproject.toml").exists():
        return None

    return None
