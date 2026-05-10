# GitHub Actions Setup

## Required Secrets

Go to **Settings → Secrets and variables → Actions** in your GitHub repo and add:

| Secret | Value | How to get it |
|--------|-------|---------------|
| `AWS_ACCESS_KEY_ID` | Your IAM access key | AWS Console → IAM → Users → Security credentials |
| `AWS_SECRET_ACCESS_KEY` | Your IAM secret key | Same as above (only shown once on creation) |
| `EC2_SSH_PRIVATE_KEY` | Contents of your `~/.ssh/id_ed25519` private key | `cat ~/.ssh/id_ed25519` |
| `EC2_PUBLIC_IP` | `3.95.33.38` (fallback if Terraform state unavailable) | Terraform output or AWS Console |
| `GRAFANA_ADMIN_USER` | Grafana login username (e.g. `admin`) | Choose your own |
| `GRAFANA_ADMIN_PASSWORD` | Grafana login password | Choose your own — min 8 chars |

## IAM Permissions needed

The IAM user needs these policies:
- `AmazonEC2ContainerRegistryPowerUser` — push/pull ECR images
- `AmazonEC2ReadOnlyAccess` — read instance info (optional, for Terraform outputs)

Minimal inline policy if you want least-privilege:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ecr:GetAuthorizationToken",
        "ecr:BatchCheckLayerAvailability",
        "ecr:GetDownloadUrlForLayer",
        "ecr:BatchGetImage",
        "ecr:InitiateLayerUpload",
        "ecr:UploadLayerPart",
        "ecr:CompleteLayerUpload",
        "ecr:PutImage"
      ],
      "Resource": "*"
    }
  ]
}
```

## Workflow Overview

```
Push to main
    │
    ▼
┌─────────────────────────────────┐
│  build-and-push                 │
│  ├── docker build backend       │
│  ├── trivy scan backend         │
│  ├── docker push backend        │
│  ├── docker build frontend      │
│  ├── trivy scan frontend        │
│  └── docker push frontend       │
└────────────┬────────────────────┘
             │ (on main only)
             ▼
┌─────────────────────────────────┐
│  deploy                         │
│  ├── resolve EC2 IP from TF     │
│  ├── render k8s manifests       │
│  ├── scp manifests to EC2       │
│  ├── kubectl apply              │
│  ├── kubectl rollout status     │
│  └── smoke test /health         │
└─────────────────────────────────┘

Pull Request → ci.yml only (no deploy)
    ├── ruff lint (backend)
    ├── npm build (frontend)
    ├── docker build (both, no push)
    └── terraform fmt + validate
```

## Environment Protection (optional but recommended)

1. Go to **Settings → Environments → New environment**
2. Name it `production`
3. Add **Required reviewers** (yourself) to require manual approval before deploy
4. This shows up as a gate in the Actions UI — good for demos

## Trivy Severity Tuning

In `deploy.yml`, the Trivy scan steps have `exit-code: 0` (warn only).  
Change to `exit-code: 1` to **block** pushes with CRITICAL vulnerabilities:

```yaml
- name: Scan backend image with Trivy
  uses: aquasecurity/trivy-action@0.28.0
  with:
    exit-code: 1   # ← blocks the pipeline
    severity: CRITICAL
```

## Local / KodeKloud Playground Deploy

Since the playground has no GitHub Actions runner, use the helper script instead:

```bash
# From repo root (WSL or the EC2 instance itself)
chmod +x scripts/apply-secrets.sh
./scripts/apply-secrets.sh
```

The script:
1. Reads EC2 IP + ECR URL from Terraform outputs automatically
2. Prompts for Grafana password interactively (never written to disk)
3. Pipes the rendered YAML directly into `kubectl apply` — nothing touches the filesystem

After running, verify:
```bash
kubectl get secrets -n deployhub
# NAME                  TYPE     DATA
# ecr-private-key       ...      1
# grafana-credentials   Opaque   2
# backend-secrets       Opaque   2

kubectl get configmap backend-config -n deployhub
```

## How Secrets flow into pods

```
secrets.yaml (template, safe to commit)
    │
    ├── GitHub Actions: envsubst → k8s_rendered/secrets.yaml → kubectl apply
    └── Local:          apply-secrets.sh → envsubst | kubectl apply
                                │
                        Kubernetes etcd (encrypted at rest in managed K8s)
                                │
                    secretKeyRef in pod spec
                                │
                    Environment variable inside container
                    (never in image, never in logs)
```
