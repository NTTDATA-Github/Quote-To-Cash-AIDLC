output "fqdn" {
  value = azurerm_container_app.odoo.latest_revision_fqdn
}

output "db_fqdn" {
  value = azurerm_postgresql_flexible_server.odoo.fqdn
}
