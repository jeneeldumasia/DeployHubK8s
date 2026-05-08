variable "aws_region" {
  description = "The AWS region to deploy to"
  type        = string
  default     = "us-east-1"
}

variable "instance_type" {
  description = "The EC2 instance type for the k3s node (max medium for playground)"
  type        = string
  default     = "t3.medium"
}

variable "key_name" {
  description = "The name of the AWS Key Pair to use for SSH (optional)"
  type        = string
  default     = ""
}

variable "public_key" {
  description = "Your local SSH public key (from ~/.ssh/id_ed25519.pub)"
  type        = string
  default     = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGe6c73EnUa2dosot5obFO7xmReg/UVAueXepw+YjIbt jeneeldumasia@jeneeldumasia-surat"
}
