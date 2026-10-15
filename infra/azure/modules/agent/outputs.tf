output "agent_fqdn" {
  description = "Internal FQDN of the agent service (for API/worker to call)"
  value       = azurerm_container_app.agent.ingress[0].fqdn
}

output "agent_service_url" {
  description = "Full URL for HttpAdapterRunLauncher to call (set AGENT_SERVICE_URL in API/worker)"
  value       = "http://${azurerm_container_app.agent.ingress[0].fqdn}"
}

output "container_app_name" {
  description = "Container App name"
  value       = azurerm_container_app.agent.name
}
