output "api_fqdn" {
  description = "Container App ingress hostname for the api (direct, bypassing Front Door)."
  value       = module.compute.api_fqdn
}

output "frontdoor_hostname" {
  description = "Public Front Door hostname — the app's entry point. Open https://<this>."
  value       = module.ui.frontdoor_hostname
}

output "ui_storage_account" {
  description = "Storage Account the UI build (ui/dist) is synced to ($web container)."
  value       = module.ui.storage_account_name
}

output "registry_login_server" {
  value = module.registry.login_server
}

output "postgres_fqdn" {
  value = module.database.fqdn
}

output "servicebus_namespace_fqdn" {
  value = module.messaging.namespace_fqdn
}

output "key_vault_uri" {
  value = module.secrets.vault_uri
}

output "entra_client_id" {
  value = module.identity.client_id
}

output "odoo_fqdn" {
  value = module.odoo.fqdn
}

output "odoo_db_fqdn" {
  value = module.odoo.db_fqdn
}

output "github_deploy_client_id" {
  description = "Client id for the GitHub Actions federated credential. Null if github_oidc_repo unset."
  value       = module.iam.github_deploy_client_id
}

output "container_app_environment_id" {
  value = module.compute.environment_id
}

output "keycloak_realm_url" {
  description = "Keycloak realm issuer URL — this is what EntraIdentityProvider-equivalent config points ENTRA_TENANT_ID/issuer-style settings at (see src/shared/identity/keycloak.py, not yet written)."
  value       = module.keycloak.realm_url
}

output "mock_netsuite_url" {
  description = "Base URL for ErpConnection pointed at the mock NetSuite (dev/test aid, not production)."
  value       = "https://${module.mocks.netsuite_fqdn}"
}

output "mock_reseller_url" {
  description = "Register this as a webhook endpoint URL to watch deliveries (dev/test aid, not production)."
  value       = "https://${module.mocks.reseller_fqdn}/hooks"
}

output "foundry_endpoint" {
  description = "Azure Foundry endpoint (set FOUNDRY_ENDPOINT in API/worker env)"
  value       = module.foundry.foundry_endpoint
}

output "agent_service_url" {
  description = "Agent service URL for HttpAdapterRunLauncher (set AGENT_SERVICE_URL in API/worker env). Empty when module.agent is skipped (no tokens supplied)."
  value       = try(module.agent[0].agent_service_url, "")
}
