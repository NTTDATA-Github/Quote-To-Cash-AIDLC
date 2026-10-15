output "api_identity_id" {
  value = azurerm_user_assigned_identity.api.id
}

output "api_identity_client_id" {
  value = azurerm_user_assigned_identity.api.client_id
}

output "api_identity_principal_id" {
  value = azurerm_user_assigned_identity.api.principal_id
}

output "worker_identity_id" {
  value = azurerm_user_assigned_identity.worker.id
}

output "worker_identity_client_id" {
  value = azurerm_user_assigned_identity.worker.client_id
}

output "worker_identity_principal_id" {
  value = azurerm_user_assigned_identity.worker.principal_id
}

output "odoo_identity_id" {
  value = azurerm_user_assigned_identity.odoo.id
}

output "odoo_identity_client_id" {
  value = azurerm_user_assigned_identity.odoo.client_id
}

output "odoo_identity_principal_id" {
  value = azurerm_user_assigned_identity.odoo.principal_id
}

output "github_deploy_client_id" {
  value = one(azuread_application.github_deploy[*].client_id)
}
