terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Remote state backend (recommended). Uncomment and fill in once the
  # bootstrap S3 bucket + DynamoDB lock table exist, then re-run
  # `terraform init -migrate-state`.
  #
  # backend "s3" {
  #   bucket         = "REPLACE_ME-tfstate-bucket"
  #   key            = "relay/prod/terraform.tfstate"
  #   region         = "us-east-1"
  #   dynamodb_table = "REPLACE_ME-tfstate-lock"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.aws_region
}
