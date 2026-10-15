output "environment_id" {
  value = azurerm_container_app_environment.main.id
}

output "api_fqdn" {
  value = azurerm_container_app.api.latest_revision_fqdn
}
