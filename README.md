# DeployHub

A self-hosted PaaS that automatically builds and deploys public GitHub repositories to Kubernetes. Submit a repo URL — DeployHub clones it, detects the framework, generates a Dockerfile if needed, builds the image with BuildKit, pushes to ECR, and deploys it to k3s with a live URL. Nothing is mocked.

**Live:** `http://3.95.33.38:3080` &nbsp;|&nbsp; **API:** `http://3.95.33.38:3081` &nbsp;|&nbsp; **Grafana:** `http://3.95.33.38:3091`

---

## Architecture

```
                    jeneeldumasia.codes (Route 53) [Phase 2]
                           │
              ┌────────────▼────────────┐
              │   AWS Application LB    │
              │   (internet-facing)     │
              └──┬──────────────────┬───┘
                 │                  │
         /  /api │                  │ /grafana
  ┌──────▼───────┴──┐    ┌──────────▼────────┐
  │   EKS Cluster   │    │   ECS Fargate      │
  │   (2 AZs, HA)   │    │   (monitoring)     │
  │                 │    │                    │
  │ ns: deployhub   │    │  • Prometheus      │
  │  • frontend     │    │  • Grafana         │
  │  • backend      │◄───│  • Loki            │
  │  • buildkit     │    │  (scrapes /metrics)│
  │  • mongodb      │    └────────────────────┘
  │                 │
  │ ns: deployhub-  │
  │ apps            │
  │  • user pods    │
  └────────┬────────┘
           │ push/pull
      ┌────▼────┐
      │   ECR   │
      │(private)│
      └─────────┘

Infrastructure: Terraform modules (networking/eks/ecs-monitoring/ecr/dns-acm)
CI/CD:          GitHub Actions (build → Trivy scan → ECR push → EKS deploy)
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Infrastructure | AWS EC2, ECR, IAM — provisioned with **Terraform** (remote state on S3 + DynamoDB lock) |
| Orchestration | **k3s** (lightweight Kubernetes) |
| Build system | **BuildKit** in-cluster, images stored in **ECR** |
| Backend | **FastAPI** (Python 3.11), async deployment queue, SSE log streaming |
| Frontend | **React + Vite**, served by Nginx |
| Database | **MongoDB** (Motor async driver) |
| Observability | **Prometheus** + **Grafana** + **Loki** + **Promtail** |
| CI/CD | **GitHub Actions** — lint, Docker build, Trivy scan, ECR push, k8s deploy |
| Secrets | **Kubernetes Secrets** + **ConfigMap** (no hardcoded values in manifests) |

---

## Features

**Deployment engine**
- Clones any public GitHub repo, detects Node / Python / static project type
- Uses repo's own `Dockerfile` if present, otherwise generates one
- Auto-detects system dependencies from `requirements.txt` (Tesseract, OpenCV, etc.)
- Builds images in-cluster via BuildKit, pushes to private ECR
- Assigns a NodePort and creates a Traefik Ingress for `<slug>.jeneeldumasia.codes`
- GitHub webhook endpoint for auto-redeploy on push: `POST /api/webhooks/github/{id}`

**Reliability**
- Post-deployment health check: polls pod readiness then HTTP-probes the app
- Auto-rollback on failure — tears down pod + ingress, marks project `failed`
- Liveness + readiness probes on the backend pod itself
- HPA scales backend 1→5 replicas on CPU/memory pressure

**Observability (full triad)**
- **Metrics** — Prometheus scrapes `/metrics` every 15s; custom counters for deployments, failures, health check failures, pod restarts, HTTP latency
- **Logs** — Loki + Promtail collects all pod logs; backend emits structured JSON events parsed by Promtail pipeline
- **Dashboards** — Grafana pre-provisioned with DeployHub dashboard (deployment rate, duration p50/p95, HTTP latency p95, pod restart table) and Loki log explorer
- Alert rules for: high failure rate, health check failures, backend down, pod restart loops

**CI/CD pipeline**

`ci.yml` — runs on every PR:
- Ruff lint (backend)
- `npm run build` (frontend)
- Docker build for both images (layer-cached)
- `terraform fmt -check` + `terraform validate`

`deploy.yml` — runs on push to `main`:
- Build + tag images with short commit SHA
- Trivy vulnerability scan (CRITICAL/HIGH)
- Push to ECR
- Read live EC2 IP from Terraform remote state (S3)
- Render k8s manifests + secrets via `envsubst`
- Deploy to EC2 via SSH, `kubectl apply`
- `kubectl rollout status` gate
- Smoke test `/health` with retries
- GitHub Step Summary with all URLs

---

## Repository Structure

```
├── backend/                  FastAPI app, deployment worker, K8s/BuildKit utils
├── frontend/                 React + Vite dashboard
├── k8s_deploy/               Kubernetes manifests (works on both k3s and EKS)
│   ├── namespace.yaml
│   ├── backend.yaml          Deployment, Service, RBAC, PVC, IRSA annotation
│   ├── frontend.yaml
│   ├── mongo.yaml
│   ├── buildkitd.yaml
│   ├── ingress.yaml          ALB Ingress (EKS) / Traefik Ingress (k3s)
│   ├── monitoring.yaml       Prometheus + Grafana (k3s mode)
│   ├── logging.yaml          Loki + Promtail (k3s mode)
│   ├── hpa.yaml              HorizontalPodAutoscaler
│   └── secrets.yaml          Template — real values injected at deploy time
├── terraform/
│   ├── modules/
│   │   ├── networking/       VPC, subnets (public+private), NAT GW, security groups
│   │   ├── eks/              EKS cluster, managed node groups (multi-AZ), IRSA
│   │   ├── ecs-monitoring/   ECS Fargate — Prometheus, Grafana, Loki + EFS storage
│   │   ├── ecr/              ECR repos with lifecycle policies + scan-on-push
│   │   └── dns-acm/          ACM certificate + Route53 records [Phase 2]
│   ├── environments/
│   │   ├── prod/             EKS + ECS + ALB — full production stack
│   │   └── k3s/              Single EC2 + k3s — KodeKloud / quick demo
│   └── bootstrap/            S3 bucket + DynamoDB table for remote state
├── .github/workflows/
│   ├── ci.yml                PR validation (lint, build, terraform validate)
│   └── deploy.yml            Build → scan → push → deploy (EKS or k3s)
├── scripts/
│   ├── deploy-eks.sh         Full EKS deploy from scratch (one command)
│   └── apply-secrets.sh      Renders secrets.yaml for local/playground use
└── docs/
```

---

## Local Development

```bash
docker compose up --build
```

Opens at `http://localhost:3000`. MongoDB runs automatically via Compose.

---

## Cloud Deployment

### EKS (Production) — one command

```bash
# Requires: AWS CLI, kubectl, helm, docker, terraform
./scripts/deploy-eks.sh
```

This provisions everything from scratch: VPC → EKS → ECS → ALB → images → manifests → smoke test. Takes ~35-45 minutes on first run.

**Access via ALB DNS** (printed at end of script):
```
UI:      http://<alb-dns>
API:     http://<alb-dns>/api
Grafana: http://<alb-dns>/grafana
```

### k3s (KodeKloud / quick demo)

```bash
# 1. Provision EC2 + ECR
cd terraform/environments/k3s && terraform init && terraform apply

# 2. Apply secrets
./scripts/apply-secrets.sh

# 3. Deploy
./deploy_to_aws.sh
```

### Phase 2 — HTTPS + custom domain

Once DNS is configured, add the `dns-acm` module to `terraform/environments/prod/main.tf`:
```hcl
module "dns_acm" {
  source       = "../../modules/dns-acm"
  project      = local.project
  domain_name  = "jeneeldumasia.codes"
  alb_dns_name = aws_lb.main.dns_name
  alb_zone_id  = aws_lb.main.zone_id
  tags         = local.tags
}
```
Then update the ALB HTTP listener to redirect to HTTPS and add the certificate ARN.

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/projects` | Add a project |
| `GET` | `/api/projects` | List all projects |
| `GET` | `/api/projects/{id}` | Project detail |
| `POST` | `/api/deploy/{id}` | Queue initial deploy |
| `POST` | `/api/redeploy/{id}` | Queue redeploy |
| `POST` | `/api/stop/{id}` | Stop and remove pod |
| `DELETE` | `/api/projects/{id}` | Delete project + all resources |
| `GET` | `/api/logs/{id}` | Build + runtime logs |
| `GET` | `/api/logs/{id}/stream` | SSE live log stream |
| `GET` | `/api/projects/{id}/health` | Live pod health + restart count |
| `POST` | `/api/webhooks/github/{id}` | GitHub push webhook |
| `GET` | `/api/system` | Cluster status |
| `GET` | `/metrics` | Prometheus metrics |
| `GET` | `/health` | Liveness check |
| `GET` | `/ready` | Readiness check (MongoDB + K8s) |

---

## Pending

- [ ] Wildcard DNS (`*.jeneeldumasia.codes`) — waiting on fixed node IP
- [ ] SSL via cert-manager (manifests ready once DNS is set)
- [ ] MongoDB authentication
