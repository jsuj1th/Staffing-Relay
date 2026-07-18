resource "aws_elasticache_subnet_group" "this" {
  name       = "${local.name_prefix}-redis-subnet-group"
  subnet_ids = module.vpc.private_subnets

  tags = local.common_tags
}

# Single-node Redis 7 replication group (no automatic failover / read replica).
# ponytail: one node is the starter ceiling; add a replica + automatic_failover_enabled
# when Celery broker availability needs to survive a node restart.
resource "aws_elasticache_replication_group" "this" {
  replication_group_id = "${local.name_prefix}-redis"
  description          = "Redis for Celery broker + result backend"

  engine         = "redis"
  engine_version = "7.0"
  node_type      = var.redis_node_type

  num_cache_clusters = 1
  port               = 6379

  subnet_group_name  = aws_elasticache_subnet_group.this.name
  security_group_ids = [aws_security_group.redis_sg.id]

  automatic_failover_enabled = false

  tags = local.common_tags
}
