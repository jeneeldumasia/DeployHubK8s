output "ec2_instance_id" {
  value = aws_instance.k3s.id
}

# Use the Elastic IP — this stays the same across instance replacements
# so DNS only needs to be pointed once.
output "ec2_public_ip" {
  value = aws_eip.k3s.public_ip
}

output "ssh_command" {
  value = "ssh ubuntu@${aws_eip.k3s.public_ip}"
}

output "ecr_registry" {
  value = "${data.aws_caller_identity.current.account_id}.dkr.ecr.us-east-1.amazonaws.com"
}

output "ecr_apps_repository_url" {
  value = "${data.aws_caller_identity.current.account_id}.dkr.ecr.us-east-1.amazonaws.com/deployhub-apps"
}

output "app_url" {
  value = "https://${aws_eip.k3s.public_ip}:3080"
}

output "api_url" {
  value = "https://${aws_eip.k3s.public_ip}:3081"
}

output "elastic_ip" {
  value       = aws_eip.k3s.public_ip
  description = "Point your DNS A records at this IP — it never changes between sessions."
}
