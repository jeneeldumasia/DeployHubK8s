import asyncio
import time
from functools import partial

from kubernetes import client, config
from kubernetes.client.rest import ApiException

from config import settings


def _user_namespace() -> str:
    return settings.apps_namespace


def _get_k8s_client() -> client.CoreV1Api:
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    return client.CoreV1Api()


def _ensure_apps_namespace_sync() -> None:
    """Best-effort namespace check. Namespace is provisioned by kustomize; SA may lack get/create."""
    v1 = _get_k8s_client()
    ns = _user_namespace()
    try:
        v1.read_namespace(ns)
    except ApiException as e:
        if e.status == 404:
            try:
                v1.create_namespace(client.V1Namespace(metadata=client.V1ObjectMeta(name=ns)))
            except ApiException as create_err:
                if create_err.status not in (403, 409):
                    raise
        elif e.status != 403:
            raise


def _create_deployment_sync(name: str, image: str, port: int, node_port: int = None, env_vars: dict = None, project_name: str = None) -> dict:
    _ensure_apps_namespace_sync()
    v1 = _get_k8s_client()
    apps_v1 = client.AppsV1Api()
    namespace = _user_namespace()

    # Base env vars + user-supplied overrides
    base_env = [
        {"name": "PORT",         "value": str(port)},
        {"name": "HOST",         "value": "0.0.0.0"},
        {"name": "BIND_ADDRESS", "value": "0.0.0.0"},
    ]
    if env_vars:
        # User vars override base vars
        base_names = {e["name"] for e in base_env}
        base_env = [e for e in base_env if e["name"] not in env_vars]
        base_env += [{"name": k, "value": v} for k, v in env_vars.items()]

    deployment_manifest = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": name,
            "labels": {"app": name, "deployhub_project": project_name or name},
        },
        "spec": {
            "replicas": 2,
            "selector": {
                "matchLabels": {"app": name}
            },
            "template": {
                "metadata": {
                    "labels": {"app": name, "deployhub_project": project_name or name}
                },
                "spec": {
                    "imagePullSecrets": [{"name": "ecr-private-key"}],
                    "containers": [
                        {
                            "name": name,
                            "image": image,
                            "imagePullPolicy": "Always",
                            "ports": [{"containerPort": port}],
                            "env": base_env,
                        }
                    ]
                }
            }
        },
    }

    service_port = {
        "protocol": "TCP",
        "port": port,
        "targetPort": port,
    }
    if node_port:
        service_port["nodePort"] = node_port

    service_manifest = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": name},
        "spec": {
            "selector": {"app": name},
            "ports": [service_port],
            "type": "NodePort" if node_port else "ClusterIP",
        },
    }

    try:
        apps_v1.create_namespaced_deployment(namespace=namespace, body=deployment_manifest)
    except ApiException as e:
        return {"status": "error", "error": str(e)}

    try:
        v1.create_namespaced_service(namespace=namespace, body=service_manifest)
    except ApiException as e:
        # Deployment was created but service failed — clean up the deployment
        try:
            apps_v1.delete_namespaced_deployment(name=name, namespace=namespace)
        except ApiException:
            pass
        return {"status": "error", "error": f"Service creation failed (deployment cleaned up): {e}"}

    return {"status": "success", "pod_name": name, "port": port}


def _delete_deployment_sync(name: str) -> dict:
    if not name:
        return {"status": "success"}
    v1 = _get_k8s_client()
    apps_v1 = client.AppsV1Api()
    namespace = _user_namespace()
    try:
        apps_v1.delete_namespaced_deployment(name=name, namespace=namespace)
    except ApiException:
        pass
    try:
        v1.delete_namespaced_service(name=name, namespace=namespace)
        # Wait up to 5 seconds for the service to be fully removed
        for _ in range(10):
            try:
                v1.read_namespaced_service(name=name, namespace=namespace)
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


def _count_running_deployhub_deployments_sync() -> int:
    try:
        apps_v1 = client.AppsV1Api()
        deployments = apps_v1.list_namespaced_deployment(namespace=_user_namespace())
        return sum(
            1
            for d in deployments.items
            if d.metadata.name.startswith("deployhub-") and d.status.ready_replicas
        )
    except Exception:
        return 0


def _get_deployment_logs_sync(name: str, tail: int = 100) -> list[str]:
    try:
        v1 = _get_k8s_client()
        pods = v1.list_namespaced_pod(namespace=_user_namespace(), label_selector=f"app={name}")
        if not pods.items:
            return []
        
        # Prefer a running pod, otherwise just use the first one
        target_pod = next((p for p in pods.items if p.status.phase == "Running"), pods.items[0])
        logs = v1.read_namespaced_pod_log(
            name=target_pod.metadata.name, namespace=_user_namespace(), tail_lines=tail
        )
        return logs.splitlines() if logs else []
    except Exception:
        return []


def _get_occupied_node_ports_sync() -> list[int]:
    try:
        v1 = _get_k8s_client()
        services = v1.list_namespaced_service(namespace=_user_namespace())
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

async def create_deployment(name: str, image: str, port: int, node_port: int = None, env_vars: dict = None, project_name: str = None) -> dict:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(_create_deployment_sync, name, image, port, node_port, env_vars, project_name))


async def delete_deployment(name: str) -> dict:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(_delete_deployment_sync, name))


async def check_k8s_available() -> bool:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _check_k8s_available_sync)


async def count_running_deployhub_deployments() -> int:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _count_running_deployhub_deployments_sync)


async def get_deployment_logs(name: str, tail: int = 100) -> list[str]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(_get_deployment_logs_sync, name, tail))


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
        namespace = _user_namespace()

        ingress_manifest = {
            "apiVersion": "networking.k8s.io/v1",
            "kind": "Ingress",
            "metadata": {
                "name": name,
                "namespace": namespace
            },
            "spec": {
                "ingressClassName": "nginx",
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
        namespace = _user_namespace()
        networking_v1.delete_namespaced_ingress(name=name, namespace=namespace)
        return {"status": "success"}
    except ApiException:
        return {"status": "success"}


def _wait_for_deployment_running_sync(name: str, timeout_seconds: int = 120) -> dict:
    """Poll until deployment has ready replicas or timeout is reached."""
    apps_v1 = client.AppsV1Api()
    v1 = _get_k8s_client()
    namespace = _user_namespace()
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            deployment = apps_v1.read_namespaced_deployment(name=name, namespace=namespace)
            if deployment.status.ready_replicas and deployment.status.ready_replicas > 0:
                return {"status": "running"}
            
            # If not ready, check if any pod is crashing
            pods = v1.list_namespaced_pod(namespace=namespace, label_selector=f"app={name}")
            for pod in pods.items:
                if pod.status.phase in ("Failed", "Unknown"):
                    return {"status": "error", "reason": pod.status.phase}
                container_statuses = pod.status.container_statuses or []
                for cs in container_statuses:
                    if cs.state and cs.state.waiting and cs.state.waiting.reason in ("CrashLoopBackOff", "ErrImagePull", "ImagePullBackOff"):
                        return {"status": "error", "reason": cs.state.waiting.reason}
                    if cs.state and cs.state.terminated and cs.state.terminated.reason == "Error":
                        return {"status": "error", "reason": "Container crashed"}
                        
        except ApiException as e:
            if e.status == 404:
                return {"status": "error", "reason": "Deployment not found"}
        time.sleep(3)
    return {"status": "error", "reason": f"Deployment did not become ready within {timeout_seconds}s"}


def _get_deployment_restart_count_sync(name: str) -> int:
    """Return total restart count across all containers in the deployment's pods."""
    try:
        v1 = _get_k8s_client()
        pods = v1.list_namespaced_pod(namespace=_user_namespace(), label_selector=f"app={name}")
        total_restarts = 0
        for pod in pods.items:
            container_statuses = pod.status.container_statuses or []
            total_restarts += sum(cs.restart_count for cs in container_statuses)
        return total_restarts
    except Exception:
        return 0


def _get_all_deployment_restart_counts_sync() -> dict[str, tuple[int, str]]:
    """Return {deployment_name: (restart_count, project_name)} for all deployhub-managed deployments."""
    try:
        v1 = _get_k8s_client()
        pods = v1.list_namespaced_pod(namespace=_user_namespace())
        result = {}
        for pod in pods.items:
            app_label = pod.metadata.labels.get("app") if pod.metadata.labels else None
            project_name = pod.metadata.labels.get("deployhub_project", app_label) if pod.metadata.labels else app_label
            if app_label and app_label.startswith("deployhub-"):
                container_statuses = pod.status.container_statuses or []
                current_count = result.get(app_label, (0, project_name))[0]
                result[app_label] = (current_count + sum(cs.restart_count for cs in container_statuses), project_name)
        return result
    except Exception:
        return {}


# ── New async wrappers ────────────────────────────────────────────────────────

async def wait_for_deployment_running(name: str, timeout_seconds: int = 120) -> dict:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(_wait_for_deployment_running_sync, name, timeout_seconds))


async def get_deployment_restart_count(name: str) -> int:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(_get_deployment_restart_count_sync, name))


async def get_all_deployment_restart_counts() -> dict[str, tuple[int, str]]:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _get_all_deployment_restart_counts_sync)


def _get_pod_status_sync(deployment_name: str) -> dict:
    """
    Return rich pod status for a deployment:
      phase, ready, restart_count, cpu, memory, events (last 3 warnings).
    Gracefully degrades: CPU/memory are omitted if metrics-server is unavailable.
    """
    v1 = _get_k8s_client()
    namespace = _user_namespace()

    # ── Find the newest running pod for this deployment ───────────────────────
    try:
        pods = v1.list_namespaced_pod(namespace=namespace, label_selector=f"app={deployment_name}")
    except ApiException:
        return {"phase": "Unknown", "ready": False, "restart_count": 0,
                "cpu": None, "memory": None, "events": []}

    if not pods.items:
        return {"phase": "Unknown", "ready": False, "restart_count": 0,
                "cpu": None, "memory": None, "events": []}

    # Prefer a Running pod; fall back to the most recently started one
    target = next((p for p in pods.items if p.status.phase == "Running"), pods.items[0])
    pod_name = target.metadata.name
    phase = target.status.phase or "Unknown"

    # ── Ready status ──────────────────────────────────────────────────────────
    ready = False
    if target.status.conditions:
        for cond in target.status.conditions:
            if cond.type == "Ready" and cond.status == "True":
                ready = True
                break

    # ── Restart count (sum across all containers) ─────────────────────────────
    restart_count = 0
    container_statuses = target.status.container_statuses or []
    for cs in container_statuses:
        restart_count += cs.restart_count

    # ── CPU / memory from metrics-server (best-effort) ────────────────────────
    cpu: str | None = None
    memory: str | None = None
    try:
        metrics_api = __import__("kubernetes").client.CustomObjectsApi()
        pod_metrics = metrics_api.get_namespaced_custom_object(
            group="metrics.k8s.io",
            version="v1beta1",
            namespace=namespace,
            plural="pods",
            name=pod_name,
        )
        cpu_total = 0
        mem_total = 0
        for container in pod_metrics.get("containers", []):
            cpu_total += _parse_cpu_quantity(container["usage"].get("cpu", "0"))
            mem_total += _parse_memory_quantity(container["usage"].get("memory", "0"))
        cpu = f"{cpu_total}m"
        memory = f"{mem_total}Mi"
    except Exception:
        pass  # metrics-server not available — omit CPU/memory

    # ── Last 3 Warning events for this pod ────────────────────────────────────
    events: list[str] = []
    try:
        ev = v1.list_namespaced_event(
            namespace=namespace,
            field_selector=f"involvedObject.name={pod_name},type=Warning",
        )
        # Sort newest-first and take last 3
        sorted_events = sorted(
            ev.items,
            key=lambda e: (e.last_timestamp or e.event_time or ""),
            reverse=True,
        )
        events = [f"{e.reason}: {e.message}" for e in sorted_events[:3] if e.message]
    except Exception:
        pass

    return {
        "phase": phase,
        "ready": ready,
        "restart_count": restart_count,
        "cpu": cpu,
        "memory": memory,
        "events": events,
    }


async def get_pod_status(deployment_name: str) -> dict:
    """Async wrapper for _get_pod_status_sync."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(_get_pod_status_sync, deployment_name))


def _get_namespace_resources_sync(pod_name: str) -> dict:
    """Return current pod resource usage vs namespace quota (metrics API)."""
    v1 = _get_k8s_client()
    ns = _user_namespace()
    usage: dict = {"cpu": "0", "memory": "0"}
    try:
        metrics = client.CustomObjectsApi()
        pod_metrics = metrics.list_namespaced_custom_object(
            group="metrics.k8s.io",
            version="v1beta1",
            namespace=ns,
            plural="pods",
        )
        for item in pod_metrics.get("items", []):
            if item["metadata"]["name"] != pod_name:
                continue
            cpu_total = 0
            mem_total = 0
            for container in item.get("containers", []):
                cpu = container["usage"].get("cpu", "0")
                mem = container["usage"].get("memory", "0")
                cpu_total += _parse_cpu_quantity(cpu)
                mem_total += _parse_memory_quantity(mem)
            usage = {
                "cpu": f"{cpu_total}m",
                "memory": f"{mem_total}Mi",
            }
            break
    except Exception:
        pass

    quota_hard: dict = {}
    try:
        quota = v1.read_namespaced_resource_quota(
            name="deployhub-apps-quota", namespace=ns
        )
        quota_hard = dict(quota.status.hard or {})
    except Exception:
        pass

    return {"usage": usage, "quota": quota_hard}


def _parse_cpu_quantity(value: str) -> int:
    if value.endswith("n"):
        return int(int(value[:-1]) / 1_000_000)
    if value.endswith("u"):
        return int(int(value[:-1]) / 1_000)
    if value.endswith("m"):
        return int(value[:-1])
    return int(float(value) * 1000)


def _parse_memory_quantity(value: str) -> int:
    units = {"Ki": 1024, "Mi": 1024**2, "Gi": 1024**3}
    for suffix, mult in units.items():
        if value.endswith(suffix):
            return int(int(value[:-len(suffix)]) * mult / (1024**2))
    return int(int(value) / (1024**2))


async def get_namespace_resources(pod_name: str) -> dict:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(_get_namespace_resources_sync, pod_name))
