import asyncio
import base64
import json
import os
import shutil
import subprocess
import tempfile
from functools import partial
from typing import Callable, Coroutine, Dict, Optional

import boto3
from botocore.exceptions import ClientError
from config import settings


def _ensure_ecr_repository(image_tag: str, region: str) -> Optional[str]:
    """
    Best-effort check that the ECR repository exists.

    With the flat repo layout (deployhub-apps:<project_id>) the repo is
    pre-created by the CI pipeline, so this is mostly a safety net.

    Returns None on success/skip, or a warning string if the check could not
    be completed due to IAM restrictions. Never raises — a failure here must
    not abort the build.
    """
    try:
        repo_with_tag = image_tag.split(".amazonaws.com/", 1)[1]
        repo_name = repo_with_tag.rsplit(":", 1)[0]
    except (IndexError, ValueError):
        return None  # not an ECR image

    ecr = boto3.client("ecr", region_name=region)

    try:
        ecr.describe_repositories(repositoryNames=[repo_name])
        return None  # repo exists, all good
    except ClientError as exc:
        code = exc.response["Error"]["Code"]

        if code == "RepositoryNotFoundException":
            # Repo doesn't exist — try to create it
            try:
                ecr.create_repository(
                    repositoryName=repo_name,
                    imageTagMutability="MUTABLE",
                    imageScanningConfiguration={"scanOnPush": False},
                )
                return None  # created successfully
            except ClientError as create_exc:
                create_code = create_exc.response["Error"]["Code"]
                if create_code in ("AccessDeniedException", "AccessDenied", "UnauthorizedOperation"):
                    return (
                        f"⚠️  ECR repo '{repo_name}' not found and cannot be auto-created "
                        f"(IAM restriction: {create_code}). "
                        f"Ensure the repo is pre-created by the CI pipeline before deploying."
                    )
                raise

        elif code in ("AccessDeniedException", "AccessDenied", "UnauthorizedOperation"):
            # Can't describe — proceed optimistically, repo likely exists
            return (
                f"⚠️  Cannot verify ECR repo '{repo_name}' (IAM restriction: {code}). "
                f"Proceeding with push — will fail if repo does not exist."
            )

        raise  # unexpected error


async def build_image(
    image_tag: str,
    dockerfile_path: str,
    context_path: str,
    on_line: Optional[Callable[[str], Coroutine]] = None,
    timeout_seconds: int | None = None,
) -> Dict[str, str]:
    """
    Builds a docker image using buildctl as an asyncio subprocess.
    """
    import signal
    timeout = timeout_seconds or settings.buildkit_timeout_seconds
    dockerfile_dir = os.path.dirname(dockerfile_path) or context_path
    dockerfile_name = os.path.basename(dockerfile_path)

    output_opts = f"type=image,name={image_tag},push=true"
    if settings.registry_insecure:
        output_opts += ",registry.insecure=true"

    cmd = [
        "buildctl", "build",
        "--frontend", "dockerfile.v0",
        "--local", f"context={context_path}",
        "--local", f"dockerfile={dockerfile_dir}",
        "--opt", f"filename={dockerfile_name}",
        "--output", output_opts,
    ]

    env = os.environ.copy()
    env["BUILDKIT_HOST"] = env.get("BUILDKIT_HOST", settings.buildkit_addr)

    docker_config_dir = None
    if ".dkr.ecr." in image_tag:
        try:
            parts = image_tag.split(".")
            region = parts[3] if len(parts) > 3 else settings.aws_region
            repo_warning = _ensure_ecr_repository(image_tag, region)
            if repo_warning:
                print(repo_warning, flush=True)

            ecr = boto3.client("ecr", region_name=region)
            auth_data = ecr.get_authorization_token()["authorizationData"][0]
            token = base64.b64decode(auth_data["authorizationToken"]).decode()
            username, password = token.split(":")
            docker_config_dir = tempfile.mkdtemp()
            config = {"auths": {auth_data["proxyEndpoint"]: {"auth": base64.b64encode(f"{username}:{password}".encode()).decode()}}}
            with open(os.path.join(docker_config_dir, "config.json"), "w") as f:
                json.dump(config, f)
            env["DOCKER_CONFIG"] = docker_config_dir
        except Exception as exc:
            if docker_config_dir: shutil.rmtree(docker_config_dir, ignore_errors=True)
            return {"status": "error", "image": image_tag, "logs": f"ECR auth failed: {exc}"}

    logs = []
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            preexec_fn=os.setsid
        )

        async def read_stream():
            while True:
                line = await proc.stdout.readline()
                if not line: break
                decoded = line.decode(errors='replace')
                logs.append(decoded)
                if on_line: await on_line(decoded)

        try:
            await asyncio.wait_for(read_stream(), timeout=timeout)
            await proc.wait()
        except asyncio.TimeoutError:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                await asyncio.sleep(1)
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                pass
            return {"status": "error", "image": image_tag, "logs": f"Timed out after {timeout}s"}

        if proc.returncode != 0:
            return {"status": "error", "image": image_tag, "logs": "".join(logs)}
        return {"status": "success", "image": image_tag, "logs": "".join(logs)}
    finally:
        if docker_config_dir and os.path.exists(docker_config_dir):
            shutil.rmtree(docker_config_dir, ignore_errors=True)
