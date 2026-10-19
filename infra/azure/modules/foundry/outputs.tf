output "foundry_endpoint" {
  description = "Azure Foundry endpoint URL"
  value       = azurerm_cognitive_account.foundry.endpoint
}

output "foundry_account_name" {
  description = "Azure Foundry (Cognitive Account) name"
  value       = azurerm_cognitive_account.foundry.name
}

output "deployment_name" {
  description = "Model deployment name (use as model_id in the LLM client)"
  value       = azurerm_cognitive_deployment.model.name
}
