# User-assigned managed identities (replaces the ECS task roles) + role assignments
# (replaces the inline IAM policies) + the GitHub Actions OIDC deploy identity.
#
# Scope matches AWS exactly: api gets Key Vault read/write only (no messaging
# permissions — api never touches Service Bus directly, same as it never touched
# SQS/SNS). worker gets Key Vault read/write + Service Bus send/receive (it consumes the
# subscriptions and publishes the outbox relay). odoo gets read-only Key Vault access
# (its db-password secret only).
#
# ACR, Key Vault, AND Service Bus access are NOT granted here as role assignments —
# ACR uses admin credentials (modules/registry), Key Vault uses access policies
# (modules/secrets), and Service Bus uses a SAS connection string
# (modules/messaging's "worker" authorization rule). All three because granting a role
# assignment needs `Microsoft.Authorization/roleAssignments/write`, which this sandbox's
# signed-in principal lacks. Nothing here needs that permission anymore except the
# optional GitHub deploy identity below. These identities' `principal_id`s are still
# what Key Vault's access policies key off of — see outputs.tf.

resource "azurerm_user_assigned_identity" "api" {
  name                = "${var.prefix}-api"
  resource_group_name = var.resource_group_name
  location            = var.location
}

resource "azurerm_user_assigned_identity" "worker" {
  name                = "${var.prefix}-worker"
  resource_group_name = var.resource_group_name
  location            = var.location
}

resource "azurerm_user_assigned_identity" "odoo" {
  name                = "${var.prefix}-odoo"
  resource_group_name = var.resource_group_name
  location            = var.location
}

# --- GitHub Actions OIDC deploy identity (optional) --------------------------
locals {
  make_oidc = var.github_oidc_repo != "" ? 1 : 0
}

resource "azuread_application" "github_deploy" {
  count        = local.make_oidc
  display_name = "${var.prefix}-github-deploy"
}

resource "azuread_service_principal" "github_deploy" {
  count     = local.make_oidc
  client_id = azuread_application.github_deploy[0].client_id
}

# Covers pushes to main, the deploy workflow's push trigger. A manual workflow_dispatch
# run from a different branch needs its own federated credential (add one per branch/
# environment as needed) — Azure's federated-credential subject must match exactly,
# unlike AWS's OIDC condition which allowed any branch/workflow via "repo:<repo>:*".
resource "azuread_application_federated_identity_credential" "github_main" {
  count          = local.make_oidc
  application_id = azuread_application.github_deploy[0].id
  display_name   = "github-actions-main"
  audiences      = ["api://AzureADTokenExchange"]
  issuer         = "https://token.actions.githubusercontent.com"
  subject        = "repo:${var.github_oidc_repo}:ref:refs/heads/main"
}

# Contributor alone fails: `terraform apply` from this identity also creates the role
# assignments above, which needs User Access Administrator too.
resource "azurerm_role_assignment" "github_deploy_contributor" {
  count                = local.make_oidc
  scope                = var.resource_group_id
  role_definition_name = "Contributor"
  principal_id         = azuread_service_principal.github_deploy[0].object_id
}

resource "azurerm_role_assignment" "github_deploy_uaa" {
  count                = local.make_oidc
  scope                = var.resource_group_id
  role_definition_name = "User Access Administrator"
  principal_id         = azuread_service_principal.github_deploy[0].object_id
}
