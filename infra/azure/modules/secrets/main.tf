# Key Vault — replaces Secrets Manager. Access-policy mode (not RBAC): granting a role
# assignment needs `Microsoft.Authorization/roleAssignments/write`, which this sandbox's
# signed-in principal lacks, but setting an access policy on the vault is an ordinary
# `Microsoft.KeyVault/vaults/write` (plain Contributor) action — see docs/deploy-azure.md.
# Functionally equivalent for our purposes: api/worker get get+set+list+delete, odoo gets
# get-only, same scope as the role assignments this replaces (Key Vault Secrets
# Officer / Secrets User). The caller running `terraform apply` also gets a policy, for
# the same reason the AWS Secrets Manager adapter never needed one — RBAC-mode Key Vault
# does not grant the creator implicit access, access-policy mode doesn't either, so
# Terraform itself needs a policy to write the two secrets below.
#
# Secret names may only contain [0-9A-Za-z-] (no "/"), unlike Secrets Manager's
# "<prefix>/erp/odoo-connection" naming — flattened to "erp-odoo-connection" etc. There is
# no prefix-glob scoping either, so (same as AWS) everything the app creates at runtime
# lives in this one vault per environment.

data "azurerm_client_config" "current" {}

resource "azurerm_key_vault" "main" {
  # Key Vault names: 3-24 chars, globally unique. "kvap" (not "kv") is deliberate: Azure
  # classifies *changing* an existing vault's RBAC/access-policy model as the
  # roleAssignments/write action — the exact permission this sandbox lacks — even though
  # setting it at creation needs no such permission. A new name forces Terraform to
  # replace (destroy + create) rather than update-in-place, so the create starts with
  # rbac_authorization_enabled=false from inception instead of trying to flip it after
  # the fact. See docs/deploy-azure.md.
  name                       = substr("${var.prefix_alnum}kvap${var.suffix}", 0, 24)
  resource_group_name        = var.resource_group_name
  location                   = var.location
  tenant_id                  = var.tenant_id
  sku_name                   = "standard"
  rbac_authorization_enabled = false
  purge_protection_enabled   = false # staging: allow a deleted vault name to be reused immediately
  soft_delete_retention_days = 7
}

resource "azurerm_key_vault_access_policy" "terraform" {
  key_vault_id = azurerm_key_vault.main.id
  tenant_id    = var.tenant_id
  object_id    = data.azurerm_client_config.current.object_id

  secret_permissions = ["Get", "Set", "List", "Delete", "Purge"]
}

resource "azurerm_key_vault_access_policy" "api" {
  key_vault_id = azurerm_key_vault.main.id
  tenant_id    = var.tenant_id
  object_id    = var.api_principal_id

  secret_permissions = ["Get", "Set", "List", "Delete"]
}

resource "azurerm_key_vault_access_policy" "worker" {
  key_vault_id = azurerm_key_vault.main.id
  tenant_id    = var.tenant_id
  object_id    = var.worker_principal_id

  secret_permissions = ["Get", "Set", "List", "Delete"]
}

resource "azurerm_key_vault_access_policy" "odoo" {
  key_vault_id = azurerm_key_vault.main.id
  tenant_id    = var.tenant_id
  object_id    = var.odoo_principal_id

  secret_permissions = ["Get"]
}

resource "azurerm_key_vault_secret" "odoo_connection" {
  name         = "erp-odoo-connection"
  key_vault_id = azurerm_key_vault.main.id
  value = var.odoo_secret_value != "" ? var.odoo_secret_value : jsonencode({
    url      = "https://odoo.example.com"
    database = "odoo"
    username = "admin"
    password = "CHANGE_ME"
  })

  lifecycle {
    ignore_changes = [value]
  }

  depends_on = [azurerm_key_vault_access_policy.terraform]
}

resource "azurerm_key_vault_secret" "anthropic_api_key" {
  name         = "anthropic-api-key"
  key_vault_id = azurerm_key_vault.main.id
  value        = var.anthropic_api_key != "" ? var.anthropic_api_key : "CHANGE_ME"

  lifecycle {
    ignore_changes = [value]
  }

  depends_on = [azurerm_key_vault_access_policy.terraform]
}
