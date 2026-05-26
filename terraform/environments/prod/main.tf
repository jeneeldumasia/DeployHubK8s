terraform {
  required_version = ">= 1.8"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }

  backend "s3" {
    bucket         = "deployhub-tfstate"
    key            = "environments/prod/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "deployhub-tfstate-lock"
    encrypt        = true
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_caller_identity" "current" {}

locals {
  project = "deployhub"
  tags = {
    Project     = "deployhub"
    Environment = "prod"
    ManagedBy   = "terraform"
  }
}

# ── Networking ────────────────────────────────────────────────────────────────
module "networking" {
  source             = "../../modules/networking"
  project            = local.project
  vpc_cidr           = var.vpc_cidr
  availability_zones = var.availability_zones
  tags               = local.tags
}



# ── EKS ───────────────────────────────────────────────────────────────────────
module "eks" {
  source                 = "../../modules/eks"
  project                = local.project
  aws_region             = var.aws_region
  kubernetes_version     = var.kubernetes_version
  public_subnet_ids      = module.networking.public_subnet_ids
  private_subnet_ids     = module.networking.private_subnet_ids
  node_security_group_id = module.networking.eks_nodes_security_group_id
  availability_zones     = var.availability_zones
  node_instance_type     = var.node_instance_type
  node_desired_size      = var.node_desired_size
  node_min_size          = var.node_min_size
  node_max_size          = var.node_max_size
  tags                   = local.tags
}

# ── ALB to EKS Nodes Access ───────────────────────────────────────────────────
# EKS Managed Node Groups don't automatically attach additional security groups.
# They only use the cluster's primary security group. We must explicitly allow
# the ALB to talk to this primary security group so health checks reach the Pod IPs.
resource "aws_security_group_rule" "alb_to_eks_nodes_primary" {
  type                     = "ingress"
  from_port                = 0
  to_port                  = 65535
  protocol                 = "tcp"
  source_security_group_id = module.networking.alb_security_group_id
  security_group_id        = module.eks.cluster_security_group_id
  description              = "Allow ALB to talk to EKS worker node Pod IPs"
}

# ── Application Load Balancer ─────────────────────────────────────────────────
resource "aws_lb" "main" {
  name               = "${local.project}-alb"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [module.networking.alb_security_group_id]
  subnets            = module.networking.public_subnet_ids

  enable_deletion_protection = false   # allow destroy on playground
  enable_http2               = true

  access_logs {
    bucket  = ""
    enabled = false
  }

  tags = merge(local.tags, { Name = "${local.project}-alb" })
}

# ── ALB Target Groups ─────────────────────────────────────────────────────────

# Frontend (React/Nginx on EKS)
resource "aws_lb_target_group" "frontend" {
  name        = "${local.project}-frontend-tg"
  port        = 8080   # matches Nginx containerPort and Service port
  protocol    = "HTTP"
  vpc_id      = module.networking.vpc_id
  target_type = "ip"   # required for EKS pods (awsvpc mode)

  health_check {
    path                = "/"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 30
    timeout             = 5
    matcher             = "200-399"
  }

  tags = local.tags
}

# Backend API (FastAPI on EKS)
resource "aws_lb_target_group" "backend" {
  name        = "${local.project}-backend-tg"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = module.networking.vpc_id
  target_type = "ip"

  health_check {
    path                = "/health"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 30
    timeout             = 5
    matcher             = "200"
  }

  tags = local.tags
}

# Grafana (ECS Fargate)
resource "aws_lb_target_group" "grafana" {
  name        = "${local.project}-grafana-tg"
  port        = 3000
  protocol    = "HTTP"
  vpc_id      = module.networking.vpc_id
  target_type = "ip"

  health_check {
    path                = "/grafana/api/health"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 30
    timeout             = 5
    matcher             = "200"
  }

  tags = local.tags
}

resource "aws_lb_target_group" "prometheus" {
  name        = "${local.project}-prometheus-tg"
  port        = 9090
  protocol    = "HTTP"
  vpc_id      = module.networking.vpc_id
  target_type = "ip"

  health_check {
    path                = "/-/healthy"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 30
    timeout             = 5
    matcher             = "200"
  }

  tags = local.tags
}

resource "aws_lb_target_group" "ingress_nginx" {
  name        = "${local.project}-ingress-nginx-tg"
  port        = 80
  protocol    = "HTTP"
  vpc_id      = module.networking.vpc_id
  target_type = "ip"

  health_check {
    path                = "/healthz"
    healthy_threshold   = 2
    unhealthy_threshold = 5
    interval            = 15
    timeout             = 5
    matcher             = "200"
    port                = "10254"
  }

  tags = local.tags
}

# ── ACM Certificate ─────────────────────────────────────────────────────────────
resource "aws_acm_certificate" "cert" {
  domain_name               = "*.jeneeldumasia.codes"
  subject_alternative_names = ["jeneeldumasia.codes"]
  validation_method         = "DNS"

  lifecycle {
    create_before_destroy = true
  }

  tags = local.tags
}

# ── ALB Listeners ─────────────────────────────────────────────────────────────

# HTTP listener redirects to HTTPS
resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"

    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }

  tags = local.tags
}

# HTTPS listener
resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-2016-08"
  certificate_arn   = aws_acm_certificate.cert.arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.frontend.arn
  }

  tags = local.tags
}

# Routing rules on HTTP listener
resource "aws_lb_listener_rule" "api" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.backend.arn
  }

  condition {
    path_pattern { values = ["/api/*", "/health", "/ready", "/metrics"] }
  }
}

resource "aws_lb_listener_rule" "grafana" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 20

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.grafana.arn
  }

  condition {
    path_pattern { values = ["/grafana", "/grafana/*"] }
  }
}

resource "aws_lb_listener_rule" "prometheus" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 25

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.prometheus.arn
  }

  condition {
    path_pattern { values = ["/prometheus", "/prometheus/*"] }
  }
}

resource "aws_lb_listener_rule" "ingress_nginx" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 30

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.ingress_nginx.arn
  }

  condition {
    host_header { values = ["*.jeneeldumasia.codes"] }
  }
}

# ── ECS Monitoring Stack ──────────────────────────────────────────────────────
module "ecs_monitoring" {
  source                      = "../../modules/ecs-monitoring"
  project                     = local.project
  aws_region                  = var.aws_region
  aws_account_id              = data.aws_caller_identity.current.account_id
  vpc_id                      = module.networking.vpc_id
  private_subnet_ids          = module.networking.private_subnet_ids
  ecs_tasks_security_group_id = module.networking.ecs_tasks_security_group_id
  grafana_target_group_arn    = aws_lb_target_group.grafana.arn
  prometheus_target_group_arn = aws_lb_target_group.prometheus.arn
  alb_dns_name                = aws_lb.main.dns_name
  # Prometheus scrapes the EKS backend via the ALB internal DNS
  eks_metrics_endpoint_host   = aws_lb.main.dns_name
  eks_metrics_endpoint_port   = 80
  grafana_admin_user          = var.grafana_admin_user
  grafana_admin_password      = var.grafana_admin_password
  tags                        = local.tags
}

# ── SSH Key Pair (for debugging nodes if needed) ──────────────────────────────
resource "aws_key_pair" "deployhub" {
  count      = var.public_key != "" ? 1 : 0
  key_name   = "${local.project}-key"
  public_key = var.public_key
}
