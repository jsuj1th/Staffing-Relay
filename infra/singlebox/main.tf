# Single-box deployment: one EC2 instance runs the Django app in Docker,
# Postgres lives on managed RDS. Uses the account's DEFAULT VPC so there's no
# network to build (no NAT/ALB). Connect to the box with SSM Session Manager
# (no SSH keys, no port 22). ponytail: smallest durable setup for ~50 users.
#
# ⚠️ Authored without a local apply. Run `terraform plan` and review before apply.

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.0" }
    random = { source = "hashicorp/random", version = "~> 3.0" }
  }
}

provider "aws" {
  region = var.aws_region
}

# ---------- variables ----------
variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "db_password" {
  type      = string
  sensitive = true
}

variable "instance_type" {
  type    = string
  default = "t3.small" # ~$15/mo. t3.micro (~$7.50) works but 1GB RAM is tight.
}

variable "allowed_hosts" {
  description = "Django ALLOWED_HOSTS (comma-separated). '*' is fine while IP-only."
  type        = string
  default     = "*"
}

# ---------- default network ----------
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# ---------- security groups ----------
resource "aws_security_group" "web" {
  name        = "relay-web"
  description = "Relay web box: HTTP in, all out. SSH not needed (SSM)."
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "db" {
  name        = "relay-db"
  description = "RDS: Postgres reachable only from the web box."
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description     = "Postgres from web box"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.web.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# ---------- RDS ----------
resource "aws_db_subnet_group" "this" {
  name       = "relay-db-subnets"
  subnet_ids = data.aws_subnets.default.ids
}

resource "aws_db_instance" "this" {
  identifier             = "relay-db"
  engine                 = "postgres"
  engine_version         = "15"
  instance_class         = "db.t4g.micro"
  allocated_storage      = 20
  storage_type           = "gp3"
  db_name                = "lms_db"
  username               = "lms_user"
  password               = var.db_password
  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false
  multi_az               = false
  backup_retention_period = 7  # daily automated backups, 7-day point-in-time restore
  skip_final_snapshot    = true # set false + final_snapshot_identifier if you want a snapshot on destroy
  deletion_protection    = false
  apply_immediately      = true
}

# ---------- ECR (image registry) ----------
resource "aws_ecr_repository" "app" {
  name                 = "relay"
  image_tag_mutability = "MUTABLE"
  force_delete         = true
}

# ---------- secrets in SSM Parameter Store ----------
resource "random_password" "secret_key" {
  length  = 50
  special = false
}

resource "aws_ssm_parameter" "secret_key" {
  name  = "/relay/prod/secret_key"
  type  = "SecureString"
  value = random_password.secret_key.result
}

# Derived from the RDS endpoint — Terraform owns this one.
resource "aws_ssm_parameter" "database_url" {
  name  = "/relay/prod/database_url"
  type  = "SecureString"
  value = "postgres://lms_user:${var.db_password}@${aws_db_instance.this.address}:5432/lms_db"
}

# Telnyx values are set out-of-band (see runbook); Terraform just creates the
# params with a placeholder and then leaves the value alone.
resource "aws_ssm_parameter" "telnyx_api_key" {
  name      = "/relay/prod/telnyx_api_key"
  type      = "SecureString"
  value     = "REPLACE_ME"
  lifecycle { ignore_changes = [value] }
}

resource "aws_ssm_parameter" "telnyx_public_key" {
  name      = "/relay/prod/telnyx_public_key"
  type      = "SecureString"
  value     = "REPLACE_ME"
  lifecycle { ignore_changes = [value] }
}

resource "aws_ssm_parameter" "telnyx_phone_number" {
  name      = "/relay/prod/telnyx_phone_number"
  type      = "String"
  value     = "REPLACE_ME"
  lifecycle { ignore_changes = [value] }
}

# ---------- IAM: instance role (SSM access + ECR pull + read secrets) ----------
resource "aws_iam_role" "ec2" {
  name = "relay-ec2"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# Session Manager (browser/CLI shell into the box without SSH).
resource "aws_iam_role_policy_attachment" "ssm_core" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "app" {
  name = "relay-ec2-app"
  role = aws_iam_role.ec2.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = "*"
      },
      {
        Effect   = "Allow"
        Action   = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer", "ecr:BatchCheckLayerAvailability"]
        Resource = aws_ecr_repository.app.arn
      },
      {
        Effect   = "Allow"
        Action   = ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"]
        Resource = "arn:aws:ssm:${var.aws_region}:*:parameter/relay/prod/*"
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = "*" # default SSM KMS key
      }
    ]
  })
}

resource "aws_iam_instance_profile" "ec2" {
  name = "relay-ec2"
  role = aws_iam_role.ec2.name
}

# ---------- EC2 instance ----------
data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]
  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }
}

resource "aws_instance" "web" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.instance_type
  subnet_id              = data.aws_subnets.default.ids[0]
  vpc_security_group_ids = [aws_security_group.web.id]
  iam_instance_profile   = aws_iam_instance_profile.ec2.name

  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    aws_region    = var.aws_region
    ecr_image     = "${aws_ecr_repository.app.repository_url}:latest"
    ecr_registry  = split("/", aws_ecr_repository.app.repository_url)[0]
    allowed_hosts = var.allowed_hosts
  })

  tags = { Name = "relay-web" }
}

resource "aws_eip" "web" {
  instance = aws_instance.web.id
  domain   = "vpc"
}

# ---------- outputs ----------
output "public_ip" {
  value = aws_eip.web.public_ip
}

output "app_url" {
  value = "http://${aws_eip.web.public_ip}"
}

output "ecr_repository_url" {
  value = aws_ecr_repository.app.repository_url
}

output "rds_endpoint" {
  value = aws_db_instance.this.address
}

output "instance_id" {
  value = aws_instance.web.id
}
