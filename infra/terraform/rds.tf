resource "aws_db_subnet_group" "this" {
  name       = "${local.name_prefix}-db-subnet-group"
  subnet_ids = module.vpc.private_subnets

  tags = local.common_tags
}

resource "aws_db_instance" "this" {
  identifier     = "${local.name_prefix}-db"
  engine         = "postgres"
  engine_version = "15"

  instance_class    = var.db_instance_class
  allocated_storage = 20
  storage_type      = "gp3"
  storage_encrypted = true

  db_name  = "lms_db"
  username = "lms_user"
  password = var.db_password

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.db_sg.id]
  multi_az               = false

  backup_retention_period = 7

  # ponytail: starter-grade, no final snapshot on destroy. Set to false and
  # add final_snapshot_identifier before this ever holds real prod data.
  skip_final_snapshot = true

  tags = local.common_tags
}
