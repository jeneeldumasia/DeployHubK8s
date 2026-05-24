"""Parse optional deployhub.yml at the repository root."""

from pathlib import Path
from typing import Any

import yaml

# Secrets must not be placed in deployhub.yml — use the DeployHub UI or API instead.
_DEPLOYHUB_CONFIG_COMMENT = (
    "# deployhub.yml — runtime overrides only. Do NOT put secrets in this file."
)


def load_deployhub_config(repo_path: Path) -> dict[str, Any]:
    config_path = repo_path / "deployhub.yml"
    if not config_path.exists():
        return {}
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def apply_deployhub_config(project_updates: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Merge deployhub.yml values into project fields used by the worker."""
    if not config:
        return project_updates
    if port := config.get("port"):
        project_updates["container_port"] = int(port)
    if health_path := config.get("healthPath"):
        project_updates["health_path"] = str(health_path)
    if build_context := config.get("buildContext"):
        project_updates["context_path"] = str(build_context).strip("./")
    if install_command := config.get("installCommand"):
        project_updates["install_command"] = str(install_command)
    if build_command := config.get("buildCommand"):
        project_updates["build_command"] = str(build_command)
    if start_command := config.get("startCommand"):
        project_updates["start_command"] = str(start_command)
    if env := config.get("env"):
        if isinstance(env, dict):
            merged = dict(project_updates.get("env_vars") or {})
            merged.update({str(k): str(v) for k, v in env.items()})
            project_updates["env_vars"] = merged
    return project_updates
