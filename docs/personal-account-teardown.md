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

## Why you can mostly just run `terraform destroy`

`terraform destroy` handles almost everything — EC2, EBS, Elastic IP, security
groups, IAM roles, ECR repos (force_delete = true), the observability S3 bucket
(force_destroy = true), ECS services, EKS cluster, VPC, NAT gateways, ALB.

The **one exception** is the Terraform state bucket (`deployhub-tfstate`).
It was created by the bootstrap module separately, so the k3s/prod Terraform
has no knowledge of it and won't touch it. It also has `force_destroy = false`
as a safety guard and versioning enabled, so even `terraform destroy` in the
bootstrap module will fail unless you empty it first.

---

## Teardown — k3s environment

```bash
# One command — destroys everything Terraform created
cd terraform/environments/k3s
terraform destroy -auto-approve
```

Removes: EC2 instance, EBS volume, Elastic IP, security group, IAM role +
profile, ECR repos + all images. Takes ~2 minutes.

---

## Teardown — EKS/prod environment

```bash
cd terraform/environments/prod
terraform destroy -auto-approve
```

Removes: EKS cluster, node groups, VPC, NAT gateways, ALB, ECS Fargate tasks
(Prometheus, Mimir, Loki, Grafana), observability S3 bucket, all IAM roles.
Takes ~20 minutes.

**NAT Gateways are the silent killer** — $0.045/hr each × 2 AZs = ~$65/mo
if forgotten.

---

## Teardown — Terraform state backend (only when done forever)

Only needed when you're completely done with the project. The state bucket
must be emptied manually before deletion because versioning is enabled.

```bash
# Empty all object versions (regular delete leaves version markers behind)
aws s3 rm s3://deployhub-tfstate --recursive --region us-east-1

aws s3api delete-objects \
  --bucket deployhub-tfstate \
  --delete "$(aws s3api list-object-versions \
    --bucket deployhub-tfstate \
    --query '{Objects: Versions[].{Key:Key,VersionId:VersionId}}' \
    --output json)" \
  --region us-east-1 2>/dev/null || true

# Delete the bucket
aws s3 rb s3://deployhub-tfstate --region us-east-1

# Delete the DynamoDB lock table
aws dynamodb delete-table \
  --table-name deployhub-tfstate-lock \
  --region us-east-1
```

---

## Verify nothing is left running

Run this after any destroy to confirm no billable resources remain:

```bash
# EC2 instances
aws ec2 describe-instances \
  --filters "Name=tag:Project,Values=deployhub" \
            "Name=instance-state-name,Values=running,stopped" \
  --query 'Reservations[*].Instances[*].[InstanceId,InstanceType,State.Name]' \
  --output table --region us-east-1

# Elastic IPs (unattached ones cost money)
aws ec2 describe-addresses \
  --query 'Addresses[?AssociationId==null].[PublicIp,AllocationId]' \
  --output table --region us-east-1

# EBS volumes (unattached ones cost money)
aws ec2 describe-volumes \
  --filters "Name=status,Values=available" \
  --query 'Volumes[*].[VolumeId,Size,State]' \
  --output table --region us-east-1

# NAT Gateways (EKS only — $0.045/hr each)
aws ec2 describe-nat-gateways \
  --filter "Name=state,Values=available" \
  --query 'NatGateways[*].[NatGatewayId,State]' \
  --output table --region us-east-1
```

All tables should be empty. If anything shows up:

```bash
aws ec2 release-address --allocation-id <AllocationId> --region us-east-1
aws ec2 delete-volume --volume-id <VolumeId> --region us-east-1
aws ec2 delete-nat-gateway --nat-gateway-id <NatGatewayId> --region us-east-1
```

---

## When you come back

Push to main or trigger the pipeline manually (GitHub Actions → workflow_dispatch).
The pipeline provisions fresh infrastructure and deploys everything in ~10 minutes.
