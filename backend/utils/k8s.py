import asyncio
import time
from functools import partial

from kubernetes import client, config
from kubernetes.client.rest import ApiException

from config import settings


def _get_k8s_client() -> client.CoreV1Api:
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    return client.CoreV1Api()


def _create_pod_sync(name: str, image: str, port: int, node_port: int = None) -> dict:
    v1 = _get_k8s_client()
    namespace = settings.k8s_namespace

    pod_manifest = {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {
            "name": name,
            "labels": {"app": name},
        },
        "spec": {
            "imagePullSecrets": [{"name": "ecr-private-key"}],
            "containers": [
                {
                    "name": name,
                    "image": image,
                    "imagePullPolicy": "Always",
                    "ports": [{"containerPort": port}],
                    "env": [
                        {"name": "PORT", "value": str(port)},
                        {"name": "HOST", "value": "0.0.0.0"},
                        {"name": "BIND_ADDRESS", "value": "0.0.0.0"},
                    ],
                }
            ]
        },
    }

    service_manifest = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": name},
        "spec": {
            "selector": {"app": name},
            "ports": [
                {
                    "protocol": "TCP",
                    "port": port,
                    "targetPort": port,
                    "nodePort": node_port if node_port else None
                }
            ],
            "type": "NodePort" if node_port else "ClusterIP",
        },
    }

    try:
        v1.create_namespaced_pod(namespace=namespace, body=pod_manifest)
        v1.create_namespaced_service(namespace=namespace, body=service_manifest)
        return {"status": "success", "pod_name": name, "port": port}
    except ApiException as e:
        return {"status": "error", "error": str(e)}


def _delete_pod_sync(name: str) -> dict:
    if not name:
        return {"status": "success"}
    v1 = _get_k8s_client()
    namespace = settings.k8s_namespace
    try:
        v1.delete_namespaced_pod(name=name, namespace=namespace)
    except ApiException:
        pass
    try:
        v1.delete_namespaced_service(name=name, namespace=namespace)
        # Wait up to 5 seconds for the service to be fully removed
        for _ in range(10):
            try:
                v1.read_namespaced_service(name=name, namespace=namespace)
                import time
                time.sleep(0.5)
            except ApiException as e:
                if e.status == 404:
                    break
    except ApiException:
        pass
    return {"status": "success"}


def _check_k8s_available_sync() -> bool:
    try:
        v1 = _get_k8s_client()
        v1.list_namespaced_pod(namespace=settings.k8s_namespace, limit=1)
        return True
    except Exception:
        return False


def _count_running_deployhub_pods_sync() -> int:
    try:
        v1 = _get_k8s_client()
        pods = v1.list_namespaced_pod(namespace=settings.k8s_namespace)
        return sum(
            1
            for pod in pods.items
            if pod.metadata.name.startswith("deployhub-") and pod.status.phase == "Running"
        )
    except Exception:
        return 0


def _get_pod_logs_sync(name: str, tail: int = 100) -> list[str]:
    try:
        v1 = _get_k8s_client()
        logs = v1.read_namespaced_pod_log(
            name=name, namespace=settings.k8s_namespace, tail_lines=tail
        )
        return logs.splitlines() if logs else []
    except Exception:
        return []


def _get_occupied_node_ports_sync() -> list[int]:
    try:
        v1 = _get_k8s_client()
        services = v1.list_namespaced_service(namespace=settings.k8s_namespace)
        ports = []
        for svc in services.items:
            if svc.spec.ports:
                for p in svc.spec.ports:
                    if p.node_port:
                        ports.append(p.node_port)
        return ports
    except Exception:
        return []


# ── Async wrappers (run blocking SDK calls in a thread pool) ──────────────────

async def create_pod(name: str, image: str, port: int, node_port: int = None) -> dict:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(_create_pod_sync, name, image, port, node_port))


async def delete_pod(name: str) -> dict:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(_delete_pod_sync, name))


async def check_k8s_available() -> bool:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _check_k8s_available_sync)


async def count_running_deployhub_pods() -> int:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _count_running_deployhub_pods_sync)


async def get_pod_logs(name: str, tail: int = 100) -> list[str]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(_get_pod_logs_sync, name, tail))


async def get_occupied_node_ports() -> list[int]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _get_occupied_node_ports_sync)


async def create_ingress(name: str, host: str, service_port: int) -> dict:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(_create_ingress_sync, name, host, service_port))


async def delete_ingress(name: str) -> dict:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(_delete_ingress_sync, name))


def _get_networking_client():
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    return client.NetworkingV1Api()


def _create_ingress_sync(name: str, host: str, service_port: int) -> dict:
    try:
        networking_v1 = _get_networking_client()
        namespace = settings.k8s_namespace
        
        ingress_manifest = {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "Ingress",
            "metadata": {
                "name": name,
                "namespace": namespace,
                "annotations": {
                    "traefik.ingress.kubernetes.io/router.entrypoints": "web"
                }
            },
            "spec": {
                "rules": [
                    {
                        "host": host,
                        "http": {
                            "paths": [
                                {
                                    "path": "/",
                                    "pathType": "Prefix",
                                    "backend": {
                                        "service": {
                                            "name": name,
                                            "port": {"number": service_port}
                                        }
                                    }
                                }
                            ]
                        }
                    }
                ]
            }
        }
        
        networking_v1.create_namespaced_ingress(namespace=namespace, body=ingress_manifest)
        return {"status": "success"}
    except ApiException as e:
        return {"status": "error", "error": str(e)}


def _delete_ingress_sync(name: str) -> dict:
    try:
        networking_v1 = _get_networking_client()
        namespace = settings.k8s_namespace
        networking_v1.delete_namespaced_ingress(name=name, namespace=namespace)
        return {"status": "success"}
    except ApiException:
        return {"status": "success"}


def _wait_for_pod_running_sync(name: str, timeout_seconds: int = 120) -> dict:
    """Poll until pod phase is Running or timeout is reached."""
    v1 = _get_k8s_client()
    namespace = settings.k8s_namespace
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            pod = v1.read_namespaced_pod(name=name, namespace=namespace)
            phase = pod.status.phase
            if phase == "Running":
                # Also check all containers are ready
                container_statuses = pod.status.container_statuses or []
                all_ready = all(cs.ready for cs in container_statuses)
                if all_ready:
                    return {"status": "running"}
                # Pod is Running but containers not yet ready — keep waiting
            elif phase in ("Failed", "Unknown"):
                # Grab last termination reason if available
                reason = phase
                container_statuses = pod.status.container_statuses or []
                for cs in container_statuses:
                    if cs.state and cs.state.terminated:
                        reason = cs.state.terminated.reason or reason
                    elif cs.state and cs.state.waiting:
                        reason = cs.state.waiting.reason or reason
                return {"status": "error", "reason": reason}
        except ApiException as e:
            if e.status == 404:
                return {"status": "error", "reason": "Pod not found"}
        time.sleep(3)
    return {"status": "error", "reason": f"Pod did not become ready within {timeout_seconds}s"}


def _get_pod_restart_count_sync(name: str) -> int:
    """Return total restart count across all containers in a pod."""
    try:
        v1 = _get_k8s_client()
        pod = v1.read_namespaced_pod(name=name, namespace=settings.k8s_namespace)
        container_statuses = pod.status.container_statuses or []
        return sum(cs.restart_count for cs in container_statuses)
    except Exception:
        return 0


def _get_all_pod_restart_counts_sync() -> dict[str, int]:
    """Return {pod_name: restart_count} for all deployhub-managed pods."""
    try:
        v1 = _get_k8s_client()
        pods = v1.list_namespaced_pod(namespace=settings.k8s_namespace)
        result = {}
        for pod in pods.items:
            if pod.metadata.name.startswith("deployhub-"):
                container_statuses = pod.status.container_statuses or []
                result[pod.metadata.name] = sum(cs.restart_count for cs in container_statuses)
        return result
    except Exception:
        return {}


# ── New async wrappers ────────────────────────────────────────────────────────

async def wait_for_pod_running(name: str, timeout_seconds: int = 120) -> dict:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(_wait_for_pod_running_sync, name, timeout_seconds))


async def get_pod_restart_count(name: str) -> int:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(_get_pod_restart_count_sync, name))


async def get_all_pod_restart_counts() -> dict[str, int]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _get_all_pod_restart_counts_sync)
