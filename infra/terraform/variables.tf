variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Project name, used for resource naming/tagging."
  type        = string
  default     = "hospital-lms"
}

variable "environment" {
  description = "Deployment environment name."
  type        = string
  default     = "prod"
}

variable "allowed_hosts" {
  description = "Value for the Django ALLOWED_HOSTS env var (comma-separated hosts)."
  type        = string
}

variable "acm_certificate_arn" {
  description = "ACM certificate ARN for the ALB HTTPS listener."
  type        = string
}

variable "db_password" {
  description = "Master password for the RDS instance."
  type        = string
  sensitive   = true
}

variable "db_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.micro"
}

variable "redis_node_type" {
  description = "ElastiCache node type."
  type        = string
  default     = "cache.t4g.micro"
}

variable "web_desired_count" {
  description = "Desired task count for the web ECS service."
  type        = number
  default     = 2
}

variable "container_image" {
  description = "ECR image URI (including tag) to run. CI overrides the running image via deploy; this is only the initial/plan-time value."
  type        = string
  default     = "PLACEHOLDER_ACCOUNT.dkr.ecr.us-east-1.amazonaws.com/hospital-lms:latest"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC."
  type        = string
  default     = "10.0.0.0/16"
}

variable "az_count" {
  description = "Number of availability zones to spread subnets across."
  type        = number
  default     = 2
}
