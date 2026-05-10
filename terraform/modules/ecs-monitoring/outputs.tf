output "ecs_cluster_name" {
  value = aws_ecs_cluster.monitoring.name
}

output "grafana_secret_arn" {
  value = aws_secretsmanager_secret.grafana.arn
}

output "loki_service_name" {
  value = aws_ecs_service.loki.name
}

output "prometheus_service_name" {
  value = aws_ecs_service.prometheus.name
}
