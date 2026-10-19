# Azure Foundry account + one model deployment for the mapping service's LLM
# (ADR-0023 extension). Model-agnostic: the model is whatever var.model_name says.
# Stores the endpoint + API key in Key Vault for the API/worker to consume.

resource "azurerm_cognitive_account" "foundry" {
  name                = "${var.prefix}-foundry"
  location            = var.location
  resource_group_name = var.resource_group_name
  kind                = "AIServices"
  sku_name            = var.sku_name # S0, S1, etc.

  # Required for api-key auth against the OpenAI-style /openai/deployments/... route.
  # Without it, .endpoint resolves to the generic regional host
  # (https://<region>.api.cognitive.microsoft.com/), which can't route an api-key to
  # this specific account — every call 401s with "invalid subscription key or wrong
  # API endpoint" even though the key is correct.
  custom_subdomain_name = "${var.prefix}-foundry"

  identity {
    type = "SystemAssigned"
  }
}

# Azure routes requests by deployment name, so it is named after the model and exported
# as `deployment_name`, which root locals feed to the app as MAPPING_OPENAI_MODEL.
resource "azurerm_cognitive_deployment" "model" {
  name                 = var.model_name
  cognitive_account_id = azurerm_cognitive_account.foundry.id

  model {
    format  = "OpenAI"
    name    = var.model_name
    version = var.model_version
  }

  sku {
    name     = "GlobalStandard"
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
# Retrieves the primary key from the Cognitive Account directly.
resource "azurerm_key_vault_secret" "foundry_api_key" {
  name         = "foundry-api-key"
  key_vault_id = var.vault_id
  value        = var.foundry_api_key != "" ? var.foundry_api_key : azurerm_cognitive_account.foundry.primary_access_key

  lifecycle {
    ignore_changes = [value]
  }
}
