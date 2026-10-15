# Azure Foundry deployment for Claude models (ADR-0023 extension).
#
# Deploys a Cognitive Account (AIServices) with a Claude model deployment,
# storing the endpoint + API key in Key Vault for the API/worker to consume.

resource "azurerm_cognitive_account" "foundry" {
  name                = "${var.prefix}-foundry"
  location            = var.location
  resource_group_name = var.resource_group_name
  kind                = "AIServices"
  sku_name            = var.sku_name  # S0, S1, etc.

  identity {
    type = "SystemAssigned"
  }
}

# Claude model deployment on Foundry. The deployment name is the model_id used
# by the API/worker (_llm_client via composition.py).
resource "azurerm_cognitive_deployment" "claude" {
  name                 = "claude"
  cognitive_account_id = azurerm_cognitive_account.foundry.id

  model {
    format  = "OpenAI"
    name    = var.model_name
    version = var.model_version
  }

  sku {
    name     = "Standard"
    capacity = 10
  }
}

# Store endpoint in Key Vault for the API/worker (read via SecretStore).
resource "azurerm_key_vault_secret" "foundry_endpoint" {
  name         = "foundry-endpoint"
  key_vault_id = var.vault_id
  value        = azurerm_cognitive_account.foundry.endpoint

  lifecycle {
    ignore_changes = [value]
  }
}

# Store API key in Key Vault (read via SecretStore).
# Note: The API key must be rotated post-apply via the Azure portal or `az cognitiveservices
# account keys regenerate`. During apply, we accept the placeholder; ops will set the real key.
resource "azurerm_key_vault_secret" "foundry_api_key" {
  name         = "foundry-api-key"
  key_vault_id = var.vault_id
  value = var.foundry_api_key != "" ? var.foundry_api_key : "placeholder-set-via-azure-portal"

  lifecycle {
    ignore_changes = [value]
  }
}
