output "foundry_endpoint" {
  description = "Azure Foundry endpoint URL for Claude API calls"
  value       = azurerm_cognitive_account.foundry.endpoint
}

output "foundry_account_name" {
  description = "Azure Foundry (Cognitive Account) name"
  value       = azurerm_cognitive_account.foundry.name
}

output "deployment_name" {
  description = "Claude model deployment name (use as model_id in client)"
  value       = azurerm_cognitive_deployment.claude.name
}
