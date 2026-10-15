output "environment_id" {
  value = azurerm_container_app_environment.main.id
}

output "environment_default_domain" {
  value = azurerm_container_app_environment.main.default_domain
}

output "api_fqdn" {
  # Stable app-level ingress hostname (no revision suffix) — unlike
  # `latest_revision_fqdn`, this never changes across deploys, so Front Door's origin
  # never needs updating (and can't hit azurerm's "inconsistent final plan" bug on
  # revision churn — see ADR-0023 / docs/deploy-azure.md).
  value = azurerm_container_app.api.ingress[0].fqdn
}
