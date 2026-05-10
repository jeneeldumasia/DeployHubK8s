#!/bin/bash
# deploy-eks.sh — full EKS deployment from scratch
# Usage: ./scripts/deploy-eks.sh  (run from repo root OR scripts/ directory)
# Estimated time: ~35-45 minutes on first run

set -euo pipefail

# Always resolve paths relative to repo root, regardless of where script is called from
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Load AWS credentials
if [ -f .env.aws ]; then
  export $(grep -v '^#' .env.aws | xargs)
fi

echo "═══════════════════════════════════════════════════"
echo "  DeployHub — EKS Production Deploy"
echo "═══════════════════════════════════════════════════"

# ── Step 0: Install required tools if missing ─────────────────────────────────
echo ""
echo "▶ Step 0/7: Checking required tools..."

install_tools() {
  echo "  Installing dependencies on Ubuntu..."
  sudo apt-get update -qq
  sudo apt-get install -y -qq curl unzip git docker.io jq

  # Terraform
  if ! command -v terraform &>/dev/null; then
    echo "  Installing Terraform..."
    curl -sLo /tmp/terraform.zip https://releases.hashicorp.com/terraform/1.8.5/terraform_1.8.5_linux_amd64.zip
    unzip -q /tmp/terraform.zip -d /tmp
    sudo mv /tmp/terraform /usr/local/bin/
  fi

  # kubectl
  if ! command -v kubectl &>/dev/null; then
    echo "  Installing kubectl..."
    curl -sLo /tmp/kubectl "https://dl.k8s.io/release/$(curl -sL https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
    sudo install -o root -g root -m 0755 /tmp/kubectl /usr/local/bin/kubectl
  fi

  # Helm
  if ! command -v helm &>/dev/null; then
    echo "  Installing Helm..."
    curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash -s -- --no-sudo 2>/dev/null || \
    curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
  fi

  # AWS CLI
  if ! command -v aws &>/dev/null; then
    echo "  Installing AWS CLI..."
    curl -sLo /tmp/awscliv2.zip "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip"
    unzip -q /tmp/awscliv2.zip -d /tmp
    sudo /tmp/aws/install
  fi

  # Start Docker if not running
  if ! docker info &>/dev/null 2>&1; then
    sudo systemctl start docker 2>/dev/null || true
    sudo usermod -aG docker "$USER" 2>/dev/null || true
    # Use sudo for docker commands in this session
    DOCKER_CMD="sudo docker"
  else
    DOCKER_CMD="docker"
  fi

  echo "  ✅ All tools ready"
}

# Check if any tool is missing
if ! command -v terraform &>/dev/null || \
   ! command -v kubectl &>/dev/null || \
   ! command -v helm &>/dev/null || \
   ! command -v aws &>/dev/null; then
  install_tools
else
  echo "  ✅ All tools already installed"
  DOCKER_CMD="docker"
  if ! docker info &>/dev/null 2>&1; then
    DOCKER_CMD="sudo docker"
  fi
fi

# ── Step 1: Bootstrap remote state (idempotent) ───────────────────────────────
echo ""
echo "▶ Step 1/7: Bootstrap Terraform remote state..."
cd terraform/bootstrap
terraform init -input=false
terraform apply -auto-approve
cd ../..

# ── Step 2: Provision infrastructure ─────────────────────────────────────────
echo ""
echo "▶ Step 2/7: Provisioning VPC, EKS, ECS, ALB (~25-35 min)..."
cd terraform/environments/prod

if [ ! -f terraform.tfvars ]; then
  cp terraform.tfvars.example terraform.tfvars
  echo ""
  echo "⚠️  terraform.tfvars created from example."
  read -rsp "Enter Grafana admin password: " GRAFANA_PASS
  echo ""
  sed -i "s/CHANGE_ME_STRONG_PASSWORD/$GRAFANA_PASS/" terraform.tfvars
fi

terraform init -input=false
terraform apply -auto-approve

# Capture outputs
CLUSTER_NAME=$(terraform output -raw eks_cluster_name)
ALB_DNS=$(terraform output -raw alb_dns_name)
ECR_BACKEND=$(terraform output -raw ecr_backend_url)
ECR_FRONTEND=$(terraform output -raw ecr_frontend_url)
ECR_APPS=$(terraform output -raw ecr_apps_url)
BACKEND_SA_ROLE=$(terraform output -raw backend_sa_role_arn)
REGISTRY_ID=$(echo $ECR_BACKEND | cut -d'.' -f1)

cd ../../..

echo ""
echo "✅ Infrastructure ready"
echo "   EKS Cluster: $CLUSTER_NAME"
echo "   ALB DNS:     $ALB_DNS"

# ── Step 3: Configure kubectl ─────────────────────────────────────────────────
echo ""
echo "▶ Step 3/7: Configuring kubectl..."
aws eks update-kubeconfig --region ${AWS_DEFAULT_REGION:-us-east-1} --name $CLUSTER_NAME

# ── Step 4: Install AWS Load Balancer Controller ──────────────────────────────
echo ""
echo "▶ Step 4/7: Installing AWS Load Balancer Controller..."
ALB_ROLE=$(cd terraform/environments/prod && terraform output -raw alb_controller_role_arn)

# Install cert-manager (dependency)
kubectl apply --validate=false \
  -f https://github.com/jetstack/cert-manager/releases/download/v1.13.3/cert-manager.yaml
kubectl wait --for=condition=available deployment/cert-manager -n cert-manager --timeout=120s

# Install ALB controller via Helm
helm repo add eks https://aws.github.io/eks-charts 2>/dev/null || true
helm repo update

helm upgrade --install aws-load-balancer-controller eks/aws-load-balancer-controller \
  -n kube-system \
  --set clusterName=$CLUSTER_NAME \
  --set serviceAccount.create=true \
  --set serviceAccount.name=aws-load-balancer-controller \
  --set serviceAccount.annotations."eks\.amazonaws\.com/role-arn"=$ALB_ROLE \
  --wait --timeout=5m

echo "✅ ALB Controller installed"

# ── Step 5: Build and push images ─────────────────────────────────────────────
echo ""
echo "▶ Step 5/7: Building and pushing Docker images..."
REGISTRY_URL=$(echo $ECR_BACKEND | cut -d'/' -f1)
aws ecr get-login-password --region ${AWS_DEFAULT_REGION:-us-east-1} \
  | $DOCKER_CMD login --username AWS --password-stdin $REGISTRY_URL

IMAGE_TAG="sha-$(git rev-parse --short HEAD)"

$DOCKER_CMD build -t $ECR_BACKEND:$IMAGE_TAG -t $ECR_BACKEND:latest ./backend
$DOCKER_CMD push $ECR_BACKEND:$IMAGE_TAG
$DOCKER_CMD push $ECR_BACKEND:latest

$DOCKER_CMD build -t $ECR_FRONTEND:$IMAGE_TAG -t $ECR_FRONTEND:latest ./frontend
$DOCKER_CMD push $ECR_FRONTEND:$IMAGE_TAG
$DOCKER_CMD push $ECR_FRONTEND:latest

echo "✅ Images pushed: $IMAGE_TAG"

# ── Step 6: Apply k8s manifests ───────────────────────────────────────────────
echo ""
echo "▶ Step 6/7: Applying Kubernetes manifests..."
./scripts/apply-secrets.sh

cp -r k8s_deploy/ k8s_rendered/
sed -i "s|deployhub-backend:latest|$ECR_BACKEND:$IMAGE_TAG|g" k8s_rendered/backend.yaml
sed -i "s|deployhub-frontend:latest|$ECR_FRONTEND:$IMAGE_TAG|g" k8s_rendered/frontend.yaml
sed -i "s|\${BACKEND_SA_ROLE_ARN}|$BACKEND_SA_ROLE|g" k8s_rendered/backend.yaml

kubectl apply -f k8s_rendered/namespace.yaml
kubectl apply -f k8s_rendered/

echo "Waiting for deployments..."
kubectl rollout status deployment/backend  -n deployhub --timeout=180s
kubectl rollout status deployment/frontend -n deployhub --timeout=90s

# ── Step 7: Smoke test ────────────────────────────────────────────────────────
echo ""
echo "▶ Step 7/7: Smoke testing..."
for i in $(seq 1 15); do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://$ALB_DNS/health || echo "000")
  if [ "$STATUS" = "200" ]; then
    echo "✅ Health check passed (HTTP $STATUS)"
    break
  fi
  echo "Attempt $i/15 — HTTP $STATUS, waiting 15s for ALB to register targets..."
  sleep 15
done

# Cleanup rendered manifests
rm -rf k8s_rendered/

echo ""
echo "═══════════════════════════════════════════════════"
echo "  ✅ DeployHub is live on EKS!"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  UI:      http://$ALB_DNS"
echo "  API:     http://$ALB_DNS/api"
echo "  Grafana: http://$ALB_DNS/grafana"
echo ""
echo "  kubectl get pods -n deployhub"
echo "  kubectl get ingress -n deployhub"
