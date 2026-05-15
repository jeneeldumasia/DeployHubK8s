---

# Session Summary — DeployHub CI/CD Debugging

**Date**: May 14, 2026  
**Status**: Pipeline partially working — backend rollout timeout is the current blocker

---

## What Was Accomplished This Session

### 1. GitHub Actions Workflow — Complete Overhaul

**File**: `.github/workflows/deploy.yml`

All major issues fixed:
- Replaced `aquasecurity/trivy-action@0.28.0` (didn't exist) with direct Trivy CLI install (`v0.69.3`)
- Bumped all actions to Node 24 compatible versions:
  - `actions/checkout@v4` → `@v5`
  - `aws-actions/configure-aws-credentials@v4` → `@v6`
  - `hashicorp/setup-terraform@v3` → `@v4`
  - `actions/setup-python@v5` → `@v6` (in ci.yml)
  - Node version `20` → `24` (in ci.yml)
- ECR registry URL now resolved dynamically from `aws sts get-caller-identity` — portable across any AWS account
- ECR repos created via AWS CLI (`aws ecr describe-repositories || aws ecr create-repository`) — idempotent
- Terraform remote state bootstrapped via AWS CLI (S3 + DynamoDB) — no Terraform bootstrap module needed
- DynamoDB `wait table-exists` added to prevent lock race on new accounts
- Account-scoped Terraform state key: `environments/k3s/<account-id>/terraform.tfstate` — each AWS account gets clean state
- SSH replaced with EC2 Instance Connect (ephemeral RSA-4096 key generated per run, pushed via `aws ec2-instance-connect send-ssh-public-key --instance-os-user ubuntu`)
- Deploy script written as a file and SCP'd to EC2 before execution — avoids SSH heredoc issues
- Key re-pushed immediately before long-running deploy command to reset the 60s EC2 Instance Connect window
- `ServerAliveInterval=30 ServerAliveCountMax=20` added to SSH to prevent broken pipe during long rollouts
- k3s is now the **default** deploy target (push to main → k3s). EKS is manual-only (`workflow_dispatch` with `environment: eks`)
- `mkdir -p /home/ubuntu/k8s_deploy` before scp
- `scp -r k8s_rendered/.` (trailing dot) to copy contents not the directory itself
- ECR `ecr-private-key` imagePullSecret created on cluster before `kubectl apply`
- Pod describe + logs printed on rollout timeout for diagnostics

**File**: `.github/workflows/ci.yml`
- Same action version bumps
- Node version 20 → 24

### 2. Terraform — k3s Environment

**File**: `terraform/environments/k3s/main.tf`
- Removed `module "ecr"` block entirely — ECR repos managed by AWS CLI in build-and-push job
- Added `data "aws_caller_identity" "current"` for account-aware ECR URL output
- Removed `aws_key_pair` resource — SSH via EC2 Instance Connect instead
- Added `ec2-instance-connect` to `user_data` apt install
- No `key_name` on `aws_instance`

**File**: `terraform/environments/k3s/variables.tf`
- Removed `public_key` variable (no longer needed)
- Fixed semicolon syntax → proper HCL multi-line blocks

**File**: `terraform/environments/k3s/outputs.tf`
- Added `ec2_instance_id` output (needed for `send-ssh-public-key`)
- `ecr_apps_repository_url` now derived from `aws_caller_identity` data source
- Fixed semicolon syntax → proper HCL multi-line blocks

### 3. Terraform — ECS Monitoring Module

**File**: `terraform/modules/ecs-monitoring/main.tf`
- Fixed semicolon syntax in `posix_user` and `creation_info` blocks
- Removed `retention_in_days` from CloudWatch log group (`logs:PutRetentionPolicy` denied in KodeKloud)
- Removed all 3 EFS access point resources (`elasticfilesystem:CreateAccessPoint` denied in KodeKloud)
- Removed `aws_iam_role_policy.ecs_read_secrets` inline policy (`iam:PutRolePolicy` denied in KodeKloud)
- EFS volumes now mount directly to file system root (no access points)

### 4. Terraform — Networking Module

**File**: `terraform/modules/networking/main.tf`
- Fixed invalid security group rule: `protocol="-1"` with `from_port=0, to_port=65535` → changed to `from_port=0, to_port=0`

### 5. Kubernetes Manifests

**File**: `k8s_deploy/backend.yaml`
- Added `strategy: type: Recreate` to backend Deployment — prevents rolling update deadlock on single replica with MongoDB readiness probe

### 6. Documentation

- `PROJECT_DEEP_DIVE.md` — 17-section technical deep dive covering every layer of the project
- `PROJECT_DEEP_DIVE.pdf` — PDF version generated via `generate_pdf.py` (ReportLab, dark theme)
- `generate_pdf.py` — utility script, can be deleted after use

### 7. Miscellaneous

- Added `logs/` to `.gitignore`
- Fixed all Terraform HCL semicolon syntax issues across k3s environment files

---

## Current State of the Pipeline

### What Works ✅
- Build & Push to ECR job: fully working
  - Image tag generation
  - AWS credential resolution
  - ECR repo creation (idempotent)
  - Docker build (backend + frontend)
  - Trivy scan
  - ECR push
- Terraform bootstrap (S3 + DynamoDB)
- EC2 provisioning via Terraform
- EC2 Instance Connect SSH (ephemeral key)
- k3s readiness wait
- File copy to EC2 (scp)
- ECR pull secret creation on cluster
- `kubectl apply` — all resources deploy successfully
- Namespace, PVCs, ServiceAccounts, RBAC, Deployments, Services, HPA, Ingress, Monitoring, Logging all apply cleanly

### Current Blocker ❌

**`kubectl rollout status deployment/backend -n deployhub --timeout=300s` times out**

Last known error output:
```
Waiting for deployment "backend" rollout to finish: 0 of 1 updated replicas are available...
error: timed out waiting for the condition
```

Diagnostics added (pod describe + logs printed on timeout) but the run with diagnostics hasn't completed yet at session end.

**Most likely root cause**: The backend pod's readiness probe (`GET /ready`) pings MongoDB. If MongoDB hasn't started yet when the backend pod starts, the readiness probe fails repeatedly and the pod never becomes Ready.

**Things already tried**:
- Increased timeout from 180s → 300s
- Added `strategy: type: Recreate` to avoid rolling update deadlock
- Created `ecr-private-key` imagePullSecret before apply (image pull is not the issue)

---

## What To Do Next Session

### Priority 1 — Fix Backend Rollout Timeout

**Step 1**: Check the diagnostic output from the latest run (pod describe + logs). The workflow now prints these on timeout. Look for:
- `CrashLoopBackOff` → app is crashing, check logs
- `ImagePullBackOff` → ECR auth issue
- `Pending` → scheduling issue (resources, node not ready)
- Readiness probe failures → MongoDB not ready

**Step 2**: If it's a MongoDB timing issue, add an `initContainer` to the backend deployment that waits for MongoDB:

```yaml
initContainers:
  - name: wait-for-mongo
    image: busybox
    command: ['sh', '-c', 'until nc -z mongo 27017; do echo waiting for mongo; sleep 2; done']
```

**Step 3**: If the image is pulling but the app crashes, SSH into the EC2 and check:
```bash
kubectl logs -n deployhub -l app=backend --previous
kubectl describe pod -n deployhub -l app=backend
```

**Step 4**: If readiness probe is too aggressive, relax it in `k8s_deploy/backend.yaml`:
```yaml
readinessProbe:
  initialDelaySeconds: 30  # was 10
  periodSeconds: 15        # was 10
  failureThreshold: 6      # was 3
```

### Priority 2 — After Backend Works

Once `kubectl rollout status` passes:
- Smoke test should pass automatically (polls `http://<ec2-ip>:3081/health`)
- Verify frontend is accessible at `http://<ec2-ip>:3080`
- Test the full user flow: paste a GitHub repo URL, watch it deploy
- Check Grafana at `http://<ec2-ip>:3091`

### Priority 3 — Clean Up

- Delete `generate_pdf.py` if no longer needed
- Consider adding `generate_pdf.py` to `.gitignore`
- The `SESSION_SUMMARY.md` file (this file) can be updated or deleted after next session

---

## Key Files Changed This Session

| File | Change |
|------|--------|
| `.github/workflows/deploy.yml` | Complete rewrite — portable, ephemeral SSH, dynamic ECR, k3s default |
| `.github/workflows/ci.yml` | Action version bumps, Node 24 |
| `terraform/environments/k3s/main.tf` | Removed ECR module, removed key pair, EC2 Instance Connect |
| `terraform/environments/k3s/variables.tf` | Removed public_key, fixed HCL syntax |
| `terraform/environments/k3s/outputs.tf` | Added instance_id, dynamic ECR URL, fixed HCL syntax |
| `terraform/modules/ecs-monitoring/main.tf` | Fixed syntax, removed denied IAM/EFS/CW operations |
| `terraform/modules/networking/main.tf` | Fixed invalid security group protocol rule |
| `k8s_deploy/backend.yaml` | Added Recreate strategy |
| `.gitignore` | Added `logs/` |
| `PROJECT_DEEP_DIVE.md` | New — 17-section technical deep dive |
| `PROJECT_DEEP_DIVE.pdf` | New — PDF version |
| `generate_pdf.py` | New — utility script for PDF generation |

---

## GitHub Secrets Required

| Secret | Value |
|--------|-------|
| `AWS_ACCESS_KEY_ID` | KodeKloud lab access key (changes each session) |
| `AWS_SECRET_ACCESS_KEY` | KodeKloud lab secret key (changes each session) |
| `GRAFANA_ADMIN_USER` | e.g. `admin` |
| `GRAFANA_ADMIN_PASSWORD` | Any strong password |

`EC2_SSH_PRIVATE_KEY` is **no longer needed** — SSH uses EC2 Instance Connect.

---

## Architecture Reminder

```
GitHub push to main
    │
    ▼
build-and-push job
    ├── Resolve AWS account ID → ECR registry URL
    ├── Create ECR repos if missing
    ├── docker build backend + frontend
    ├── Trivy scan (non-blocking)
    └── docker push to ECR (sha-XXXXXXX + latest tags)
    │
    ▼
deploy-k3s job
    ├── Bootstrap S3 + DynamoDB (idempotent)
    ├── Generate ephemeral RSA-4096 SSH key
    ├── terraform apply → EC2 + k3s
    ├── EC2 Instance Connect → push public key (60s window)
    ├── Render k8s manifests (envsubst + sed)
    ├── Wait for k3s ready (kubectl get nodes)
    ├── SCP deploy script to EC2
    ├── Re-push EC2 Instance Connect key
    ├── SSH → run deploy script:
    │       create ecr-private-key secret
    │       kubectl apply -f k8s_deploy/
    │       kubectl rollout status ← CURRENT BLOCKER
    └── Smoke test: curl http://<ec2-ip>:3081/health
```

---

## Useful Commands for Next Session

```bash
# Check what's happening on the EC2 after a failed run
# (SSH in manually using EC2 Instance Connect from AWS console)

kubectl get pods -n deployhub
kubectl describe pod -n deployhub -l app=backend
kubectl logs -n deployhub -l app=backend --tail=100
kubectl logs -n deployhub -l app=mongo --tail=50
kubectl get events -n deployhub --sort-by='.lastTimestamp'

# Check if images are pulling correctly
kubectl get pods -n deployhub -o jsonpath='{.items[*].status.containerStatuses[*].state}'

# Force restart backend
kubectl rollout restart deployment/backend -n deployhub
```
