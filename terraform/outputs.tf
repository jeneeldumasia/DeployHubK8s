output "ec2_public_ip" {
  description = "Public IP address of the EC2 instance"
  value       = aws_instance.k3s_node.public_ip
}

output "ecr_backend_repository_url" {
  description = "The URL of the backend repository"
  value       = aws_ecr_repository.backend.repository_url
}

output "ecr_frontend_repository_url" {
  description = "The URL of the frontend repository"
  value       = aws_ecr_repository.frontend.repository_url
}

output "ecr_apps_repository_url" {
  description = "The URL for deployed user applications"
  value       = aws_ecr_repository.apps.repository_url
}

output "ssh_command" {
  description = "Command to SSH into the instance"
  value       = "ssh ubuntu@${aws_instance.k3s_node.public_ip}"
}
