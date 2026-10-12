output "odoo_secret_arn" {
  value = aws_secretsmanager_secret.odoo_connection.arn
}
