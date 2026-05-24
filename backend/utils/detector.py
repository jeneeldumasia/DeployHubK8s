import json
from pathlib import Path

from models import ProjectType


def detect_project_type(repo_path: Path) -> tuple[ProjectType, dict]:
    package_json   = repo_path / "package.json"
    requirements   = repo_path / "requirements.txt"
    pyproject_toml = repo_path / "pyproject.toml"
    main_py        = repo_path / "main.py"
    app_py         = repo_path / "app.py"
    dockerfile     = repo_path / "Dockerfile"
    package_lock   = repo_path / "package-lock.json"
    yarn_lock      = repo_path / "yarn.lock"
    pnpm_lock      = repo_path / "pnpm-lock.yaml"
    go_mod         = repo_path / "go.mod"
    cargo_toml     = repo_path / "Cargo.toml"
    pom_xml        = repo_path / "pom.xml"
    build_gradle   = repo_path / "build.gradle"
    gemfile        = repo_path / "Gemfile"
    composer_json  = repo_path / "composer.json"

    static_candidates = [
        repo_path / "index.html",
        repo_path / "dist" / "index.html",
        repo_path / "build" / "index.html",
        repo_path / "public" / "index.html",
    ]

    metadata: dict = {
        "has_dockerfile":      dockerfile.exists(),
        "has_package_json":    package_json.exists(),
        "has_requirements_txt": requirements.exists(),
        "has_pyproject_toml":  pyproject_toml.exists(),
        "has_package_lock":    package_lock.exists(),
        "has_yarn_lock":       yarn_lock.exists(),
        "has_pnpm_lock":       pnpm_lock.exists(),
        "has_go_mod":          go_mod.exists(),
        "has_cargo_toml":      cargo_toml.exists(),
        "has_pom_xml":         pom_xml.exists(),
        "has_build_gradle":    build_gradle.exists(),
        "has_gemfile":         gemfile.exists(),
        "has_composer_json":   composer_json.exists(),
    }

    # ── New framework types (checked before Node/Python to win on ambiguity) ──
    if go_mod.exists():
        return "go", metadata

    if cargo_toml.exists():
        return "rust", metadata

    if pom_xml.exists():
        metadata["java_build"] = "maven"
        return "java", metadata

    if build_gradle.exists():
        metadata["java_build"] = "gradle"
        return "java", metadata

    if gemfile.exists():
        metadata["ruby_rails"] = (repo_path / "config" / "application.rb").exists()
        return "ruby", metadata

    if composer_json.exists():
        return "php", metadata

    # ── Node.js ───────────────────────────────────────────────────────────────
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
            (repo_path / "packages").exists()
            or (repo_path / "apps").exists()
            or "workspaces" in package_data
        )
        return "node", metadata

    # ── Node.js — no package.json but has common server entry files ───────────
    node_entry_files = ["index.js", "server.js", "app.js", "index.ts", "server.ts", "app.ts"]
    if any((repo_path / f).exists() for f in node_entry_files):
        for parent in [repo_path.parent, repo_path.parent.parent]:
            parent_pkg = parent / "package.json"
            if parent_pkg.exists():
                try:
                    package_data = json.loads(parent_pkg.read_text(encoding="utf-8"))
                    scripts = package_data.get("scripts", {})
                    metadata["node_scripts"] = scripts
                    metadata["has_package_json"] = True
                    metadata["has_package_lock"] = (parent / "package-lock.json").exists()
                    metadata["has_yarn_lock"] = (parent / "yarn.lock").exists()
                    return "node", metadata
                except (OSError, json.JSONDecodeError):
                    pass
        metadata["node_scripts"] = {"start": "node index.js"}
        metadata["has_package_json"] = False
        return "node", metadata

    # ── Python ────────────────────────────────────────────────────────────────
    if requirements.exists() or pyproject_toml.exists() or main_py.exists() or app_py.exists():
        metadata["python_entrypoint"] = detect_python_entrypoint(repo_path, main_py, app_py)
        return "python", metadata

    # ── Static ────────────────────────────────────────────────────────────────
    for static_path in static_candidates:
        if static_path.exists():
            metadata["static_root"] = (
                "."
                if static_path.parent == repo_path
                else str(static_path.parent.relative_to(repo_path))
            )
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
