# Personal AWS Account — Teardown Checklist

> Run this every time you're done using DeployHub on your personal account
> to avoid unexpected charges. Takes ~5 minutes.

---

## What costs money if left running

| Resource | Cost if forgotten |
|---|---|
| EC2 t3.medium (k3s node) | ~$0.042/hr = ~$30/mo |
| EBS volume 30GB (attached to EC2) | ~$3/mo |
| Elastic IP (unattached) | $0.005/hr = ~$3.60/mo |
| ECR storage (images) | ~$0.10/GB/mo (small but accumulates) |
| S3 bucket (Terraform state) | negligible |
| DynamoDB table (Terraform lock) | negligible (on-demand) |

**The EC2 instance is the main one.** Everything else is cents.

---

## Teardown order

### Step 1 — Destroy the k3s environment

```bash
cd terraform/environments/k3s
terraform destroy -auto-approve
```

This removes: EC2 instance, EBS volume, Elastic IP, security group, IAM role + profile.
Takes ~2 minutes.

### Step 2 — Clear ECR images (optional but saves storage cost)

```bash
for repo in deployhub-backend deployhub-frontend deployhub-apps; do
  IMAGE_IDS=$(aws ecr list-images \
    --repository-name $repo \
    --query 'imageIds[*]' \
    --output json \
    --region us-east-1 2>/dev/null)

  if [ "$IMAGE_IDS" != "[]" ] && [ -n "$IMAGE_IDS" ]; then
    aws ecr batch-delete-image \
      --repository-name $repo \
      --image-ids "$IMAGE_IDS" \
      --region us-east-1
    echo "Cleared $repo"
  fi
done
```

### Step 3 — Destroy the Terraform state backend (last)

The S3 bucket and DynamoDB table must go last — Terraform needs them
to track the destroy operations above.

```bash
# Empty the S3 bucket first (versioning is enabled so you need --recursive
# plus a separate delete-marker pass)
aws s3 rm s3://deployhub-tfstate --recursive --region us-east-1

# Delete all object versions and delete markers
python3 -c "
import boto3
s3 = boto3.resource('s3', region_name='us-east-1')
bucket = s3.Bucket('deployhub-tfstate')
bucket.object_versions.delete()
print('All versions deleted')
"

# Now delete the bucket
aws s3 rb s3://deployhub-tfstate --region us-east-1

# Delete the DynamoDB lock table
aws dynamodb delete-table \
  --table-name deployhub-tfstate-lock \
  --region us-east-1
```

### Step 4 — Verify nothing is left running

```bash
# EC2 instances
aws ec2 describe-instances \
  --filters "Name=tag:Project,Values=deployhub" \
            "Name=instance-state-name,Values=running,stopped" \
  --query 'Reservations[*].Instances[*].[InstanceId,InstanceType,State.Name]' \
  --output table \
  --region us-east-1

# Elastic IPs (unattached ones cost money)
aws ec2 describe-addresses \
  --query 'Addresses[?AssociationId==null].[PublicIp,AllocationId]' \
  --output table \
  --region us-east-1

# EBS volumes (unattached ones cost money)
aws ec2 describe-volumes \
  --filters "Name=status,Values=available" \
  --query 'Volumes[*].[VolumeId,Size,State]' \
  --output table \
  --region us-east-1
```

All three tables should be empty. If anything shows up, delete it:

```bash
# Release a stray Elastic IP
aws ec2 release-address --allocation-id <AllocationId> --region us-east-1

# Delete a stray EBS volume
aws ec2 delete-volume --volume-id <VolumeId> --region us-east-1
```

---

## When you come back

Just push to main (or trigger the pipeline manually via GitHub Actions →
workflow_dispatch). The pipeline will:

1. Run `terraform apply` — provisions a fresh EC2 instance
2. Build and push Docker images to ECR
3. Deploy all k8s manifests including the full monitoring stack
4. Deploy the Cloudflare tunnel (if secrets are configured)

Everything is back up in ~10 minutes.

---

## EKS path (if you used the EKS environment)

EKS is significantly more expensive. Run this instead:

```bash
cd terraform/environments/prod
terraform destroy -auto-approve
```

This removes: EKS cluster, node groups, VPC, NAT gateways, ALB, ECS Fargate
tasks (Grafana/Prometheus), all IAM roles. Takes ~20 minutes.

**NAT Gateways are the silent killer on EKS** — $0.045/hr each × 2 AZs =
~$65/mo if forgotten.
