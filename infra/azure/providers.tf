# azurerm v4 requires an explicit subscription_id (no more falling back to `az` CLI
# context implicitly) plus an empty features block.
provider "azurerm" {
  subscription_id = var.subscription_id
  features {}
}

# Entra app registrations (identity module + the GitHub OIDC deploy app) live in the
# External ID tenant created by hand in Phase 1 (docs/deploy-azure.md) — not the
# subscription's own AAD tenant.
provider "azuread" {
  tenant_id = var.entra_tenant_id
}
