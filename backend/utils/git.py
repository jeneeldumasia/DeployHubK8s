import asyncio
import shutil
from pathlib import Path
from urllib.parse import urlparse

from config import settings


class GitError(Exception):
    pass


def normalize_repo_url(repo_url: str) -> str:
    parsed = urlparse(repo_url)
    host = parsed.netloc.lower()
    if host not in settings.allowed_repo_host_list:
        raise GitError(f"Unsupported git host '{host}'. Allowed hosts: {', '.join(settings.allowed_repo_host_list)}")

    if not parsed.path or parsed.path == "/":
        raise GitError("Repository URL is missing an owner/repository path")

    normalized_path = parsed.path.rstrip("/")
    if normalized_path.endswith(".git"):
        normalized_path = normalized_path[:-4]

    return f"https://{host}{normalized_path}.git"


def project_repo_path(project_id: str) -> Path:
    return Path(settings.repo_root) / project_id


async def _run_git_command(args: list[str], cwd: Path | None = None) -> tuple[int, str]:
    process = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await process.communicate()
    output = stdout.decode("utf-8", errors="replace")
    return process.returncode, output


async def clone_or_update_repo(project_id: str, normalized_repo_url: str) -> Path:
    target = project_repo_path(project_id)
    target.parent.mkdir(parents=True, exist_ok=True)

    if (target / ".git").exists():
        returncode, remote_output = await _run_git_command(["git", "-C", str(target), "remote", "get-url", "origin"])
        if returncode != 0:
            shutil.rmtree(target, ignore_errors=True)
        else:
            existing_remote = remote_output.strip()
            if existing_remote == normalized_repo_url:
                fetch_code, fetch_output = await _run_git_command(
                    ["git", "-C", str(target), "pull", "--ff-only"],
                )
                if fetch_code != 0:
                    raise GitError(fetch_output.strip() or "git pull failed")
                return target
            shutil.rmtree(target, ignore_errors=True)

    clone_code, clone_output = await _run_git_command(
        ["git", "clone", "--depth", "1", normalized_repo_url, str(target)],
    )
    if clone_code != 0:
        raise GitError(clone_output.strip() or "git clone failed")

    return target
