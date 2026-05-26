variable "project" {
  type = string
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "aws_account_id" {
  type        = string
  description = "AWS account ID — used for S3 bucket naming and SSM ARNs"
}

variable "vpc_id" {
  type        = string
  description = "VPC ID for Cloud Map private DNS namespace"
}

variable "private_subnet_ids" {
  type = list(string)
}

variable "ecs_tasks_security_group_id" {
  type = string
}

variable "grafana_target_group_arn" {
  type        = string
  description = "ALB target group ARN for Grafana"
}

variable "prometheus_target_group_arn" {
  type        = string
  description = "ALB target group ARN for Prometheus"
}

variable "alb_dns_name" {
  type        = string
  description = "ALB DNS name for Grafana root URL config"
}

variable "eks_metrics_endpoint_host" {
  type        = string
  description = "Hostname/IP Prometheus uses to scrape EKS backend /metrics"
  default     = ""
}

variable "eks_metrics_endpoint_port" {
  type        = number
  description = "Port for the EKS backend /metrics scrape target"
  default     = 8000
}

variable "grafana_admin_user" {
  type      = string
  sensitive = true
  default   = "admin"
}

variable "grafana_admin_password" {
  type      = string
  sensitive = true
}

variable "tags" {
  type    = map(string)
  default = {}
}
