# Secrets Manager — ERP (Odoo) connection credentials + inbound-webhook signing keys.
# Runs on both floci and AWS. On AWS the secret uses the account's default
# aws/secretsmanager KMS key; floci ignores KMS.

resource "aws_secretsmanager_secret" "odoo_connection" {
  name        = "${var.prefix}/erp/odoo-connection"
  description = "Odoo external-API credentials for the demo connection (JSON)."
}

resource "aws_secretsmanager_secret_version" "odoo_connection" {
  secret_id = aws_secretsmanager_secret.odoo_connection.id
  secret_string = var.odoo_secret_value != "" ? var.odoo_secret_value : jsonencode({
    url      = "https://odoo.example.com"
    database = "odoo"
    username = "admin"
    password = "CHANGE_ME"
  })

  lifecycle {
    ignore_changes = [secret_string]
  }
}
