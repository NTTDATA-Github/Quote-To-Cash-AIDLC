output "cluster_endpoint" {
  value = aws_rds_cluster.aurora.endpoint
}

# SQLAlchemy URL the app expects (postgresql+psycopg2://...).
output "database_url" {
  value = format(
    "postgresql+psycopg2://%s:%s@%s:5432/%s",
    var.db_username,
    var.db_password,
    aws_rds_cluster.aurora.endpoint,
    var.db_name,
  )
  sensitive = true
}
