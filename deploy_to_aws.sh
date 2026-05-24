#!/bin/bash
set -e

if [ -f .env.aws ]; then
    export $(grep -v '^#' .env.aws | xargs)
fi

echo "🚀 Starting Cloud Deployment to AWS..."

cd terraform
EC2_IP=$(terraform output -raw ec2_public_ip)
BACKEND_ECR=$(terraform output -raw ecr_backend_repository_url)
FRONTEND_ECR=$(terraform output -raw ecr_frontend_repository_url)
APPS_ECR=$(terraform output -raw ecr_apps_repository_url)
REGISTRY_URL=$(echo $BACKEND_ECR | cut -d'/' -f1)
cd ..

echo "✅ Target EC2: $EC2_IP"
echo "✅ Backend ECR: $BACKEND_ECR"

echo "🔑 Logging into AWS ECR..."
aws ecr get-login-password --region $AWS_DEFAULT_REGION | docker login --username AWS --password-stdin $REGISTRY_URL

echo "📦 Building and Pushing Backend..."
docker build -t deployhub-backend ./backend
docker tag deployhub-backend:latest $BACKEND_ECR:latest
docker push $BACKEND_ECR:latest

echo "📦 Building and Pushing Frontend..."
docker build -t deployhub-frontend ./frontend
docker tag deployhub-frontend:latest $FRONTEND_ECR:latest
docker push $FRONTEND_ECR:latest

echo "📝 Preparing K8s Manifests..."
mkdir -p ./k8s_rendered
cp -r ./k8s_deploy ./k8s_rendered-src
sed -i "s|deployhub-backend:latest|$BACKEND_ECR:latest|g" ./k8s_rendered-src/base/backend.yaml
sed -i "s|deployhub-frontend:latest|$FRONTEND_ECR:latest|g" ./k8s_rendered-src/base/frontend.yaml
sed -i "s|YOUR_APPS_REGISTRY|$APPS_ECR|g" ./k8s_rendered-src/base/backend.yaml
sed -i "s|YOUR_REGISTRY|$REGISTRY_URL|g" ./k8s_rendered-src/base/backend.yaml
sed -i "s|YOUR_EC2_PUBLIC_IP:30081|$EC2_IP:3081|g" ./k8s_rendered-src/base/backend.yaml
sed -i "s|YOUR_EC2_PUBLIC_IP|$EC2_IP|g" ./k8s_rendered-src/base/backend.yaml
sed -i "s|YOUR_REGISTRY/deployhub-frontend:latest|$FRONTEND_ECR:latest|g" ./k8s_rendered-src/base/frontend.yaml
sed -i "s|YOUR_EC2_PUBLIC_IP:30080|$EC2_IP:3080|g" ./k8s_rendered-src/base/frontend.yaml

echo "🚚 Uploading Manifests to EC2..."
scp -o StrictHostKeyChecking=no -r ./k8s_rendered-src ubuntu@$EC2_IP:/home/ubuntu/k8s_deploy/

echo "🎡 Applying Kustomize overlay (k3s) on EC2..."
ssh -o StrictHostKeyChecking=no ubuntu@$EC2_IP "kubectl apply -k /home/ubuntu/k8s_deploy/overlays/k3s"

echo "✨ Deployment Complete!"
echo "🔗 UI URL: http://$EC2_IP:3080"
echo "🔗 API Status: http://$EC2_IP:3081/health"
