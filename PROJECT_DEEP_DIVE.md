# DeployHub — Complete Technical Deep Dive

This document covers every layer of the project in enough detail to answer any question from a manager, interviewer, or technical reviewer.

---

## 1. What Is DeployHub?

DeployHub is a self-hosted PaaS (Platform-as-a-Service) — think a mini Heroku or Render that you run yourself on AWS. You give it a public GitHub repository URL, and it automatically:

1. Clones the repo
2. Figures out what kind of project it is (Node.js, Python, static HTML)
3. Generates a Dockerfile if the repo doesn't have one
4. Builds a Docker image using BuildKit running inside Kubernetes
5. Pushes the image to AWS ECR (Elastic Container Registry)
6. Deploys it as a Kubernetes Pod with a public URL
7. Runs a health check — rolls back automatically if it fails
8. Streams live build logs to the browser in real time

Everything is real infrastructure. Nothing is mocked or simulated.

---

## 2. The Full User Flow (Step by Step)

1. User opens the React frontend at `http://<ec2-ip>:3080`
2. User pastes a GitHub repo URL (e.g. `https://github.com/owner/my-app`) and clicks "Add Project"
3. Frontend calls `POST /api/analyze` — backend clones the repo and scans it for services
4. If multiple services are found (monorepo), the UI shows a picker. If one, it auto-proceeds.
5. Frontend calls `POST /api/projects` — creates a project record in MongoDB with status `queued`
6. The async DeploymentWorker picks it up from the queue and runs the full pipeline:
   - Clone/pull the repo
   - Detect project type and generate a Dockerfile if needed
   - Build the image via BuildKit (in-cluster), push to ECR
   - Allocate a free NodePort (range 3000–3999)
   - Create a Kubernetes Pod + Service in the `deployhub` namespace
   - Create a Traefik Ingress for `<repo-slug>.jeneeldumasia.codes`
   - Run a two-stage health check: wait for pod Ready, then HTTP-probe the NodePort
   - On failure: auto-rollback (delete pod + ingress, mark project `failed`)
   - On success: mark project `running`, store the `service_url`
7. The frontend streams live build logs via Server-Sent Events (SSE)
8. User can redeploy, stop, or delete the project from the UI
9. GitHub webhook (`POST /api/webhooks/github/{id}`) triggers auto-redeploy on push

---

## 3. Architecture Overview

```
User Browser
    │
    ▼
React Frontend (Nginx, port 3080)
    │  /api/* proxied to backend
    ▼
FastAPI Backend (Python 3.11, port 3081/8000)
    │
    ├── MongoDB (Motor async driver) — project state, build logs
    │
    ├── BuildKit (in-cluster, tcp://buildkitd:1234) — image builds
    │
    ├── AWS ECR — image storage (deployhub-backend, deployhub-frontend, deployhub-apps)
    │
    └── Kubernetes API — create/delete user pods, services, ingresses
            │
            └── User App Pods (deployhub-{id}) — dynamically created per project
```

**Observability stack (same cluster):**
- Prometheus → scrapes `/metrics` every 15s
- Grafana → pre-provisioned dashboards, reads from Prometheus + Loki
- Loki → log aggregation backend
- Promtail → DaemonSet, ships all pod logs to Loki

---

## 4. Backend — API Endpoints

All defined in `backend/main.py` using FastAPI.

| Method | Path | What it does |
|--------|------|-------------|
| GET | `/health` | Liveness check — always returns `{"status":"ok"}` |
| GET | `/ready` | Readiness — pings MongoDB + checks K8s availability |
| GET | `/metrics` | Prometheus metrics (refreshes gauges on each call) |
| POST | `/api/analyze` | Clones repo, detects services, returns list |
| POST | `/api/projects` | Creates project record, queues initial deploy |
| GET | `/api/projects` | Lists all projects (newest first) |
| GET | `/api/projects/{id}` | Full project detail |
| POST | `/api/deploy/{id}` | Queues a deploy |
| POST | `/api/redeploy/{id}` | Queues a redeploy |
| POST | `/api/stop/{id}` | Stops pod, marks `stopped` |
| DELETE | `/api/projects/{id}` | Deletes project + all resources |
| GET | `/api/logs/{id}` | Snapshot of build + runtime logs |
| GET | `/api/logs/{id}/stream` | SSE live log stream |
| GET | `/api/projects/{id}/health` | Live pod phase + restart count |
| POST | `/api/webhooks/github/{id}` | GitHub push webhook → queues redeploy |
| GET | `/api/system` | Cluster status snapshot |

---

## 5. Backend — The Deployment Worker

`DeploymentWorker` in `backend/worker.py` is the core engine.

**Queue mechanism:**
- `asyncio.Queue` — items are `(action, project_id)` tuples
- Two sets for deduplication: `enqueued_project_ids` and `active_project_ids`
- Prevents the same project from being queued twice simultaneously
- Single background `asyncio.Task` loops on `queue.get()`

**Deploy pipeline (k8s mode):**
1. `clone_or_update_repo()` — git clone with `--depth 1`, or `git pull --ff-only` if already cloned
2. `detect_project_type()` — checks for `package.json` (Node), `requirements.txt`/`main.py` (Python), `index.html` (static)
3. `_resolve_dockerfile()` — uses repo's own Dockerfile if present, otherwise generates one
4. `buildkit_build_image()` — calls `buildctl build` via subprocess, pushes to ECR
5. Port allocation — scans occupied NodePorts via K8s API, picks first free one in range 3000–3999
6. `create_pod()` — creates Pod + NodePort Service in `deployhub` namespace
7. `create_ingress()` — Traefik Ingress for subdomain routing
8. `_health_check_pod()` — waits for pod Ready (120s), then HTTP probes NodePort (10 retries × 5s)
9. On failure: `delete_pod()` + `delete_ingress()` + mark `failed`
10. On success: update project with `service_url`, mark `running`

**Dockerfile generation:**
- Node: detects `npm run start` or `npm run dev`, uses `npm ci` if `package-lock.json` exists
- Python: detects FastAPI/Flask/uvicorn from `requirements.txt` content, auto-detects system deps (Tesseract, OpenCV)
- Static: wraps in `nginx:1.27-alpine`
- Raises `RuntimeError` for unsupported types (forces user to add their own Dockerfile)

---

## 6. Backend — Key Files Explained

### `config.py`
Pydantic `BaseSettings` — reads from environment variables or `.env`:
- `deployment_mode`: `"k8s"` (default in production) or `"docker"` (local dev with Docker Compose)
- `k8s_namespace`: `"deployhub"` — where user pods are created
- `buildkit_addr`: `"tcp://buildkitd:1234"` — in-cluster BuildKit service address
- `port_range_start/end`: `3000–3999` — NodePort allocation range
- `base_domain`: `"jeneeldumasia.codes"` — for Ingress subdomain generation
- `aws_region`: `"us-east-1"`

### `models.py`
Pydantic models defining all data shapes:
- `ProjectStatus`: `created | queued | building | running | stopped | failed | deleting`
- `ProjectType`: `node | python | static | unknown`
- `ProjectCreate`: what the user submits `{repo_url, context_path, service_name}`
- `ProjectSummary` / `ProjectDetail`: what the API returns
- `LogsResponse`: `{build_logs[], runtime_logs[]}`

### `database.py`
Async MongoDB via Motor:
- Singleton client initialized at startup via `lifespan` context manager
- Collections: `projects` with indexes on `normalized_repo_url` (unique), `status`, `created_at`
- `append_build_log()` uses MongoDB `$push` operator — appends one log line atomically
- `update_project()` always sets `updated_at` to current UTC time

### `observability.py`
All custom Prometheus metrics:
- `deployhub_projects_total` — Gauge (total projects in DB)
- `deployhub_deployments_total{action}` — Counter (deploy/redeploy requests)
- `deployhub_deployment_failures_total{phase}` — Counter
- `deployhub_deployment_success_total{action}` — Counter
- `deployhub_deployment_duration_seconds{action}` — Histogram (p50/p95 in Grafana)
- `deployhub_active_containers` — Gauge (running pods)
- `deployhub_health_check_failures_total{reason}` — Counter
- `deployhub_pod_restarts_total{pod_name}` — Gauge
- `http_requests_total{method,path,status_code}` — Counter
- `http_request_duration_seconds{method,path}` — Histogram
- `log_event()` — emits structured JSON to stdout, parsed by Promtail into Loki labels

---

## 7. Backend — Utility Modules

### `utils/buildkit.py`
- Calls `buildctl build` via `subprocess.run`
- Sets `BUILDKIT_HOST` env var to point at in-cluster `tcp://buildkitd:1234`
- For ECR images: calls `boto3` to get an ECR auth token, writes a temporary `~/.docker/config.json`, passes it via `DOCKER_CONFIG` env var, cleans up after
- `registry_insecure=True` only for local registries — ECR always uses HTTPS

### `utils/k8s.py`
- Uses the official `kubernetes` Python SDK
- Tries in-cluster config first (`/var/run/secrets/kubernetes.io/serviceaccount`), falls back to `~/.kube/config`
- All blocking SDK calls wrapped in `asyncio.run_in_executor` so they don't block the async event loop
- `create_pod()`: Pod manifest with `imagePullSecrets: ecr-private-key`, env vars `PORT/HOST/BIND_ADDRESS`, plus a NodePort Service
- `wait_for_pod_running()`: polls pod phase every 3s up to 120s, checks all containers are ready
- `get_all_pod_restart_counts()`: returns `{pod_name: restart_count}` for all `deployhub-*` pods

### `utils/git.py`
- `normalize_repo_url()`: validates host against allowlist (`github.com`), strips `.git` suffix, re-adds it consistently
- `clone_or_update_repo()`: if `.git` exists and remote matches → `git pull --ff-only`; if remote differs → delete and fresh clone; always uses `--depth 1` for speed

### `utils/detector.py`
- `detect_project_type()`: checks for `package.json` → Node, `requirements.txt`/`pyproject.toml`/`main.py`/`app.py` → Python, `index.html` → static
- `detect_python_entrypoint()`: reads file content to detect FastAPI vs Flask vs plain Python

### `utils/analyzer.py`
- `RepoAnalyzer.analyze()`: recursive `os.walk` (skips `node_modules`, `.git`, `venv`, etc.)
- Returns `List[DetectedService]` with `name`, `path`, `type`, `framework`
- Framework detection: reads `package.json` for `next`/`vite`/`express`; reads `requirements.txt` for `fastapi`/`flask`
- Used for monorepo support — can detect multiple deployable services in one repo

---

## 8. Frontend

**Stack**: React 18 + Vite 5, served by Nginx. No external UI component libraries.

### Three UI Sections

**Hero Panel** — URL input + "Add Project" button
- On submit: calls `/api/analyze` first to detect services
- If multiple services: shows a service picker grid
- If one service: auto-deploys immediately

**Workspace** (two-column layout):
- Left: Projects list — cards with service name, type, status badge, "Open" link
- Right: Project detail — full metadata (repo URL, type, port, container ID, image tag, timestamps), webhook URL with copy button, action buttons (Deploy / Redeploy / Stop / Delete)

**Logs Panel** — two columns: Build Logs | Runtime Logs
- Primary: SSE stream via `EventSource` on `/api/logs/{id}/stream`
- Fallback: 5-second polling if SSE connection fails
- Stream state indicator shows `idle | live | polling`

### Nginx Config
- Proxies `/api/*` → `http://backend:8000` with `proxy_buffering off` (required for SSE to work)
- All other paths → `index.html` (SPA routing)

### Theme
Dark/light toggle stored in `localStorage`.

---

## 9. Infrastructure — Two Deployment Targets

### k3s (KodeKloud / Quick Demo)
**What it is**: k3s is a lightweight Kubernetes distribution. One EC2 instance runs the entire cluster.

**Terraform provisions** (`terraform/environments/k3s/`):
- Ubuntu 22.04 EC2 instance (t3.medium, 30GB gp2 disk)
- k3s installed via `user_data` script on first boot: `curl -sfL https://get.k3s.io | sh -`
- NodePort range extended to `3000–3999` via `--service-node-port-range`
- TLS SAN set to public IP so kubectl works remotely
- IAM role with `AmazonEC2ContainerRegistryPowerUser` attached — lets the instance pull/push ECR images without static credentials
- Security group opens: 22 (SSH), 80 (HTTP), 6443 (k3s API), 3000–3999 (NodePorts), 8000 (backend direct)
- SSH access via EC2 Instance Connect — ephemeral RSA key generated per CI run, pushed for 60 seconds, no stored secrets

**State management**: Account-scoped S3 key (`environments/k3s/<account-id>/terraform.tfstate`) so each AWS account gets a clean state — critical for KodeKloud lab portability.

### EKS (Production)
**What it is**: AWS managed Kubernetes — control plane managed by AWS, worker nodes are EC2 instances.

**Terraform provisions** (`terraform/environments/prod/`):
- **Networking module**: Custom VPC (10.0.0.0/16), public + private subnets across 2 AZs, NAT Gateway per AZ (for HA), route tables, 3 security groups (ALB, EKS nodes, ECS tasks)
- **EKS module**: Managed node groups (one per AZ), OIDC provider for IRSA, ALB Controller IAM role, Backend ServiceAccount IAM role
- **ECR module**: 3 repos (`deployhub-backend`, `deployhub-frontend`, `deployhub-apps`), scan-on-push enabled, lifecycle policy (keep last 10 tagged images, delete untagged after 1 day)
- **ALB**: Internet-facing Application Load Balancer, listener rules route `/api/*` → backend, `/grafana/*` → Grafana, `/` → frontend
- **ECS Monitoring**: Fargate tasks for Prometheus + Grafana + Loki, EFS for persistent storage

**IRSA (IAM Roles for Service Accounts)**: The backend pod assumes an IAM role via Kubernetes ServiceAccount annotation — no static AWS credentials in the pod. The role has `AmazonEC2ContainerRegistryPowerUser` to push built images to ECR.

---

## 10. Kubernetes Manifests (`k8s_deploy/`)

All resources live in the `deployhub` namespace.

| File | What it creates |
|------|----------------|
| `namespace.yaml` | The `deployhub` namespace |
| `backend.yaml` | PVC (20Gi for repos/dockerfiles), ServiceAccount with IRSA annotation, RBAC Role (`pod-manager` — can create/delete pods/services/ingresses), Deployment (Recreate strategy, liveness + readiness probes, resource limits 250m–1000m CPU / 256Mi–1Gi RAM), NodePort Service on 3081 |
| `frontend.yaml` | Nginx deployment, NodePort Service on 3080 |
| `mongo.yaml` | MongoDB deployment + PVC (5Gi) + ClusterIP Service on 27017 |
| `buildkitd.yaml` | BuildKit daemon (privileged container, `moby/buildkit:v0.19.0`), ClusterIP Service on 1234 |
| `monitoring.yaml` | Prometheus (ConfigMap with scrape config + alert rules, PVC 5Gi, NodePort 3090) + Grafana (3 ConfigMaps for datasources/dashboards/provider, PVC 2Gi, NodePort 3091) |
| `logging.yaml` | Loki (ConfigMap, PVC 5Gi, ClusterIP) + Promtail (DaemonSet with ClusterRole to read pod logs, mounts `/var/log` and `/var/lib/docker/containers`) |
| `hpa.yaml` | HPA for backend: min 1, max 5 replicas; scale up at 70% CPU / 80% memory; scale-down stabilization 5 minutes |
| `ingress.yaml` | ALB Ingress (EKS) routing `/api`, `/health`, `/ready`, `/metrics` → backend; `/` → frontend |
| `secrets.yaml` | Template with `REPLACE_ME_*` placeholders — rendered by `envsubst` at deploy time |

**Why Recreate strategy on backend?** The backend has a single replica and a readiness probe that checks MongoDB. With RollingUpdate, Kubernetes waits for the new pod to be ready before killing the old one — but if the new pod can't connect to MongoDB immediately, it never becomes ready, causing a deadlock. Recreate kills the old pod first, then starts the new one.

---

## 11. Observability — The Full Triad

### Metrics (Prometheus)
- Deployed in-cluster (k3s) or on ECS Fargate (prod)
- Scrapes `backend:8000/metrics` every 15 seconds
- 15-day data retention
- Alert rules:
  - `HighDeploymentFailureRate`: >0.1 failures/sec over 5 minutes → warning
  - `HealthCheckFailures`: >2 HC failures in 10 minutes → warning
  - `BackendDown`: backend unreachable for 1 minute → critical
  - `PodRestartingFrequently`: restart count >5 for 5 minutes → warning

### Dashboards (Grafana)
- Pre-provisioned via Kubernetes ConfigMaps — no manual setup needed
- Datasources: Prometheus (default) + Loki
- DeployHub Overview dashboard panels:
  - Stat cards: Total Projects, Running Pods, Deployment Failures (1h), Health Check Failures (1h)
  - Timeseries: Deployment Rate by action, Deployment Duration p50/p95, HTTP Request Rate, HTTP Latency p95
  - Table: Pod Restart Counts per deployed app

### Logs (Loki + Promtail)
- Loki: single-instance, filesystem storage, 7-day retention
- Promtail: DaemonSet (one pod per node), scrapes all pods in `deployhub` namespace
- Pipeline stages: parses JSON log lines from `log_event()` → extracts `event`, `project_id`, `level` as Loki labels
- Relabels: `pod`, `app`, `namespace` from Kubernetes metadata
- This means you can filter logs in Grafana by `{project_id="abc123"}` to see all events for a specific deployment

---

## 12. CI/CD Pipeline (GitHub Actions)

### `ci.yml` — runs on every Pull Request to `main`
Four parallel jobs:
1. **Backend lint**: Python 3.11, `ruff check backend/`, verifies all imports resolve
2. **Frontend build**: Node 24, `npm install` + `npm run build`
3. **Docker build**: Builds both images with Buildx (no push), uses GitHub Actions cache
4. **Terraform validate**: `terraform fmt -check -recursive` + `terraform validate`

### `deploy.yml` — runs on push to `main`

**Job 1: Build & Push to ECR**
- Generates image tag: `sha-<7-char-git-SHA>` (e.g. `sha-a1b2c3d`)
- Resolves AWS account ID dynamically → builds ECR registry URL (portable across accounts)
- Ensures ECR repos exist (creates if missing — idempotent)
- Builds backend + frontend Docker images
- Trivy vulnerability scan (CRITICAL/HIGH, non-blocking — reports but doesn't fail the build)
- Pushes both images with SHA tag + `latest`

**Job 2a: Deploy to k3s** (default for push to `main`)
- Bootstraps Terraform remote state (S3 + DynamoDB, idempotent — safe to run repeatedly)
- Generates ephemeral RSA-4096 SSH key pair (fresh per run)
- `terraform apply` on k3s environment → outputs EC2 IP + instance ID
- Pushes ephemeral public key via EC2 Instance Connect (60-second window)
- Renders k8s manifests: substitutes image tags, EC2 IP, ECR URLs
- Waits for k3s to be ready (polls `kubectl get nodes` up to 4 minutes)
- SSHes to EC2, runs deploy script: creates ECR pull secret, `kubectl apply`, `kubectl rollout status`
- Smoke test: polls `/health` up to 15 times × 10 seconds
- Step Summary with UI/API URLs

**Job 2b: Deploy to EKS** (manual trigger only — requires full IAM permissions not available in KodeKloud)
- Same bootstrap + `terraform apply` on prod environment
- `aws eks update-kubeconfig` to configure kubectl
- Renders manifests with ALB DNS, ECR URLs, IRSA role ARN
- `kubectl apply`, rollout status, smoke test via ALB DNS

---

## 13. Security Design

- **No hardcoded credentials** anywhere in the codebase — all secrets via environment variables or Kubernetes Secrets
- **Secrets template**: `k8s_deploy/secrets.yaml` uses `REPLACE_ME_*` placeholders, rendered by `envsubst` at deploy time, never committed with real values
- **ECR authentication**: In k3s, the EC2 instance IAM role grants ECR access — no static AWS keys on the instance. In EKS, IRSA (IAM Roles for Service Accounts) lets the backend pod assume an IAM role via Kubernetes ServiceAccount — no static credentials in the pod.
- **SSH access**: Ephemeral RSA key generated per CI run, pushed via EC2 Instance Connect for 60 seconds only — no long-lived SSH keys stored anywhere
- **Terraform state**: S3 bucket with versioning, AES256 encryption, public access blocked, DynamoDB locking to prevent concurrent applies
- **Image scanning**: Trivy scans every image for CRITICAL/HIGH CVEs before push
- **RBAC**: Backend ServiceAccount has a minimal Role — can only manage pods, services, and ingresses in the `deployhub` namespace

---

## 14. Local Development

```bash
docker compose up --build
```

Three containers:
- **backend** on `:8000` — `deployment_mode=docker`, uses Docker socket directly
- **frontend** on `:3000` — Nginx serving the React build
- **mongo** on `:27017` — MongoDB 6, health-checked before backend starts

In Docker mode, the worker uses the Docker daemon directly instead of BuildKit + Kubernetes. Images are built with `docker build`, containers run with `docker run`. No AWS credentials needed.

---

## 15. Port Map

| Port | Service | Notes |
|------|---------|-------|
| 3080 | Frontend | React UI via Nginx |
| 3081 | Backend API | FastAPI direct access |
| 3090 | Prometheus | Metrics UI |
| 3091 | Grafana | Dashboards |
| 3100–3999 | User app pods | Dynamically allocated NodePorts |
| 8000 | Backend (internal) | Used by Nginx proxy |
| 27017 | MongoDB | Internal only |
| 1234 | BuildKit | Internal only (TCP) |
| 6443 | k3s API | kubectl access |

---

## 16. Common Questions and Answers

**Q: Why BuildKit instead of Docker daemon for builds?**
BuildKit runs as a separate daemon inside the cluster. It supports concurrent builds, better layer caching, and doesn't require a privileged Docker socket on every node. The backend calls `buildctl` (BuildKit CLI) over TCP to the in-cluster `buildkitd` service.

**Q: Why ECR instead of a local registry?**
ECR is managed, highly available, and integrates with IAM for authentication. A local registry would be a single point of failure and require manual credential management. ECR also has built-in vulnerability scanning.

**Q: How does the backend know which port to assign to a new app?**
It calls the Kubernetes API to list all existing Services in the namespace, collects all occupied NodePorts, then iterates through the range 3000–3999 to find the first free one.

**Q: What happens if a deployment fails?**
The worker catches the exception, calls `delete_pod()` and `delete_ingress()` to clean up, marks the project `failed` in MongoDB, stores the error message in `last_error`, and increments the `deployhub_deployment_failures_total` Prometheus counter. The user sees the error in the UI and can retry.

**Q: How does the GitHub webhook work?**
The user adds `http://<ec2-ip>:3081/api/webhooks/github/{project_id}` as a webhook in their GitHub repo settings. On every push, GitHub sends a POST request. The backend checks the `X-GitHub-Event` header — if it's `push`, it queues a redeploy. If it's `ping` (GitHub's test), it returns `pong`.

**Q: Why k3s instead of full Kubernetes?**
k3s is a CNCF-certified Kubernetes distribution that runs on a single node with ~512MB RAM overhead. It includes Traefik as the default ingress controller and the metrics server. It's ideal for demos, labs, and single-node deployments. The same manifests work on both k3s and EKS.

**Q: What is IRSA?**
IAM Roles for Service Accounts. On EKS, each Kubernetes ServiceAccount can be annotated with an IAM role ARN. When a pod uses that ServiceAccount, AWS automatically provides temporary credentials for that role via the pod's environment. This means the backend pod can push to ECR without any static AWS keys — it just calls `boto3` and the credentials are injected automatically.

**Q: How is Terraform state managed across multiple AWS accounts?**
The S3 state key is account-scoped: `environments/k3s/<account-id>/terraform.tfstate`. Each AWS account gets its own state file. This prevents stale state from a previous lab session causing errors in a new one.

**Q: Why does the backend deployment use Recreate instead of RollingUpdate?**
With a single replica and a readiness probe that checks MongoDB connectivity, RollingUpdate creates a deadlock: Kubernetes won't kill the old pod until the new one is ready, but the new pod might not become ready immediately. Recreate kills the old pod first, then starts the new one — simpler and more reliable for single-replica stateful services.

---

## 17. Technology Choices Summary

| Technology | Why chosen |
|-----------|-----------|
| FastAPI | Async Python, automatic OpenAPI docs, Pydantic validation, SSE support |
| Motor | Async MongoDB driver — non-blocking DB calls in async FastAPI |
| BuildKit | In-cluster image builds, better caching than Docker daemon, no socket exposure |
| k3s | Lightweight Kubernetes, single-node, includes Traefik + metrics server |
| ECR | Managed registry, IAM auth, scan-on-push, lifecycle policies |
| Terraform | Infrastructure as code, remote state, modular design |
| Prometheus + Grafana | Industry standard observability, pre-provisioned dashboards |
| Loki + Promtail | Log aggregation without Elasticsearch overhead, integrates with Grafana |
| GitHub Actions | CI/CD, native GitHub integration, free for public repos |
| React + Vite | Fast builds, no framework overhead, SSE support built into browser |
