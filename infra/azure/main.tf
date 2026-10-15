# Root composition for the Azure stack (ADR-0023 / docs/deploy-azure.md). Mirrors
# infra/terraform's module boundaries 1:1 so the two stacks are easy to diff while they
# run in parallel.

resource "random_string" "suffix" {
  length  = 6
  special = false
  upper   = false
}

resource "azurerm_resource_group" "main" {
  name     = var.resource_group_name
  location = var.location
  tags = {
    Project         = "order-to-cash-connector"
    Environment     = var.environment
    ManagedBy       = "terraform"
    Std_Owner       = var.std_owner
    Std_Environment = var.std_environment
    Std_Project     = var.std_project
    Std_Billable    = var.std_billable
  }
}

module "registry" {
  source              = "./modules/registry"
  prefix_alnum        = local.prefix_alnum
  suffix              = local.suffix
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
}

module "observability" {
  source              = "./modules/observability"
  prefix              = local.prefix
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
}

module "identity" {
  source     = "./modules/identity"
  prefix     = local.prefix
  create_app = var.create_entra_app
}

module "messaging" {
  source               = "./modules/messaging"
  prefix               = local.prefix
  resource_group_name  = azurerm_resource_group.main.name
  location             = azurerm_resource_group.main.location
  topic_name           = local.topic_name
  subscription_filters = local.subscription_filters
  max_delivery_count   = local.max_delivery_count
}

module "database" {
  source              = "./modules/database"
  prefix              = local.prefix
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  db_name             = var.db_name
  db_username         = var.db_username
  db_password         = var.db_password
  sku_name            = var.postgres_sku_name
  storage_mb          = var.postgres_storage_mb
  public_access       = var.public_access
}

module "iam" {
  source                  = "./modules/iam"
  prefix                  = local.prefix
  location                = var.location
  resource_group_name     = azurerm_resource_group.main.name
  resource_group_id       = azurerm_resource_group.main.id
  servicebus_namespace_id = module.messaging.namespace_id
  github_oidc_repo        = var.github_oidc_repo
}

module "secrets" {
  source              = "./modules/secrets"
  prefix_alnum        = local.prefix_alnum
  suffix              = local.suffix
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  tenant_id           = var.entra_tenant_id
  odoo_secret_value   = var.odoo_secret_value
  anthropic_api_key   = var.anthropic_api_key
  api_principal_id    = module.iam.api_identity_principal_id
  worker_principal_id = module.iam.worker_identity_principal_id
  odoo_principal_id   = module.iam.odoo_identity_principal_id
}

module "compute" {
  source                     = "./modules/compute"
  prefix                     = local.prefix
  resource_group_name        = azurerm_resource_group.main.name
  location                   = azurerm_resource_group.main.location
  log_analytics_workspace_id = module.observability.workspace_id
  registry_login_server      = module.registry.login_server
  registry_admin_username    = module.registry.admin_username
  registry_admin_password    = module.registry.admin_password
  api_identity_id            = module.iam.api_identity_id
  api_identity_client_id     = module.iam.api_identity_client_id
  worker_identity_id         = module.iam.worker_identity_id
  worker_identity_client_id  = module.iam.worker_identity_client_id
  api_image                  = var.api_image != "" ? var.api_image : "${module.registry.login_server}/o2c/api:bootstrap"
  worker_image               = var.worker_image != "" ? var.worker_image : "${module.registry.login_server}/o2c/worker:bootstrap"
  api_min_replicas           = var.api_min_replicas
  api_max_replicas           = var.api_max_replicas
  worker_min_replicas        = var.worker_min_replicas
  worker_max_replicas        = var.worker_max_replicas
  container_cpu              = var.container_cpu
  container_memory           = var.container_memory
  app_env                    = local.app_env
}

module "ui" {
  source              = "./modules/ui"
  prefix              = local.prefix
  prefix_alnum        = local.prefix_alnum
  suffix              = local.suffix
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  api_fqdn            = module.compute.api_fqdn
}

module "odoo" {
  source                       = "./modules/odoo"
  prefix                       = local.prefix
  resource_group_name          = azurerm_resource_group.main.name
  location                     = azurerm_resource_group.main.location
  container_app_environment_id = module.compute.environment_id
  registry_login_server        = module.registry.login_server
  registry_admin_username      = module.registry.admin_username
  registry_admin_password      = module.registry.admin_password
  odoo_identity_id             = module.iam.odoo_identity_id
  odoo_identity_client_id      = module.iam.odoo_identity_client_id
  odoo_image                   = var.odoo_image
  odoo_db_password             = var.odoo_db_password
  vault_id                     = module.secrets.vault_id
  vault_uri                    = module.secrets.vault_uri

  # Odoo's db-password secret write needs the Key Vault access policy that grants
  # Terraform itself write access (module.secrets' "terraform" policy) — not implied by
  # referencing vault_id/vault_uri alone, since neither output depends on that policy.
  depends_on = [module.secrets]
}

module "mocks" {
  source                       = "./modules/mocks"
  prefix                       = local.prefix
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = module.compute.environment_id
  registry_login_server        = module.registry.login_server
  registry_admin_username      = module.registry.admin_username
  registry_admin_password      = module.registry.admin_password
  mock_netsuite_image          = var.mock_netsuite_image != "" ? var.mock_netsuite_image : "${module.registry.login_server}/o2c/mock-netsuite:bootstrap"
  mock_reseller_image          = var.mock_reseller_image != "" ? var.mock_reseller_image : "${module.registry.login_server}/o2c/mock-reseller:bootstrap"
}
