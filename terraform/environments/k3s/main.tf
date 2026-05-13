terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    bucket         = "deployhub-tfstate"
    key            = "environments/k3s/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "deployhub-tfstate-lock"
    encrypt        = true
  }
}

provider "aws" {
  region = var.aws_region
}

locals {
  project = "deployhub"
  tags = {
    Project     = "deployhub"
    Environment = "k3s"
    ManagedBy   = "terraform"
  }
}

module "ecr" {
  source = "../../modules/ecr"
  repository_names = [
    "deployhub-backend",
    "deployhub-frontend",
    "deployhub-apps",
  ]
  tags = local.tags
}

data "aws_vpc" "default" {
  default = true
}

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"]
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }
}

resource "aws_key_pair" "deployhub" {
  count      = var.public_key != "" ? 1 : 0
  key_name   = "${local.project}-k3s-key"
  public_key = var.public_key
}

resource "aws_iam_role" "k3s_node" {
  name = "${local.project}-k3s-node-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "k3s_ecr" {
  role       = aws_iam_role.k3s_node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPowerUser"
}

resource "aws_iam_instance_profile" "k3s" {
  name = "${local.project}-k3s-profile"
  role = aws_iam_role.k3s_node.name
}

resource "aws_security_group" "k3s" {
  name   = "${local.project}-k3s-sg"
  vpc_id = data.aws_vpc.default.id

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 6443
    to_port     = 6443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 3000
    to_port     = 3999
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.tags, { Name = "${local.project}-k3s-sg" })
}

resource "aws_instance" "k3s" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  key_name               = var.public_key != "" ? aws_key_pair.deployhub[0].key_name : null
  iam_instance_profile   = aws_iam_instance_profile.k3s.name
  vpc_security_group_ids = [aws_security_group.k3s.id]

  root_block_device {
    volume_size = 30
    volume_type = "gp2"
  }

  user_data = <<-EOF
    #!/bin/bash
    set -e
    apt-get update && apt-get install -y curl unzip
    curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
    unzip awscliv2.zip && ./aws/install
    PUBLIC_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4)
    curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="server --tls-san $PUBLIC_IP --write-kubeconfig-mode 644 --service-node-port-range 3000-3999" sh -
    mkdir -p /home/ubuntu/.kube
    cp /etc/rancher/k3s/k3s.yaml /home/ubuntu/.kube/config
    chown -R ubuntu:ubuntu /home/ubuntu/.kube
    sed -i "s/127.0.0.1/$PUBLIC_IP/g" /home/ubuntu/.kube/config
  EOF

  tags = merge(local.tags, { Name = "${local.project}-k3s-node" })
}
