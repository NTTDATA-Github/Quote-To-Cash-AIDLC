output "fqdn" {
  value = azurerm_postgresql_flexible_server.main.fqdn
}

output "database_url" {
  description = "Same shape as AWS's DATABASE_URL — password embedded directly, matching the existing app_env convention."
  value       = "postgresql+psycopg2://${var.db_username}:${var.db_password}@${azurerm_postgresql_flexible_server.main.fqdn}:5432/${var.db_name}"
  sensitive   = true
}
