output "repository_urls" {
  description = "Map of repo name → repository URL"
  value       = { for k, v in aws_ecr_repository.repos : k => v.repository_url }
}

output "registry_id" {
  description = "AWS account ID (ECR registry ID)"
  value       = values(aws_ecr_repository.repos)[0].registry_id
}
