# Aurora Serverless v2 PostgreSQL. One cluster + one serverless instance to start.
# publicly_accessible follows public_access.

resource "aws_db_subnet_group" "aurora" {
  name       = "${var.prefix}-aurora"
  subnet_ids = var.subnet_ids
  tags       = { Name = "${var.prefix}-aurora" }
}

resource "aws_rds_cluster" "aurora" {
  cluster_identifier     = "${var.prefix}-aurora"
  engine                 = "aurora-postgresql"
  engine_mode            = "provisioned"
  engine_version         = "16.4"
  database_name          = var.db_name
  master_username        = var.db_username
  master_password        = var.db_password
  db_subnet_group_name   = aws_db_subnet_group.aurora.name
  vpc_security_group_ids = [var.db_sg_id]

  storage_encrypted   = true
  skip_final_snapshot = true

  serverlessv2_scaling_configuration {
    min_capacity = var.min_acu
    max_capacity = var.max_acu
  }

  lifecycle {
    ignore_changes = [master_password]
  }
}

resource "aws_rds_cluster_instance" "aurora" {
  identifier           = "${var.prefix}-aurora-1"
  cluster_identifier   = aws_rds_cluster.aurora.id
  instance_class       = "db.serverless"
  engine               = aws_rds_cluster.aurora.engine
  engine_version       = aws_rds_cluster.aurora.engine_version
  db_subnet_group_name = aws_db_subnet_group.aurora.name
  publicly_accessible  = var.public_access
}
