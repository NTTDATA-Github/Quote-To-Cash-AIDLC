output "fqdn" {
  value = azurerm_postgresql_flexible_server.main.fqdn
}

output "database_url" {
  description = "Connection URL with the password embedded, matching the app_env convention."
  value       = "postgresql+psycopg2://${var.db_username}:${var.db_password}@${azurerm_postgresql_flexible_server.main.fqdn}:5432/${var.db_name}"
  sensitive   = true
}
