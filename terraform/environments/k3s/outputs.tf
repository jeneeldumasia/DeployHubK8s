output "ec2_public_ip" {
  value = aws_instance.k3s.public_ip
}

output "ssh_command" {
  value = "ssh ubuntu@${aws_instance.k3s.public_ip}"
}

output "ecr_registry" {
  value = "${data.aws_caller_identity.current.account_id}.dkr.ecr.us-east-1.amazonaws.com"
}

output "ecr_apps_repository_url" {
  value = "${data.aws_caller_identity.current.account_id}.dkr.ecr.us-east-1.amazonaws.com/deployhub-apps"
}

output "app_url" {
  value = "http://${aws_instance.k3s.public_ip}:3080"
}

output "api_url" {
  value = "http://${aws_instance.k3s.public_ip}:3081"
}
