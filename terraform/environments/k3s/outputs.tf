output "ec2_public_ip" {
  value = aws_instance.k3s.public_ip
}

output "ssh_command" {
  value = "ssh ubuntu@${aws_instance.k3s.public_ip}"
}

output "ecr_backend_repository_url" {
  value = module.ecr.repository_urls["deployhub-backend"]
}

output "ecr_frontend_repository_url" {
  value = module.ecr.repository_urls["deployhub-frontend"]
}

output "ecr_apps_repository_url" {
  value = module.ecr.repository_urls["deployhub-apps"]
}

output "app_url" {
  value = "http://${aws_instance.k3s.public_ip}:3080"
}

output "api_url" {
  value = "http://${aws_instance.k3s.public_ip}:3081"
}
