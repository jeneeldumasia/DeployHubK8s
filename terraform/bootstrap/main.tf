# bootstrap/main.tf
# Run this ONCE before `terraform init` in the parent directory.
# Creates the S3 bucket and DynamoDB table that store Terraform state.
#
# Usage:
#   cd terraform/bootstrap
#   terraform init
#   terraform apply
#   cd ..
#   terraform init   ← now picks up the S3 backend

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

# ── S3 bucket for state storage ───────────────────────────────────────────────
resource "aws_s3_bucket" "tfstate" {
  bucket        = "deployhub-tfstate"
  force_destroy = false   # safety: prevent accidental deletion of state

  tags = {
    Project = "deployhub"
    Purpose = "terraform-state"
  }
}

resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  versioning_configuration {
    status = "Enabled"   # keeps history of every state file — enables rollback
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"   # encrypt state at rest
    }
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket                  = aws_s3_bucket.tfstate.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ── DynamoDB table for state locking ─────────────────────────────────────────
resource "aws_dynamodb_table" "tfstate_lock" {
  name         = "deployhub-tfstate-lock"
  billing_mode = "PAY_PER_REQUEST"   # no capacity planning needed
  hash_key     = "LockID"            # required key name for Terraform locking

  attribute {
    name = "LockID"
    type = "S"
  }

  tags = {
    Project = "deployhub"
    Purpose = "terraform-state-lock"
  }
}

output "s3_bucket_name" {
  value = aws_s3_bucket.tfstate.bucket
}

output "dynamodb_table_name" {
  value = aws_dynamodb_table.tfstate_lock.name
}
