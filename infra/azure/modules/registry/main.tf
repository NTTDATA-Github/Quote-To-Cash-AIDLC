# Azure Container Registry — replaces ECR. CI pushes commit-SHA-tagged images here.
#
# admin_enabled = true: Container Apps authenticate with the registry's admin
# username/password instead of AcrPull via managed identity. Deliberate, not the
# recommended pattern — managed identity + AcrPull is keyless and the better long-term
# answer, but granting AcrPull needs `Microsoft.Authorization/roleAssignments/write`,
# which this sandbox's signed-in principal doesn't have (see docs/deploy-azure.md).
# Reading the admin credentials is an ordinary Contributor action, so this unblocks
# every Container App's image pull without needing elevated access. Revisit once that
# access is sorted — this is a real step down in security posture (long-lived
# credentials vs. short-lived identity tokens), acceptable for this debug/staging
# environment, not for one with real customer data.
resource "azurerm_container_registry" "main" {
  # ACR names: alphanumeric only, globally unique, 5-50 chars.
  name                = "${var.prefix_alnum}acr${var.suffix}"
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = "Basic"
  admin_enabled       = true
}
