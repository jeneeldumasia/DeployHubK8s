#!/bin/bash
# apply-secrets.sh — renders secrets.yaml with real values and applies to cluster
# Usage: ./scripts/apply-secrets.sh  (run from repo root OR scripts/ directory)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

if [ -f .env.aws ]; then
  export $(grep -v '^#' .env.aws | xargs)
fi

# ── Detect environment and resolve public endpoint ───────────────────────────
PUBLIC_URL=""

# Try EKS prod environment first
if command -v terraform &>/dev/null && [ -d terraform/environments/prod ]; then
  PUBLIC_URL=$(cd terraform/environments/prod && terraform output -raw alb_dns_name 2>/dev/null || true)
  if [ -n "$PUBLIC_URL" ]; then
    PUBLIC_URL="http://$PUBLIC_URL"
    echo "Detected EKS environment. Public URL: $PUBLIC_URL"
  fi
fi

# Fall back to k3s environment
if [ -z "$PUBLIC_URL" ] && command -v terraform &>/dev/null && [ -d terraform/environments/k3s ]; then
  EC2_IP=$(cd terraform/environments/k3s && terraform output -raw ec2_public_ip 2>/dev/null || true)
  if [ -n "$EC2_IP" ]; then
    PUBLIC_URL="http://$EC2_IP:3081"
    echo "Detected k3s environment. Public URL: $PUBLIC_URL"
  fi
fi

# Manual fallback
if [ -z "$PUBLIC_URL" ]; then
  read -rp "Enter public URL (e.g. http://1.2.3.4:3081 or http://alb-dns): " PUBLIC_URL
fi

# ── Resolve ECR apps registry URL ────────────────────────────────────────────
APPS_ECR=""
if command -v terraform &>/dev/null && [ -d terraform/environments/prod ]; then
  APPS_ECR=$(cd terraform/environments/prod && terraform output -raw ecr_apps_url 2>/dev/null || true)
fi
if [ -z "$APPS_ECR" ] && command -v terraform &>/dev/null && [ -d terraform/environments/k3s ]; then
  APPS_ECR=$(cd terraform/environments/k3s && terraform output -raw ecr_apps_repository_url 2>/dev/null || true)
fi
if [ -z "$APPS_ECR" ]; then
  read -rp "Enter ECR apps registry URL: " APPS_ECR
fi

# ── Prompt for secrets ────────────────────────────────────────────────────────
read -rp "Grafana admin username [admin]: " GRAFANA_USER
GRAFANA_USER="${GRAFANA_USER:-admin}"

read -rsp "Grafana admin password: " GRAFANA_PASSWORD
echo
if [ -z "$GRAFANA_PASSWORD" ]; then
  echo "❌ Grafana password cannot be empty"
  exit 1
fi

# ── Render and apply — values never touch disk ────────────────────────────────
echo ""
echo "Applying Secrets and ConfigMap to cluster..."

REPLACE_ME_GRAFANA_USER="$GRAFANA_USER" \
REPLACE_ME_GRAFANA_PASSWORD="$GRAFANA_PASSWORD" \
REPLACE_ME_MONGO_URI="mongodb://mongo:27017/deployhub" \
REPLACE_ME_REGISTRY_ADDR="$APPS_ECR" \
REPLACE_ME_PUBLIC_BASE_URL="$PUBLIC_URL" \
  envsubst < k8s_deploy/secrets.yaml | kubectl apply -f -

echo ""
echo "✅ Secrets applied."
echo "   kubectl get secrets -n deployhub"
echo "   kubectl get configmap backend-config -n deployhub"
