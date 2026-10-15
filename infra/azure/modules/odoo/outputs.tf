output "fqdn" {
  value = azurerm_container_app.odoo.ingress[0].fqdn
}

output "db_fqdn" {
  value = azurerm_postgresql_flexible_server.odoo.fqdn
}

# Exposed so other modules (keycloak) can add their own database to this same server
# instead of standing up a third Postgres server — see infra/azure/modules/keycloak.
output "db_server_id" {
  value = azurerm_postgresql_flexible_server.odoo.id
}

output "db_admin_username" {
  value = azurerm_postgresql_flexible_server.odoo.administrator_login
}
