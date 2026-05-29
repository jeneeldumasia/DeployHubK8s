import asyncio
import shutil
import os
import aiohttp
from datetime import UTC, datetime
from pathlib import Path

from database import append_build_log, append_deployment_history, get_project_by_id, update_project, utc_now
from observability import (
    deployhub_build_duration_seconds,
    deployhub_deployment_duration_seconds,
    deployhub_deployment_failures_total,
    deployhub_deployment_success_total,
    deployhub_health_check_failures_total,
    deployhub_pod_runtime_seconds,
    log_event,
)
from utils.deployhub_config import apply_deployhub_config, load_deployhub_config
from utils.detector import detect_project_type
from utils.docker import (
    DockerError,
    get_container_logs,
    inspect_exposed_ports,
    is_container_running,
    remove_container,
    remove_image,
    run_container,
    allocate_host_port,
)
from utils.git import GitError, clone_or_update_repo

# Import K8s utilities
from utils.k8s import (
    create_deployment,
    delete_deployment,
    get_occupied_node_ports,
    create_ingress,
    delete_ingress,
    wait_for_deployment_running,
)
from config import settings


def timestamped_log(message: str) -> str:
    return f"[{datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')}] {message}"


class DeploymentWorker:
    def __init__(self, public_base_url: str, generated_dockerfile_root: str, deployment_mode: str = "docker") -> None:
        self.queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()
        self.enqueued_project_ids: set[str] = set()
        self.active_project_ids: set[str] = set()
        self._build_semaphore = asyncio.Semaphore(settings.max_concurrent_builds)
        self.public_base_url = public_base_url.rstrip("/")
        self.generated_dockerfile_root = Path(generated_dockerfile_root)
        self.task: asyncio.Task | None = None
        # mode can be "docker" or "k8s"
        self.deployment_mode = deployment_mode

    def start(self) -> None:
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.run(), name="deployhub-worker")

    async def stop(self) -> None:
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    def queued_count(self) -> int:
        return len(self.enqueued_project_ids)

    def active_count(self) -> int:
        return len(self.active_project_ids)

    async def enqueue(self, project_id: str, action: str = "deploy") -> bool:
        if project_id in self.enqueued_project_ids or project_id in self.active_project_ids:
            return False
        self.enqueued_project_ids.add(project_id)
        await self.queue.put((action, project_id))
        return True

    async def run(self) -> None:
        while True:
            action, project_id = await self.queue.get()
            self.enqueued_project_ids.discard(project_id)
            self.active_project_ids.add(project_id)
            try:
                async with self._build_semaphore:
                    if action == "rollback":
                        await self._do_rollback(project_id)
                    else:
                        await self.deploy(project_id, action=action)
            finally:
                self.active_project_ids.discard(project_id)
                self.queue.task_done()

    async def deploy(self, project_id: str, action: str = "deploy") -> None:
        project = await get_project_by_id(project_id)
        if not project:
            return
        started_at = datetime.now(UTC)

        async def record_log(message: str) -> None:
            if message:
                await append_build_log(project_id, timestamped_log(message))

        image_tag = self.image_tag(project_id)
        container_name = self.container_name(project_id)

        await update_project(
            project_id,
            {
                "status": "building",
                "last_error": None,
                "image_tag": image_tag,
                "container_name": container_name,
                "container_id": None,
                "build_logs": [timestamped_log(f"{action.title()} started")],
            },
        )

        try:
            log_event("deployment_started", project_id=project_id, action=action)
            await record_log("Cloning or updating repository")
            repo_path = await clone_or_update_repo(project_id, project["normalized_repo_url"])
            await update_project(project_id, {"repo_path": str(repo_path)})
            await record_log(f"Repository ready at {repo_path}")

            dh_config = load_deployhub_config(repo_path)
            if dh_config:
                await record_log("Applying deployhub.yml overrides")
                overrides = apply_deployhub_config({}, dh_config)
                persist = {k: v for k, v in overrides.items() if k in ("env_vars", "health_path", "context_path", "install_command", "build_command", "start_command")}
                if persist:
                    await update_project(project_id, persist)
                    project = await get_project_by_id(project_id) or project

            context_path = project.get("context_path") or ""
            build_context = repo_path / context_path

            project_type, metadata = detect_project_type(build_context)
            await update_project(project_id, {"project_type": project_type})
            await record_log(f"Detected project type: {project_type}")

            # 3. Build & Deploy
            dockerfile_path = await self._resolve_dockerfile(
                project_id, build_context, project_type, metadata, project, record_log
            )
            await update_project(project_id, {"dockerfile_path": str(dockerfile_path)})
            if dockerfile_path.name == "Dockerfile":
                await record_log(f"Using repository Dockerfile at {dockerfile_path}")
            else:
                await record_log(f"Using generated Dockerfile at {dockerfile_path}")

            await self.stop_project_resources(project)
            container_port = project.get("container_port") or self._default_container_port(project_type)
            await record_log(f"Using container port {container_port}")

            image_tag = self.image_tag(project_id)
            if self.deployment_mode == "k8s":
                # Use ECR when ecr_registry is configured, otherwise use the
                # local in-cluster registry (registry_addr).
                registry_prefix = settings.ecr_registry.rstrip("/") if settings.ecr_registry else settings.registry_addr.rstrip("/")
                registry_image = self.ecr_image_ref(project_id, registry_prefix)
                await record_log(f"Building Docker image '{registry_image}' via BuildKit for Kubernetes")

                from utils.buildkit import build_image as buildkit_build_image
                try:
                    build_result = await asyncio.wait_for(
                        buildkit_build_image(
                            image_tag=registry_image,
                            dockerfile_path=str(dockerfile_path),
                            context_path=str(build_context),
                            on_line=record_log,
                        ),
                        timeout=settings.buildkit_timeout_seconds,
                    )
                except asyncio.TimeoutError:
                    log_event(
                        "build_timeout",
                        project_id=project_id,
                        timeout=settings.buildkit_timeout_seconds,
                    )
                    await update_project(project_id, {
                        "status": "failed",
                        "last_error": (
                            "Build exceeded time limit. Check for infinite loops "
                            "or very large dependencies."
                        ),
                    })
                    await record_log(
                        f"[ERROR] Build timed out after {settings.buildkit_timeout_seconds}s"
                    )
                    return
                if build_result["logs"]:
                    for line in build_result["logs"].splitlines():
                        await record_log(line)

                if build_result["status"] == "error":
                    raise RuntimeError(f"BuildKit build failed: {build_result.get('logs')}")

                log_event("k8s_build_finished", project_id=project_id, image_tag=registry_image)
 
                # Use cluster-aware port allocation
                occupied_ports = await get_occupied_node_ports()
                preferred_port = project.get("assigned_port")
                
                assigned_port = None
                # Try preferred port first if it's in range and free
                if preferred_port and settings.port_range_start <= preferred_port <= settings.port_range_end:
                    if preferred_port not in occupied_ports:
                        assigned_port = preferred_port
                
                # Otherwise pick the first free one in range
                if not assigned_port:
                    for p in range(settings.port_range_start, settings.port_range_end + 1):
                        if p not in occupied_ports:
                            assigned_port = p
                            break
                
                if not assigned_port:
                    raise RuntimeError("No free NodePorts available in the configured range")

                await record_log(f"Deploying Deployment {container_name} with public NodePort {assigned_port}")
                
                # Extract human readable project name
                repo_url = project.get("repo_url", "")
                project_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "") if repo_url else container_name
                
                # 1. Start the new deployment container
                deployment_result = await create_deployment(
                    name=container_name,
                    image=registry_image,
                    port=container_port,
                    node_port=assigned_port,
                    env_vars=project.get("env_vars", {}),
                    project_name=project_name
                )
                if deployment_result.get("status") == "error":
                    raise RuntimeError(f"K8s deployment creation failed: {deployment_result.get('error')}")

                await record_log("Waiting for deployment to be ready...")
                ready_result = await wait_for_deployment_running(container_name, timeout_seconds=300)
                if ready_result.get("status") == "error":
                    raise RuntimeError(f"Deployment failed to start: {ready_result.get('reason')}")
                
                container_id = container_name

                # In EKS with an ALB, NodePorts are blocked externally.
                # The primary service URL must be the Ingress host URL.
                slug = self._get_slug(project["repo_url"])
                host = f"{slug}.{settings.base_domain}"
                service_url = f"http://{host}"

                # Create Ingress for subdomain (best-effort — don't fail deploy if it errors)
                ingress_result = await create_ingress(name=container_name, host=host, service_port=container_port)
                if ingress_result["status"] == "error":
                    await record_log(f"⚠️ Ingress creation failed (non-fatal): {ingress_result.get('error')}")
                else:
                    await record_log(f"Ingress configured for {service_url} (requires DNS to be set up)")

                # ── Post-deployment health check ──────────────────────────────
                try:
                    await self._health_check_pod(
                        pod_name=container_name,
                        container_port=container_port,
                        record_log=record_log,
                        health_path=project.get("health_path") or "/",
                    )
                except RuntimeError as health_exc:
                    # Rollback: tear down the deployment and ingress we just created
                    await record_log(f"❌ Health check failed — rolling back: {health_exc}")
                    log_event("health_check_failed", project_id=project_id, reason=str(health_exc))
                    await delete_deployment(container_name)
                    await delete_ingress(container_name)
                    raise RuntimeError(f"Post-deployment health check failed: {health_exc}") from health_exc

            else:
                await record_log(f"Building Docker image '{image_tag}' via Docker daemon")
                log_event("docker_build_started", project_id=project_id, image_tag=image_tag)
                from utils.docker import build_image as docker_build_image
                await docker_build_image(image_tag=image_tag, dockerfile_path=dockerfile_path, context_path=repo_path, on_line=record_log)
                log_event("docker_build_finished", project_id=project_id, image_tag=image_tag)

                exposed_ports = await inspect_exposed_ports(image_tag)
                container_port = exposed_ports[0] if exposed_ports else container_port
                
                container_id, assigned_port, run_logs = await run_container(
                    image_tag=image_tag,
                    container_name=container_name,
                    container_port=container_port,
                    preferred_host_port=project.get("assigned_port"),
                    env_vars={
                        "PORT": str(container_port),
                        "HOST": "0.0.0.0",
                        "BIND_ADDRESS": "0.0.0.0",
                        # User-supplied env vars override defaults
                        **project.get("env_vars", {}),
                    },
                )
                for line in run_logs:
                    await record_log(line)

                service_url = f"{self.public_base_url}:{assigned_port}"
                if not await is_container_running(container_id):
                    runtime_logs = await get_container_logs(container_id, tail=100)
                    for line in runtime_logs:
                        await record_log(f"[runtime] {line}")
                    raise DockerError("Container exited immediately after startup")

            await update_project(
                project_id,
                {
                    "status": "running",
                    "assigned_port": assigned_port,
                    "service_url": service_url,
                    "container_id": container_id,
                    "last_deployed_at": utc_now(),
                    # Track previous image for rollback
                    "previous_image_tag": project.get("image_tag"),
                },
            )
            # Save last known-good image for rollback
            if self.deployment_mode == "k8s":
                await update_project(project_id, {"last_good_image": registry_image})
                log_event("last_good_image_saved", project_id=project_id, image=registry_image)
            await record_log(f"App deployed successfully on {service_url}")
            duration = (datetime.now(UTC) - started_at).total_seconds()
            deployhub_deployment_duration_seconds.labels(action=action).observe(duration)
            deployhub_deployment_success_total.labels(action=action).inc()
            # Cost tracking — record runtime start
            deployhub_pod_runtime_seconds.labels(project_id=project_id).inc(0)
            log_event("deployment_success", project_id=project_id, service_url=service_url)
            # Append to deployment history
            await append_deployment_history(project_id, {
                "timestamp": utc_now(),
                "action": action,
                "status": "success",
                "image_tag": image_tag,
                "duration_seconds": round(duration, 1),
                "error": None,
            })

        except Exception as exc:
            await record_log(f"Deployment failed: {exc}")
            duration = (datetime.now(UTC) - started_at).total_seconds()
            deployhub_deployment_failures_total.labels(phase="deploy").inc()
            log_event("deployment_failed", project_id=project_id, error=self._summarize_error(exc), action=action)

            # Record failure in history
            await append_deployment_history(project_id, {
                "timestamp": utc_now(),
                "action": action,
                "status": "failed",
                "image_tag": image_tag,
                "duration_seconds": round(duration, 1),
                "error": self._summarize_error(exc),
            })

            # Attempt rollback on redeploy if a previous working image exists
            previous_image = project.get("image_tag")  # image before this deploy attempt
            if action == "redeploy" and previous_image and self.deployment_mode == "k8s":
                await record_log(f"🔄 Attempting rollback to previous image: {previous_image}")
                try:
                    rollback_port = project.get("assigned_port")
                    repo_url = project.get("repo_url", "")
                    project_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "") if repo_url else container_name
                    if rollback_port:
                        rb_result = await create_deployment(
                            name=container_name,
                            image=previous_image,
                            port=self._default_container_port(project.get("project_type", "unknown")),
                            node_port=rollback_port,
                            env_vars=project.get("env_vars", {}),
                            project_name=project_name
                        )
                        if rb_result["status"] == "success":
                            await update_project(project_id, {
                                "status": "running",
                                "last_error": f"Rolled back: {self._summarize_error(exc)}",
                            })
                            await record_log("✅ Rollback successful — previous version restored")
                            await append_deployment_history(project_id, {
                                "timestamp": utc_now(),
                                "action": "rollback",
                                "status": "success",
                                "image_tag": previous_image,
                                "duration_seconds": None,
                                "error": None,
                            })
                            log_event("deployment_rolled_back", project_id=project_id, image=previous_image)
                            return
                except Exception as rb_exc:
                    await record_log(f"❌ Rollback also failed: {rb_exc}")

            await update_project(project_id, {"status": "failed", "last_error": self._summarize_error(exc)})

    async def stop_project_resources(self, project: dict | None) -> None:
        if not project:
            return

        if self.deployment_mode == "k8s":
            # Derive the canonical name and delete once; ignore if already gone
            canonical_name = self.container_name(str(project["_id"]))
            await delete_deployment(canonical_name)
        else:
            await remove_container(project.get("container_id"))
            await remove_container(project.get("container_name"))
            await remove_container(self.container_name(str(project["_id"])))

    async def stop_project(self, project_id: str) -> dict[str, str]:
        project = await get_project_by_id(project_id)
        if not project:
            raise ValueError("Project not found")
        if project_id in self.active_project_ids:
            raise RuntimeError("Project is currently building and cannot be stopped")

        await self.stop_project_resources(project)
        await append_build_log(project_id, timestamped_log("Project stopped and resources removed"))
        await update_project(
            project_id,
            {
                "status": "stopped",
                "container_id": None,
            },
        )
        return {"message": "Project stopped", "status": "stopped"}

    async def delete_project_resources(self, project: dict) -> None:
        await self.stop_project_resources(project)
        
        if self.deployment_mode == "k8s":
            canonical_name = self.container_name(str(project["_id"]))
            await delete_deployment(canonical_name)
            await delete_ingress(canonical_name)
        elif self.deployment_mode == "docker":
            await remove_image(project.get("image_tag"))

        repo_path = project.get("repo_path")
        if repo_path:
            shutil.rmtree(repo_path, ignore_errors=True)

        dockerfile_path = project.get("dockerfile_path")
        if dockerfile_path:
            dockerfile_dir = Path(dockerfile_path).parent
            repo_path_str = project.get("repo_path") or ""
            if dockerfile_dir.exists() and dockerfile_dir != Path(repo_path_str):
                shutil.rmtree(dockerfile_dir, ignore_errors=True)

    def image_tag(self, project_id: str) -> str:
        return f"deployhub-{project_id}:latest".lower()

    def ecr_image_ref(self, project_id: str, registry_prefix: str) -> str:
        """
        Build the fully-qualified ECR image reference.

        Uses a FLAT repo layout:  <account>.dkr.ecr.<region>.amazonaws.com/deployhub-apps:<project_id>

        registry_prefix may arrive as either:
          - bare registry:   767397755297.dkr.ecr.us-east-1.amazonaws.com
          - with repo path:  767397755297.dkr.ecr.us-east-1.amazonaws.com/deployhub-apps
          - or local:        registry:5000

        We always normalise to the bare registry host so we can append
        /deployhub-apps:<project_id> exactly once.
        """
        if ".dkr.ecr." in registry_prefix:
            # Strip everything after the amazonaws.com host (any /repo/path suffix)
            host = registry_prefix.split(".amazonaws.com")[0] + ".amazonaws.com"
            return f"{host}/deployhub-apps:{project_id}".lower()
        else:
            # Local registry — keep original naming
            return f"{registry_prefix}/{self.image_tag(project_id)}"

    def container_name(self, project_id: str) -> str:
        return f"deployhub-{project_id}".lower()

    def _get_slug(self, repo_url: str) -> str:
        # e.g. https://github.com/jeneeldumasia/me -> me
        slug = repo_url.rstrip("/").split("/")[-1].lower()
        # sanitize (only alphanumeric and hyphens)
        sanitized = "".join(c if c.isalnum() or c == "-" else "-" for c in slug)
        return sanitized.strip("-")

    async def _resolve_dockerfile(self, project_id: str, repo_path: Path, project_type: str, metadata: dict, project: dict, record_log) -> Path:
        existing_dockerfile = repo_path / "Dockerfile"
        if existing_dockerfile.exists():
            return existing_dockerfile

        generated_dir = self.generated_dockerfile_root / project_id
        generated_dir.mkdir(parents=True, exist_ok=True)
        dockerfile_path = generated_dir / "Dockerfile.generated"
        dockerfile_content = await self._generated_dockerfile_contents(project_type, metadata, repo_path, project, record_log)
        dockerfile_path.write_text(dockerfile_content, encoding="utf-8")
        return dockerfile_path

    async def _generated_dockerfile_contents(self, project_type: str, metadata: dict, repo_path: Path, project: dict, record_log) -> str:
        if project_type == "node":
            scripts = metadata.get("node_scripts", {})

            # Resolve install + build commands (package-manager aware)
            if project.get("install_command"):
                install_command = project["install_command"]
                default_build = "npm run build"
            elif metadata.get("has_yarn_lock"):
                install_command = "yarn install --frozen-lockfile"
                default_build = "yarn build"
            elif metadata.get("has_pnpm_lock"):
                install_command = "npm install -g pnpm && pnpm install --frozen-lockfile"
                default_build = "pnpm build"
            elif metadata.get("has_package_lock"):
                install_command = "npm ci"
                default_build = "npm run build"
            else:
                install_command = "npm install"
                default_build = "npm run build"

            has_build_step = bool(project.get("build_command") or "build" in scripts)
            build_command = project.get("build_command") or (default_build if has_build_step else None)

            # Resolve the start command:
            #   user override > explicit start script > built app (serve dist/) > dev server
            if project.get("start_command"):
                command = project["start_command"]
            elif "start" in scripts:
                command = "npm run start"
            elif has_build_step:
                # App produces static dist/ — serve it correctly as a SPA.
                # `serve -s` enables SPA fallback routing; honours $PORT.
                command = "npx serve -s dist -l ${PORT}"
            elif "dev" in scripts:
                # No build output; dev server is the only option.
                command = "npm run dev -- --host 0.0.0.0 --port ${PORT}"
            else:
                # No scripts defined — fall back to direct node execution
                for entry in ["index.js", "server.js", "app.js"]:
                    if (repo_path / entry).exists():
                        command = f"node {entry}"
                        break
                else:
                    raise RuntimeError("No supported Node start command found. Add a Dockerfile or define start/dev scripts.")

            dockerfile_lines = [
                "FROM node:20-alpine",
                "WORKDIR /app",
                "COPY . .",
                f"RUN {install_command}",
            ]
            if build_command:
                dockerfile_lines.append(f"RUN {build_command}")

            dockerfile_lines.extend(
                [
                    "ENV HOST=0.0.0.0",
                    "ENV PORT=3000",
                    "EXPOSE 3000",
                    f'CMD ["sh", "-c", "{command}"]',
                    "",
                ]
            )
            return "\n".join(dockerfile_lines)

        if project_type == "python":
            install_lines = []
            system_packages = []
            
            # Detect common system dependencies
            requirements_content = ""
            if metadata.get("has_requirements_txt"):
                try:
                    req_path = repo_path / "requirements.txt"
                    if req_path.exists():
                        requirements_content = req_path.read_text().lower()
                except (OSError, IOError, UnicodeDecodeError) as e:
                    await record_log(f"⚠️ Could not read requirements.txt: {e}")

            # Smart detection logic
            if "pytesseract" in requirements_content or "tesseract" in requirements_content:
                system_packages.append("tesseract-ocr")
            if "opencv" in requirements_content or "cv2" in requirements_content:
                system_packages.append("libgl1-mesa-glx")
            
            if system_packages:
                await record_log(f"Auto-detected system dependencies: {', '.join(system_packages)}")
                install_lines.append(f"RUN apt-get update && apt-get install -y {' '.join(system_packages)} && rm -rf /var/lib/apt/lists/*")
            else:
                await record_log("No special system dependencies detected in requirements.txt")

            if metadata.get("has_requirements_txt"):
                install_lines.extend(
                    [
                        "COPY requirements.txt ./requirements.txt",
                        "RUN pip install --no-cache-dir -r requirements.txt",
                    ]
                )
            elif metadata.get("has_pyproject_toml"):
                raise RuntimeError("Python pyproject.toml apps need a Dockerfile until pyproject support is added.")

            if metadata.get("python_entrypoint") == "uvicorn":
                start_command = "uvicorn main:app --host 0.0.0.0 --port ${PORT}"
            elif metadata.get("python_entrypoint") == "app_uvicorn":
                start_command = "uvicorn app:app --host 0.0.0.0 --port ${PORT}"
            elif metadata.get("python_entrypoint") == "main_py":
                start_command = "python main.py"
            elif metadata.get("python_entrypoint") == "app_py":
                start_command = "python app.py"
            else:
                raise RuntimeError("No supported Python entrypoint found. Add a Dockerfile or provide main.py/app.py.")

            lines = [
                "FROM python:3.11-slim",
                "WORKDIR /app",
                "ENV PYTHONDONTWRITEBYTECODE=1",
                "ENV PYTHONUNBUFFERED=1",
                "ENV PORT=8000",
            ]
            lines.extend(install_lines)
            lines.extend(
                [
                    "COPY . .",
                    "EXPOSE 8000",
                    f'CMD ["sh", "-c", "{start_command}"]',
                    "",
                ]
            )
            return "\n".join(lines)

        if project_type == "static":
            static_root = metadata.get("static_root", ".")
            return "\n".join(
                [
                    "FROM nginx:1.27-alpine",
                    f"COPY {static_root} /usr/share/nginx/html",
                    "EXPOSE 80",
                    "",
                ]
            )

        if project_type == "go":
            return "\n".join([
                "FROM golang:1.22-alpine AS builder",
                "WORKDIR /app",
                "COPY . .",
                "RUN go build -o app .",
                "FROM alpine:3.19",
                "WORKDIR /app",
                "COPY --from=builder /app/app .",
                "EXPOSE 8080",
                'CMD ["./app"]',
                "",
            ])

        if project_type == "rust":
            return "\n".join([
                "FROM rust:1.77-alpine AS builder",
                "WORKDIR /app",
                "COPY . .",
                "RUN cargo build --release",
                "FROM alpine:3.19",
                "WORKDIR /app",
                "COPY --from=builder /app/target/release/app .",
                "EXPOSE 8080",
                'CMD ["./app"]',
                "",
            ])

        if project_type == "java":
            if metadata.get("java_build") == "gradle":
                return "\n".join([
                    "FROM gradle:8-jdk21 AS builder",
                    "WORKDIR /app",
                    "COPY . .",
                    "RUN gradle build -q && cp build/libs/*.jar /app/app.jar",
                    "FROM eclipse-temurin:21-jre",
                    "WORKDIR /app",
                    "COPY --from=builder /app/app.jar app.jar",
                    "EXPOSE 8080",
                    'CMD ["java", "-jar", "app.jar"]',
                    "",
                ])
            return "\n".join([
                "FROM maven:3.9-eclipse-temurin-21 AS builder",
                "WORKDIR /app",
                "COPY . .",
                "RUN mvn package -q && cp target/*.jar /app/app.jar",
                "FROM eclipse-temurin:21-jre",
                "WORKDIR /app",
                "COPY --from=builder /app/app.jar app.jar",
                "EXPOSE 8080",
                'CMD ["java", "-jar", "app.jar"]',
                "",
            ])

        if project_type == "ruby":
            if metadata.get("ruby_rails"):
                cmd = 'bundle exec rails server -b 0.0.0.0 -p ${PORT:-3000}'
            else:
                cmd = "bundle exec ruby app.rb"
            return "\n".join([
                "FROM ruby:3.3-alpine",
                "WORKDIR /app",
                "COPY . .",
                "RUN bundle install",
                "ENV PORT=3000",
                "EXPOSE 3000",
                f'CMD ["sh", "-c", "{cmd}"]',
                "",
            ])

        if project_type == "php":
            return "\n".join([
                "FROM php:8.3-apache",
                "WORKDIR /var/www/html",
                "COPY --from=composer:2 /usr/bin/composer /usr/bin/composer",
                "COPY . .",
                "RUN composer install --no-dev",
                "EXPOSE 80",
                "",
            ])

        raise RuntimeError("Unsupported project type. Add a Dockerfile to the repository for custom builds.")

    @staticmethod
    def _default_container_port(project_type: str) -> int:
        return {
            "node": 3000, "python": 8000, "static": 80,
            "go": 8080, "rust": 8080, "java": 8080,
            "ruby": 3000, "php": 80,
        }.get(project_type, 8080)

    async def _do_rollback(self, project_id: str) -> None:
        project = await get_project_by_id(project_id)
        rollback_image = project.get("last_good_image") if project else None
        if not rollback_image:
            await update_project(project_id, {
                "status": "failed",
                "last_error": "Rollback failed: no last_good_image recorded.",
            })
            return
        container_name = self.container_name(project_id)
        container_port = project.get("container_port") or self._default_container_port(
            project.get("project_type", "unknown")
        )

        async def record_log(msg: str) -> None:
            await append_build_log(project_id, timestamped_log(msg))

        await record_log(f"Rolling back to {rollback_image}")
        await update_project(project_id, {"status": "building",
                                          "build_logs": [timestamped_log("Rollback started")]})
        await self.stop_project_resources(project)
        repo_url = project.get("repo_url", "")
        project_name = repo_url.rstrip("/").split("/")[-1].replace(".git", "") if repo_url else container_name
        
        pod_result = await create_deployment(
            name=container_name,
            image=rollback_image,
            port=container_port,
            node_port=project.get("assigned_port"),
            env_vars=project.get("env_vars", {}),
            project_name=project_name
        )
        if pod_result.get("status") == "error":
            await update_project(project_id, {
                "status": "failed",
                "last_error": f"Rollback deployment creation failed: {pod_result.get('error')}",
            })
            return
        await wait_for_deployment_running(container_name)
        await self._health_check_pod(
            pod_name=container_name,
            container_port=container_port,
            record_log=record_log,
            health_path=project.get("health_path") or "/",
        )
        await update_project(project_id, {
            "status": "running",
            "image_tag": rollback_image,
        })
        await record_log("✅ Rollback complete.")
        log_event("rollback_complete", project_id=project_id, image=rollback_image)

    @staticmethod
    def _summarize_error(exc: Exception) -> str:
        message = str(exc).strip()
        return message.splitlines()[0][:240] if message else exc.__class__.__name__

    async def _health_check_pod(
        self,
        pod_name: str,
        container_port: int,
        record_log,
        health_path: str = "/",
        pod_ready_timeout: int = 120,
        http_timeout: int = 60,
        http_retries: int = 10,
        http_initial_delay: float = 1.0,
    ) -> None:
        """
        Two-stage post-deployment health check with exponential backoff:
          1. Wait for the K8s pod to reach Running+Ready state.
          2. Probe the app via HTTP using internal Kubernetes DNS.
        Raises RuntimeError on failure so the caller can trigger rollback.
        """
        await record_log("⏳ Waiting for deployment to reach Running state...")
        pod_result = await wait_for_deployment_running(pod_name, timeout_seconds=pod_ready_timeout)
        if pod_result["status"] != "running":
            reason = pod_result.get("reason", "unknown")
            deployhub_health_check_failures_total.labels(reason="pod_not_ready").inc()
            raise RuntimeError(f"Deployment never became ready: {reason}")

        await record_log("✅ Pod is Running. Probing HTTP endpoint...")

        path = health_path if health_path.startswith("/") else f"/{health_path}"
        # Probe the service directly using internal Kubernetes DNS and the container port
        probe_url = f"http://{pod_name}.{settings.apps_namespace}.svc.cluster.local:{container_port}{path}"

        last_error: str = "no attempts made"
        timeout = aiohttp.ClientTimeout(total=10)
        retry_delay = http_initial_delay
        max_delay = 30.0

        for attempt in range(1, http_retries + 1):
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(probe_url, allow_redirects=True) as resp:
                        if resp.status < 500:
                            await record_log(f"✅ Health check passed (HTTP {resp.status}) on attempt {attempt}")
                            return
                        last_error = f"HTTP {resp.status}"
            except Exception as exc:
                last_error = str(exc)

            if attempt < http_retries:
                await record_log(
                    f"⏳ Health check attempt {attempt}/{http_retries} failed ({last_error}), "
                    f"retrying in {retry_delay:.1f}s..."
                )
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 1.5, max_delay)  # exponential backoff

        deployhub_health_check_failures_total.labels(reason="http_probe_failed").inc()
        raise RuntimeError(f"App did not respond after {http_retries} attempts. Last error: {last_error}")
