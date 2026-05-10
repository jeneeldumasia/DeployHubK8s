terraform {
  backend "s3" {
    bucket         = "deployhub-tfstate"
    key            = "deployhub/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "deployhub-tfstate-lock"
    encrypt        = true
  }
}
