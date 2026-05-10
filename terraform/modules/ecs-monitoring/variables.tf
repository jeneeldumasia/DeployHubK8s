variable "project" {
  type = string
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
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

variable "alb_dns_name" {
  type        = string
  description = "ALB DNS name for Grafana root URL config"
}

variable "eks_metrics_endpoint" {
  type        = string
  description = "Internal endpoint for Prometheus to scrape EKS backend metrics"
  default     = ""
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

variable "grafana_secret_arn" {
  type        = string
  description = "ARN of the Secrets Manager secret for Grafana credentials (self-reference, set after creation)"
  default     = ""
}

variable "tags" {
  type    = map(string)
  default = {}
}
