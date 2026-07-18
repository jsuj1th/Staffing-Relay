resource "aws_cloudwatch_log_group" "web" {
  name              = "/ecs/${local.name_prefix}-web"
  retention_in_days = 30
  tags              = local.common_tags
}

resource "aws_cloudwatch_log_group" "celery" {
  name              = "/ecs/${local.name_prefix}-celery"
  retention_in_days = 30
  tags              = local.common_tags
}

resource "aws_cloudwatch_log_group" "migrate" {
  name              = "/ecs/${local.name_prefix}-migrate"
  retention_in_days = 30
  tags              = local.common_tags
}

resource "aws_ecs_cluster" "this" {
  name = "hospital-lms-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  tags = local.common_tags
}

# Non-secret env vars shared by every container that runs the Django app.
locals {
  app_environment = [
    { name = "DJANGO_SETTINGS_MODULE", value = "lms.settings.production" },
    { name = "ALLOWED_HOSTS", value = var.allowed_hosts },
    { name = "AWS_S3_REGION_NAME", value = var.aws_region },
    { name = "AWS_STORAGE_BUCKET_NAME", value = aws_s3_bucket.static.bucket },
    { name = "HTTPS_ENABLED", value = tostring(local.enable_https) },
    # Over plain HTTP, POST forms (login) need the ALB origin trusted for CSRF.
    { name = "CSRF_TRUSTED_ORIGINS", value = local.enable_https ? "" : "http://${aws_lb.this.dns_name}" },
  ]

  app_secrets = [
    { name = "SECRET_KEY", valueFrom = aws_ssm_parameter.secret_key.arn },
    { name = "DATABASE_URL", valueFrom = aws_ssm_parameter.database_url.arn },
    { name = "REDIS_URL", valueFrom = aws_ssm_parameter.redis_url.arn },
    { name = "TELNYX_API_KEY", valueFrom = aws_ssm_parameter.telnyx_api_key.arn },
    { name = "TELNYX_PUBLIC_KEY", valueFrom = aws_ssm_parameter.telnyx_public_key.arn },
    { name = "TELNYX_PHONE_NUMBER", valueFrom = aws_ssm_parameter.telnyx_phone_number.arn },
  ]
}

resource "aws_ecs_task_definition" "web" {
  family                   = "hospital-lms-web"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([{
    name      = "web"
    image     = var.container_image
    essential = true
    # No command override — Dockerfile's default gunicorn entrypoint runs.
    portMappings = [{ containerPort = 8000, protocol = "tcp" }]
    environment  = local.app_environment
    secrets      = local.app_secrets
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.web.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "web"
      }
    }
  }])

  tags = local.common_tags
}

resource "aws_ecs_task_definition" "celery" {
  family                   = "hospital-lms-celery"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([{
    name        = "celery"
    image       = var.container_image
    essential   = true
    command     = ["celery", "-A", "lms", "worker", "--loglevel=info"]
    environment = local.app_environment
    secrets     = local.app_secrets
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.celery.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "celery"
      }
    }
  }])

  tags = local.common_tags
}

resource "aws_ecs_task_definition" "migrate" {
  family                   = "hospital-lms-migrate"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([{
    name        = "migrate"
    image       = var.container_image
    essential   = true
    command     = ["python", "manage.py", "migrate", "--noinput"]
    environment = local.app_environment
    secrets     = local.app_secrets
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.migrate.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "migrate"
      }
    }
  }])

  tags = local.common_tags
}

resource "aws_ecs_service" "web" {
  name            = "hospital-lms-web"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.web.arn
  desired_count   = var.web_desired_count
  launch_type     = "FARGATE"

  health_check_grace_period_seconds = 60

  network_configuration {
    subnets          = module.vpc.private_subnets
    security_groups  = [aws_security_group.app_sg.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.web.arn
    container_name   = "web"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener.https, aws_lb_listener.http]

  # CI (GitHub Actions) deploys new images by registering a new task-def
  # revision and updating the service. Let it own the running revision and
  # scale, so `terraform apply` doesn't revert to var.container_image.
  lifecycle {
    ignore_changes = [task_definition, desired_count]
  }

  tags = local.common_tags
}

resource "aws_ecs_service" "celery" {
  name            = "hospital-lms-celery"
  cluster         = aws_ecs_cluster.this.id
  task_definition = aws_ecs_task_definition.celery.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = module.vpc.private_subnets
    security_groups  = [aws_security_group.app_sg.id]
    assign_public_ip = false
  }

  lifecycle {
    ignore_changes = [task_definition, desired_count]
  }

  tags = local.common_tags
}

# hospital-lms-migrate has no service — the pipeline runs it via
# `aws ecs run-task` before each web rollout (see README.md).
