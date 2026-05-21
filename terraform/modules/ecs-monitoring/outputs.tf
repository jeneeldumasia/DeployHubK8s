output "ecs_cluster_name" {
  value = aws_ecs_cluster.monitoring.name
}

output "grafana_secret_arn" {
  value = aws_secretsmanager_secret.grafana.arn
}

output "observability_bucket" {
  value       = aws_s3_bucket.observability.bucket
  description = "S3 bucket storing Mimir metrics blocks and Loki log chunks"
}

output "mimir_service_name" {
  value = aws_ecs_service.mimir.name
}

output "loki_service_name" {
  value = aws_ecs_service.loki.name
}

output "prometheus_service_name" {
  value = aws_ecs_service.prometheus.name
}

output "grafana_service_name" {
  value = aws_ecs_service.grafana.name
}

output "service_discovery_namespace" {
  value       = aws_service_discovery_private_dns_namespace.monitoring.name
  description = "Private DNS namespace — services resolve as <name>.<namespace>"
}
