terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# --- SSH Key Pair ---

resource "aws_key_pair" "deployhub_key" {
  count      = var.public_key != "" ? 1 : 0
  key_name   = "deployhub-key"
  public_key = var.public_key
}

# --- ECR Repositories ---

resource "aws_ecr_repository" "backend" {
  name                 = "deployhub-backend"
  image_tag_mutability = "MUTABLE"
  force_delete         = true
}

resource "aws_ecr_repository" "frontend" {
  name                 = "deployhub-frontend"
  image_tag_mutability = "MUTABLE"
  force_delete         = true
}

resource "aws_ecr_repository" "apps" {
  name                 = "deployhub-apps"
  image_tag_mutability = "MUTABLE"
  force_delete         = true
}

# --- IAM Role for EC2 to access ECR ---

data "aws_iam_policy_document" "ec2_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "deployhub_node_role" {
  name               = "deployhub-node-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume_role.json
}

resource "aws_iam_role_policy_attachment" "ecr_access" {
  role       = aws_iam_role.deployhub_node_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryPowerUser"
}

resource "aws_iam_instance_profile" "deployhub_profile" {
  name = "deployhub-node-profile"
  role = aws_iam_role.deployhub_node_role.name
}

# --- Security Group ---

data "aws_vpc" "default" {
  default = true
}

resource "aws_security_group" "deployhub_sg" {
  name        = "deployhub-sg"
  description = "Security group for DeployHub k3s node"
  vpc_id      = data.aws_vpc.default.id

  # SSH
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Frontend HTTP
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # K8s API
  ingress {
    from_port   = 6443
    to_port     = 6443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Deployed Apps Port Range (Internal)
  ingress {
    from_port   = 3000
    to_port     = 3999
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Backend API
  ingress {
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # K8s NodePort Range (for Frontend at 30080)
  ingress {
    from_port   = 30000
    to_port     = 32767
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# --- EC2 Instance (k3s Node) ---

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }
}

resource "aws_instance" "k3s_node" {
  ami                  = data.aws_ami.ubuntu.id
  instance_type        = var.instance_type
  key_name             = var.public_key != "" ? aws_key_pair.deployhub_key[0].key_name : (var.key_name != "" ? var.key_name : null)
  iam_instance_profile = aws_iam_instance_profile.deployhub_profile.name
  vpc_security_group_ids = [aws_security_group.deployhub_sg.id]

  root_block_device {
    volume_size = 30
    volume_type = "gp2"
  }

  user_data = <<-EOF
    #!/bin/bash
    set -e
    
    # Update and install dependencies
    apt-get update
    apt-get install -y curl unzip
    
    # Install AWS CLI to help with ECR authentication
    curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
    unzip awscliv2.zip
    ./aws/install
    
    # Get public IP for K8s API certs
    PUBLIC_IP=$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4)
    
    # Install k3s with exposed API and custom NodePort range
    curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="server --tls-san $PUBLIC_IP --write-kubeconfig-mode 644 --service-node-port-range 3000-3999" sh -
    
    # Make kubeconfig readable by ubuntu user
    mkdir -p /home/ubuntu/.kube
    cp /etc/rancher/k3s/k3s.yaml /home/ubuntu/.kube/config
    chown -R ubuntu:ubuntu /home/ubuntu/.kube
    sed -i "s/127.0.0.1/$PUBLIC_IP/g" /home/ubuntu/.kube/config
  EOF

  tags = {
    Name = "deployhub-k3s-node"
  }
}
