import asyncio
import json
import os
import socket
from pathlib import Path

from config import settings


class DockerError(Exception):
    pass


async def _stream_command(
    args: list[str],
    on_line,
    cwd: Path | None = None,
    timeout_seconds: int | None = None,
) -> tuple[int, list[str]]:
    collected_output: list[str] = []
    process = await asyncio.create_subprocess_exec(
        *args,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, "DOCKER_BUILDKIT": "0"},
    )

    async def read_output() -> None:
        pending = ""
        while True:
            chunk = await process.stdout.read(4096)
            if not chunk:
                break
            pending += chunk.decode("utf-8", errors="replace")
            while "\n" in pending:
                line, pending = pending.split("\n", 1)
                clean_line = line.rstrip()
                if clean_line:
                    collected_output.append(clean_line)
                    await on_line(clean_line)

        trailing = pending.rstrip()
        if trailing:
            collected_output.append(trailing)
            await on_line(trailing)

    output_task = asyncio.create_task(read_output())

    try:
        await asyncio.wait_for(process.wait(), timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        process.kill()
        await process.wait()
        await output_task
        raise DockerError("Docker command timed out") from exc

    await output_task
    return process.returncode, collected_output


async def _run_docker_command(args: list[str]) -> tuple[int, str]:
    process = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, "DOCKER_BUILDKIT": "0"},
    )
    stdout, _ = await process.communicate()
    return process.returncode, stdout.decode("utf-8", errors="replace")


def _is_port_free(host_port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", host_port)) != 0


def _port_candidates(preferred_port: int | None = None) -> list[int]:
    ports = list(range(settings.port_range_start, settings.port_range_end + 1))
    if preferred_port and preferred_port in ports:
        return [preferred_port] + [port for port in ports if port != preferred_port]
    return ports


def allocate_host_port(preferred_port: int | None = None) -> int:
    for port in _port_candidates(preferred_port):
        if _is_port_free(port):
            return port
    raise DockerError(
        f"No free ports available in configured range {settings.port_range_start}-{settings.port_range_end}"
    )


async def check_docker_available() -> bool:
    exit_code, _ = await _run_docker_command(["docker", "version", "--format", "{{.Server.Version}}"])
    return exit_code == 0


async def build_image(image_tag: str, dockerfile_path: Path, context_path: Path, on_line) -> None:
    exit_code, output = await _stream_command(
        ["docker", "build", "-t", image_tag, "-f", str(dockerfile_path), str(context_path)],
        on_line=on_line,
        cwd=context_path,
        timeout_seconds=settings.docker_build_timeout_seconds,
    )
    if exit_code != 0:
        raise DockerError(output[-1] if output else "docker build failed")


async def inspect_exposed_ports(image_tag: str) -> list[int]:
    exit_code, output = await _run_docker_command(
        ["docker", "image", "inspect", image_tag, "--format", "{{json .Config.ExposedPorts}}"],
    )
    if exit_code != 0:
        return []
    raw = output.strip()
    if not raw or raw == "null":
        return []
    try:
        exposed = json.loads(raw)
    except json.JSONDecodeError:
        return []

    ports: list[int] = []
    for key in exposed.keys():
        port = key.split("/")[0]
        if port.isdigit():
            ports.append(int(port))
    return sorted(set(ports))


async def remove_container(container_ref: str | None) -> None:
    if not container_ref:
        return
    await _run_docker_command(["docker", "rm", "-f", container_ref])


async def remove_image(image_tag: str | None) -> None:
    if not image_tag:
        return
    await _run_docker_command(["docker", "rmi", "-f", image_tag])


async def get_container_state(container_ref: str | None) -> dict[str, str | int | bool | None]:
    if not container_ref:
        return {"exists": False, "running": False, "exit_code": None}
    exit_code, output = await _run_docker_command(
        ["docker", "inspect", container_ref, "--format", "{{json .State}}"],
    )
    if exit_code != 0:
        return {"exists": False, "running": False, "exit_code": None}
    try:
        state = json.loads(output.strip())
    except json.JSONDecodeError:
        return {"exists": False, "running": False, "exit_code": None}
    return {
        "exists": True,
        "running": bool(state.get("Running")),
        "exit_code": state.get("ExitCode"),
        "status": state.get("Status"),
    }


async def is_container_running(container_ref: str | None) -> bool:
    state = await get_container_state(container_ref)
    return bool(state.get("running"))


async def count_running_deployhub_containers() -> int:
    exit_code, output = await _run_docker_command(["docker", "ps", "--filter", "label=deployhub.project", "-q"])
    if exit_code != 0:
        return 0
    return len([line for line in output.splitlines() if line.strip()])


async def run_container(
    image_tag: str,
    container_name: str,
    container_port: int,
    env_vars: dict[str, str],
    preferred_host_port: int | None = None,
) -> tuple[str, int, list[str]]:
    await remove_container(container_name)

    last_output = ""
    for _ in range(settings.docker_run_retry_count):
        host_port = allocate_host_port(preferred_port=preferred_host_port)
        args = [
            "docker",
            "run",
            "-d",
            "--name",
            container_name,
            "--label",
            f"deployhub.project={container_name}",
            "-p",
            f"{host_port}:{container_port}",
        ]

        if settings.deployment_network:
            args.extend(["--network", settings.deployment_network])

        for key, value in env_vars.items():
            args.extend(["-e", f"{key}={value}"])

        args.append(image_tag)

        exit_code, output = await _run_docker_command(args)
        last_output = output.strip()
        if exit_code == 0:
            return output.strip(), host_port, [f"Docker run started container '{container_name}' on port {host_port}"]
        if "port is already allocated" not in output.lower():
            raise DockerError(output.strip() or "docker run failed")
        preferred_host_port = None

    raise DockerError(last_output or "Unable to allocate an open host port for the container")


async def get_container_logs(container_id: str, tail: int = 500) -> list[str]:
    exit_code, output = await _run_docker_command(["docker", "logs", "--tail", str(tail), container_id])
    if exit_code != 0:
        return [output.strip()] if output.strip() else []
    return [line for line in output.splitlines() if line.strip()]
