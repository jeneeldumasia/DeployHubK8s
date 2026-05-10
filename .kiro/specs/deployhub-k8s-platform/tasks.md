# Implementation Plan: DeployHub Kubernetes-Native Platform

## Overview

Evolve the existing FastAPI + React + Kubernetes codebase into a production-grade Kubernetes-native PaaS. Work proceeds in six phases: (1) replace bare Pods with Deployment/Service objects and add namespace isolation; (2) replace rule-based detection with an LLM-assisted analysis pipeline and code-patching module; (3) add Terraform-managed infrastructure for local (kind) and EKS; (4) integrate the LGTM observability stack; (5) update the React frontend; (6) harden with integration and property-based tests.

All backend code is Python (FastAPI). All frontend code is JavaScript/React. Infrastructure is Terraform + YAML.

---

## Tasks

- [ ] 1. Kubernetes Deployment Engine — replace bare Pods with Deployments + Services
  - [ ] 1.1 Extend `backend/utils/k8s.py` with Deployment CRUD functions
    - Add `_create_deployment_sync(name, image, port, namespace, labels, replicas=1)` using `client.AppsV1Api`
    - Add `_delete_deployment_sync(name, namespace)` that deletes both the `Deployment` and its matching `Service`
    - Add `_get_deployment_status_sync(name, namespace)` returning ready/desired replica counts
    - Add `_wait_for_rollout_sync(name, namespace, timeout=120)` polling until `ready_replicas >= 1`
    - Wrap each sync function with an `async` executor wrapper (matching the existing pattern)
    - _Requirements: Foundation — Kubernetes Deployment engine_

  - [ ] 1.2 Update RBAC in `k8s/backend.yaml` to grant Deployment and ReplicaSet permissions
    - Add `apps` apiGroup with `deployments`, `replicasets` resources and full verbs to the `pod-manager` Role
    - Keep existing Pod/Service permissions so legacy paths still compile
    - _Requirements: Foundation — Kubernetes Deployment engine_

  - [ ]* 1.3 Write unit tests for `k8s.py` Deployment helpers
    - Mock `kubernetes.client.AppsV1Api` and assert correct manifest structure is passed
    - Test error path: `ApiException` is caught and returned as `{"status": "error"}`
    - _Requirements: Foundation — Kubernetes Deployment engine_

  - [ ] 1.4 Replace `create_pod` / `delete_pod` calls in `backend/worker.py` with `create_deployment` / `delete_deployment`
    - In `DeploymentWorker.deploy()`, replace the `create_pod(...)` call with `create_deployment(...)`
    - In `DeploymentWorker.stop_project_resources()`, replace `delete_pod(...)` with `delete_deployment(...)`
    - Update `service_url` construction to use the Kubernetes Service DNS name: `http://{name}.{namespace}.svc.cluster.local:{port}`
    - _Requirements: Foundation — Kubernetes Deployment engine_

  - [ ] 1.5 Add rolling-update strategy to generated Deployment manifests
    - Set `strategy.type: RollingUpdate` with `maxUnavailable: 0` and `maxSurge: 1` in the manifest dict inside `_create_deployment_sync`
    - Add `readinessProbe` (HTTP GET `/health` or TCP socket) so the rollout gate works correctly
    - _Requirements: Foundation — zero downtime deployments_

  - [ ] 1.6 Checkpoint — verify Deployment engine end-to-end
    - Ensure all tests pass, ask the user if questions arise.

- [ ] 2. Per-Project Namespace Isolation
  - [ ] 2.1 Add `_ensure_namespace_sync(namespace)` to `backend/utils/k8s.py`
    - Create the namespace if it does not exist; ignore `409 Conflict` (already exists)
    - _Requirements: Foundation — per-project namespace isolation_

  - [ ] 2.2 Derive a per-project namespace name in `backend/worker.py`
    - Add helper `project_namespace(project_id: str) -> str` returning `f"dh-{project_id[:16]}"` (DNS-safe, ≤ 63 chars)
    - Call `await ensure_namespace(namespace)` before `create_deployment` in `DeploymentWorker.deploy()`
    - Pass the per-project namespace to all `create_deployment` / `delete_deployment` calls
    - _Requirements: Foundation — per-project namespace isolation_

  - [ ] 2.3 Extend RBAC so the backend ServiceAccount can manage resources in dynamically created namespaces
    - Replace the namespaced `Role` + `RoleBinding` in `k8s/backend.yaml` with a `ClusterRole` + `ClusterRoleBinding` scoped to `deployhub-*` namespace pattern
    - _Requirements: Foundation — per-project namespace isolation_

  - [ ] 2.4 Update `delete_project_resources` to delete the entire per-project namespace
    - Add `_delete_namespace_sync(namespace)` to `k8s.py`
    - Call `await delete_namespace(namespace)` in `DeploymentWorker.delete_project_resources()` when `deployment_mode == "k8s"`
    - _Requirements: Foundation — clean destroy flow_

  - [ ]* 2.5 Write unit tests for namespace helpers
    - Assert `ensure_namespace` is idempotent (second call with 409 does not raise)
    - Assert `delete_namespace` swallows 404
    - _Requirements: Foundation — per-project namespace isolation_

- [ ] 3. LLM-Assisted Analysis Pipeline
  - [ ] 3.1 Add LLM client configuration to `backend/config.py`
    - Add `llm_provider: str = "openai"`, `llm_api_key: str = ""`, `llm_model: str = "gpt-4o-mini"`, `llm_max_tokens: int = 2048`, `llm_timeout_seconds: int = 30` settings
    - Add `analysis_use_llm: bool = True` flag so the rule-based path can be used as fallback
    - _Requirements: Analysis Pipeline — LLM-assisted repo analysis_

  - [ ] 3.2 Create `backend/utils/analyzer.py` — repo analysis module
    - Implement `collect_repo_signals(repo_path: Path) -> dict` that gathers: directory tree (depth ≤ 3), file list, key file contents (`package.json`, `requirements.txt`, `pyproject.toml`, `Dockerfile`, `docker-compose.yml`, first 60 lines of `main.py`/`app.py`/`index.js`)
    - Implement `build_analysis_prompt(signals: dict) -> str` that formats signals into a compact LLM prompt requesting JSON output with fields: `project_type`, `runtime`, `framework`, `build_command`, `start_command`, `port`, `env_vars_needed`, `architecture_recommendation`, `services`
    - Keep total prompt token count under 3 000 by truncating file contents
    - _Requirements: Analysis Pipeline — LLM-assisted repo analysis, efficient token use_

  - [ ] 3.3 Implement `analyze_repo(repo_path: Path) -> AnalysisResult` in `backend/utils/analyzer.py`
    - Call the LLM with the prompt from 3.2; parse the JSON response into an `AnalysisResult` dataclass
    - On LLM failure or JSON parse error, fall back to `detect_project_type` from `detector.py` and construct a minimal `AnalysisResult`
    - Cache the result in a module-level `dict[str, AnalysisResult]` keyed by `repo_path` to avoid re-analysis on redeploy
    - _Requirements: Analysis Pipeline — LLM-assisted repo analysis, efficient token use_

  - [ ]* 3.4 Write property test for `collect_repo_signals` output structure
    - **Property 1: Signal completeness** — for any repo path containing a `package.json`, the returned signals dict must include a non-empty `package_json` key
    - **Validates: Requirements — Analysis Pipeline, efficient token use**

  - [ ]* 3.5 Write unit tests for `analyze_repo` fallback behaviour
    - Mock LLM to raise `httpx.TimeoutException`; assert result equals the rule-based fallback
    - Mock LLM to return malformed JSON; assert result equals the rule-based fallback
    - _Requirements: Analysis Pipeline — LLM-assisted repo analysis_

  - [ ] 3.6 Create `backend/utils/architecture.py` — architecture recommendation engine
    - Implement `recommend_architecture(analysis: AnalysisResult) -> ArchitectureRecommendation` that maps analysis fields to a structured recommendation: `deployment_type` (`single-service` | `multi-service` | `worker+api`), `replicas`, `resource_requests`, `resource_limits`, `needs_persistent_volume`, `suggested_env_vars`, `rationale` (human-readable string)
    - _Requirements: Analysis Pipeline — architecture recommendation engine_

  - [ ]* 3.7 Write property test for `recommend_architecture` output invariants
    - **Property 2: Resource limits ≥ resource requests** — for any valid `AnalysisResult`, `limits.cpu >= requests.cpu` and `limits.memory >= requests.memory`
    - **Validates: Requirements — Analysis Pipeline, architecture recommendation engine**

  - [ ] 3.8 Wire `analyzer.py` and `architecture.py` into `backend/worker.py`
    - Replace the `detect_project_type(repo_path)` call in `DeploymentWorker.deploy()` with `await analyze_repo(repo_path)`
    - Pass `AnalysisResult` fields to `_resolve_dockerfile` and `create_deployment`
    - Store `architecture_recommendation` dict in the project document via `update_project`
    - _Requirements: Analysis Pipeline — LLM-assisted repo analysis, architecture recommendation engine_

  - [ ] 3.9 Extend `backend/models.py` with analysis and recommendation fields
    - Add `architecture_recommendation: dict | None = None` and `analysis_result: dict | None = None` to `ProjectRecord`, `ProjectSummary`, and `ProjectDetail`
    - _Requirements: Analysis Pipeline — architecture recommendation engine_

  - [ ] 3.10 Checkpoint — verify analysis pipeline end-to-end
    - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Code-Patching Module
  - [ ] 4.1 Create `backend/utils/patcher.py`
    - Implement `patch_repo(repo_path: Path, analysis: AnalysisResult) -> PatchReport` that applies the following transforms in-place:
      - Replace hardcoded `localhost` / `127.0.0.1` in source files with `os.environ.get("HOST", "0.0.0.0")` (Python) or `process.env.HOST || "0.0.0.0"` (Node)
      - Ensure server bind address is `0.0.0.0` (not `localhost`)
      - If no `/health` or `/healthz` route exists, inject a minimal health endpoint
    - Return a `PatchReport` listing which files were modified and which patches were applied
    - NEVER modify files outside the repo clone directory; NEVER alter business logic
    - _Requirements: Analysis Pipeline — code-patching module_

  - [ ]* 4.2 Write property test for `patch_repo` idempotency
    - **Property 3: Idempotency** — applying `patch_repo` twice produces the same file contents as applying it once
    - **Validates: Requirements — Analysis Pipeline, code-patching module**

  - [ ]* 4.3 Write property test for `patch_repo` business-logic preservation
    - **Property 4: Non-destructive patching** — for any file not containing `localhost`/`127.0.0.1`, `patch_repo` must leave that file byte-for-byte identical
    - **Validates: Requirements — Analysis Pipeline, code-patching module**

  - [ ] 4.4 Wire `patcher.py` into `backend/worker.py`
    - Call `patch_repo(repo_path, analysis)` after `analyze_repo` and before `_resolve_dockerfile`
    - Log each patched file via `record_log`
    - _Requirements: Analysis Pipeline — code-patching module_

- [ ] 5. Terraform Infrastructure — Local (kind)
  - [ ] 5.1 Create `infra/local/` Terraform module for kind cluster
    - Write `infra/local/main.tf` using the `tehcyx/kind` provider to declare a `kind_cluster` resource named `deployhub`
    - Write `infra/local/variables.tf` with `cluster_name`, `k8s_version`, `registry_port` variables
    - Write `infra/local/outputs.tf` exporting `kubeconfig_path` and `registry_endpoint`
    - _Requirements: Infrastructure as Code — Terraform for local (kind)_

  - [ ] 5.2 Add local registry and BuildKit to the kind cluster config
    - Configure a `containerdConfigPatches` entry in the kind cluster spec to trust the local registry at `localhost:{registry_port}`
    - Add a `null_resource` that applies `k8s/registry.yaml` and `k8s/buildkitd.yaml` after cluster creation
    - _Requirements: Infrastructure as Code — Terraform for local (kind)_

  - [ ] 5.3 Create `infra/local/deployhub.tf` — deploy DeployHub core services via Terraform
    - Use `kubernetes_manifest` resources (or `helm_release` with a local chart) to apply `k8s/namespace.yaml`, `k8s/mongo.yaml`, `k8s/backend.yaml`, `k8s/frontend.yaml`
    - _Requirements: Infrastructure as Code — Terraform for local (kind)_

  - [ ] 5.4 Checkpoint — verify `terraform init && terraform plan` succeeds for local module
    - Ensure all tests pass, ask the user if questions arise.

- [ ] 6. Terraform Infrastructure — EKS (cloud)
  - [ ] 6.1 Create `infra/eks/` Terraform module — VPC and networking
    - Write `infra/eks/vpc.tf` using the `terraform-aws-modules/vpc/aws` module: 3 public + 3 private subnets, NAT gateway, DNS hostnames enabled
    - Write `infra/eks/variables.tf` with `region`, `cluster_name`, `vpc_cidr`, `environment` variables
    - _Requirements: Infrastructure as Code — EKS, VPC/networking_

  - [ ] 6.2 Create `infra/eks/eks.tf` — EKS cluster and node group
    - Use `terraform-aws-modules/eks/aws` module: managed node group in private subnets, instance type `t3.medium`, min 2 / max 5 nodes
    - Enable IRSA (IAM Roles for Service Accounts) for the backend ServiceAccount
    - _Requirements: Infrastructure as Code — EKS_

  - [ ] 6.3 Create `infra/eks/ecr.tf` — ECR registry for built images
    - Declare an `aws_ecr_repository` per-project (or a single shared repo with image tags)
    - Output the registry URL for use in `config.py` `registry_addr`
    - _Requirements: Infrastructure as Code — EKS_

  - [ ] 6.4 Create `infra/eks/lb.tf` — public Load Balancer ingress
    - Install the AWS Load Balancer Controller via `helm_release`
    - Create an `Ingress` resource (or `kubernetes_manifest`) routing `/*` to the frontend Service and `/api/*` to the backend Service
    - _Requirements: Infrastructure as Code — Load Balancer, public access_

  - [ ] 6.5 Write `infra/eks/outputs.tf`
    - Export `cluster_endpoint`, `cluster_name`, `ecr_registry_url`, `load_balancer_hostname`
    - _Requirements: Infrastructure as Code — EKS_

- [ ] 7. LGTM Observability Stack Integration
  - [ ] 7.1 Create `k8s/observability/` directory with Loki, Prometheus, Grafana manifests
    - Write `k8s/observability/namespace.yaml` creating `monitoring` namespace
    - Write `k8s/observability/prometheus.yaml`: `Deployment` + `Service` + `ConfigMap` for `prometheus.yml` with a scrape config targeting `deployhub` namespace pods on `/metrics`
    - Write `k8s/observability/loki.yaml`: `Deployment` + `Service` + `PersistentVolumeClaim` for Loki log storage
    - Write `k8s/observability/grafana.yaml`: `Deployment` + `Service` (NodePort or LoadBalancer) + `ConfigMap` with pre-provisioned Prometheus and Loki datasources
    - _Requirements: Observability — LGTM stack integration_

  - [ ] 7.2 Add per-project Prometheus scrape annotations to generated Deployments
    - In `_create_deployment_sync` (k8s.py), add pod template annotations: `prometheus.io/scrape: "true"`, `prometheus.io/port: "{port}"`, `prometheus.io/path: "/metrics"`
    - Update the Prometheus `ConfigMap` scrape config to use `kubernetes_sd_configs` with `role: pod` and relabeling on those annotations
    - _Requirements: Observability — per-project Prometheus scraping_

  - [ ] 7.3 Add Promtail (Loki log shipper) DaemonSet to `k8s/observability/`
    - Write `k8s/observability/promtail.yaml`: `DaemonSet` that mounts `/var/log/pods` and ships logs to Loki, with a pipeline stage that adds `project_id` label from pod label `deployhub.io/project-id`
    - Add `deployhub.io/project-id: {project_id}` label to pod templates in `_create_deployment_sync`
    - _Requirements: Observability — Loki log shipping, per-project observability_

  - [ ] 7.4 Extend `backend/observability.py` with per-project metrics
    - Add `deployhub_project_deployment_duration_seconds` Histogram with `project_id` label
    - Add `deployhub_project_build_failures_total` Counter with `project_id` and `phase` labels
    - Emit these metrics from `DeploymentWorker.deploy()` after the existing metrics calls
    - _Requirements: Observability — per-project Prometheus scraping_

  - [ ] 7.5 Add Grafana dashboard ConfigMap for DeployHub
    - Write `k8s/observability/grafana-dashboard.yaml` with a `ConfigMap` containing a JSON dashboard definition that panels: deployment duration histogram, active deployments gauge, build failure rate, and a Loki log panel filtered by `project_id`
    - _Requirements: Observability — LGTM stack integration, per-project observability_

  - [ ] 7.6 Checkpoint — verify observability stack applies cleanly
    - Ensure all tests pass, ask the user if questions arise.

- [ ] 8. Frontend — Architecture Recommendation UI
  - [ ] 8.1 Add `architecture_recommendation` display to the Project Detail panel in `frontend/src/App.jsx`
    - After the existing `detail-grid`, render a collapsible `<details>` section titled "Architecture Recommendation"
    - Display `deployment_type`, `replicas`, `resource_requests`, `resource_limits`, and `rationale` fields from `project.architecture_recommendation`
    - Only render the section when `architecture_recommendation` is non-null
    - _Requirements: Frontend — architecture recommendation UI_

  - [ ] 8.2 Add `analysis_result` display panel showing detected runtime, framework, and suggested env vars
    - Render a second collapsible `<details>` section titled "Analysis Details" showing `runtime`, `framework`, `build_command`, `start_command`, `port`, `env_vars_needed`
    - _Requirements: Frontend — architecture recommendation UI_

  - [ ] 8.3 Improve deployment status display with phase-aware progress indicator
    - Add a `DeploymentProgress` component that maps `status` values (`queued` → `building` → `running`) to a visual step indicator
    - Show elapsed time since `updated_at` while status is `building`
    - _Requirements: Frontend — improved deployment status_

  - [ ] 8.4 Add destroy flow confirmation modal
    - Replace the `window.confirm` calls in `handleProjectAction` with a React modal component that shows: action name, project repo URL, and a list of resources that will be deleted (namespace, Deployment, Service, image)
    - _Requirements: Frontend — destroy flow_

  - [ ] 8.5 Update `ProjectSummary` and `ProjectDetail` API response serialization in `backend/main.py`
    - Add `architecture_recommendation` and `analysis_result` fields to `serialize_project_summary` and `serialize_project_detail`
    - _Requirements: Frontend — architecture recommendation UI_

- [ ] 9. Integration Tests and Hardening
  - [ ] 9.1 Create `backend/tests/` directory and `conftest.py`
    - Set up `pytest` with `pytest-asyncio` and `httpx.AsyncClient` for FastAPI testing
    - Add a `mongo_client` fixture using `mongomock-motor` or a real test MongoDB URI from env
    - Add a `mock_k8s` fixture that patches `kubernetes.client` with `unittest.mock.MagicMock`
    - _Requirements: Testing & Hardening_

  - [ ] 9.2 Write integration tests for the deployment lifecycle API
    - `POST /api/projects` → assert 200 and `status == "created"`
    - `POST /api/deploy/{id}` → assert 200 and `status == "queued"`
    - `DELETE /api/projects/{id}` → assert 204 and project removed from DB
    - Mock `DeploymentWorker.enqueue` to avoid real queue processing
    - _Requirements: Testing & Hardening_

  - [ ]* 9.3 Write property test for `project_namespace` name generation
    - **Property 5: DNS safety** — for any `project_id` string, `project_namespace(project_id)` must match `^[a-z0-9][a-z0-9-]{0,61}[a-z0-9]$` and be ≤ 63 characters
    - **Validates: Requirements — Foundation, per-project namespace isolation**

  - [ ]* 9.4 Write property test for `build_analysis_prompt` token budget
    - **Property 6: Prompt token budget** — for any repo signals dict, `len(build_analysis_prompt(signals).split()) <= 3000`
    - **Validates: Requirements — Analysis Pipeline, efficient token use**

  - [ ]* 9.5 Write property test for `patch_repo` localhost replacement completeness
    - **Property 7: No residual localhost** — after `patch_repo`, no patched source file contains the literal string `localhost` or `127.0.0.1` in a server-bind context
    - **Validates: Requirements — Analysis Pipeline, code-patching module**

  - [ ] 9.6 Write integration test for the full worker deploy path (k8s mode, mocked)
    - Instantiate `DeploymentWorker(deployment_mode="k8s")` with mocked `buildkit_build_image`, `create_deployment`, `ensure_namespace`
    - Call `worker.deploy(project_id)` and assert: namespace ensured, image built, deployment created, project status set to `"running"`
    - _Requirements: Testing & Hardening_

  - [ ] 9.7 Write integration test for the destroy flow
    - Assert `delete_project_resources` calls `delete_namespace` (not just `delete_deployment`) in k8s mode
    - Assert repo clone directory is removed from disk
    - _Requirements: Testing & Hardening, Foundation — clean destroy flow_

  - [ ] 9.8 Final checkpoint — all tests pass, linting clean
    - Ensure all tests pass, ask the user if questions arise.

---

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- Each task references the phase/requirement it satisfies for traceability
- Checkpoints (tasks 1.6, 3.10, 5.4, 7.6, 9.8) are natural integration points — pause and verify before continuing
- Property tests (3.4, 3.7, 4.2, 4.3, 9.3–9.5) validate universal correctness invariants; unit tests validate specific examples
- The LLM API key (`llm_api_key`) must be set in `.env` before tasks 3.2–3.8 can be exercised end-to-end; the fallback path (rule-based detector) works without it
- Terraform tasks (5–6) are independent of backend/frontend tasks and can be worked in parallel
- The LGTM stack (task 7) can be applied to the cluster at any point after task 1 is complete
