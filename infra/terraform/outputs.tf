output "alb_dns_name" {
  description = "Public DNS name of the ALB (point your domain's CNAME/ALIAS here)."
  value       = aws_lb.this.dns_name
}

output "ecr_repository_url" {
  description = "ECR repository URL for pushing images."
  value       = aws_ecr_repository.app.repository_url
}

output "rds_endpoint" {
  description = "RDS connection endpoint (host:port)."
  value       = aws_db_instance.this.endpoint
}

output "redis_endpoint" {
  description = "ElastiCache Redis primary endpoint address."
  value       = aws_elasticache_replication_group.this.primary_endpoint_address
}

output "static_bucket_name" {
  description = "S3 bucket name for static files."
  value       = aws_s3_bucket.static.bucket
}

output "private_subnet_ids" {
  description = "Private subnet IDs (used by CI for the migrate run-task)."
  value       = module.vpc.private_subnets
}

output "app_security_group_id" {
  description = "Security group ID for app tasks (used by CI for the migrate run-task)."
  value       = aws_security_group.app_sg.id
}

output "cluster_name" {
  description = "ECS cluster name (used by CI for the migrate run-task)."
  value       = aws_ecs_cluster.this.name
}
