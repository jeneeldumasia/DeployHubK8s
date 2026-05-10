output "alb_dns_name" {
  description = "ALB DNS name — use this to access DeployHub until DNS is configured"
  value       = aws_lb.main.dns_name
}

output "alb_zone_id" {
  description = "ALB hosted zone ID — needed for Route53 alias records (Phase 2)"
  value       = aws_lb.main.zone_id
}

output "eks_cluster_name" {
  value = module.eks.cluster_name
}

output "eks_cluster_endpoint" {
  value = module.eks.cluster_endpoint
}

output "ecr_backend_url" {
  value = module.ecr.repository_urls["deployhub-backend"]
}

output "ecr_frontend_url" {
  value = module.ecr.repository_urls["deployhub-frontend"]
}

output "ecr_apps_url" {
  value = module.ecr.repository_urls["deployhub-apps"]
}

output "alb_controller_role_arn" {
  value = module.eks.alb_controller_role_arn
}

output "backend_sa_role_arn" {
  value = module.eks.backend_sa_role_arn
}

output "kubeconfig_command" {
  description = "Run this to configure kubectl"
  value       = "aws eks update-kubeconfig --region ${var.aws_region} --name ${module.eks.cluster_name}"
}

output "app_url" {
  description = "DeployHub UI"
  value       = "http://${aws_lb.main.dns_name}"
}

output "api_url" {
  description = "DeployHub API"
  value       = "http://${aws_lb.main.dns_name}/api"
}

output "grafana_url" {
  description = "Grafana dashboard"
  value       = "http://${aws_lb.main.dns_name}/grafana"
}
