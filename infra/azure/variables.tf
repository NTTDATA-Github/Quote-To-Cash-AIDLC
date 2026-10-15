variable "subscription_id" {
  description = "Azure subscription id to deploy into."
  type        = string
}

variable "entra_tenant_id" {
  description = "Tenant id of the Entra External ID tenant created by hand in Phase 1 (docs/deploy-azure.md)."
  type        = string
}

variable "location" {
  description = "Azure region."
  type        = string
  default     = "eastus"
}

variable "environment" {
  description = "Environment name (used in resource names/tags). Single env for now, same as infra/terraform."
  type        = string
  default     = "staging"
}

variable "name_prefix" {
  description = "Short prefix for resource names."
  type        = string
  default     = "o2c"
}

variable "resource_group_name" {
  description = "Resource group the whole stack is created in."
  type        = string
  default     = "rg-o2c-staging"
}

# This subscription's management group enforces a "Standard Tags" policy: every resource
# GROUP (not every resource) must carry these 4 tags or creation is denied — discovered by
# probing `az group create` against the real policy. See docs/deploy-azure.md.
variable "std_owner" {
  type    = string
  default = "sridar.cs@global.ntt"
}

variable "std_environment" {
  type    = string
  default = "dev"
}

variable "std_project" {
  type    = string
  default = "order-to-cash-connector"
}

variable "std_billable" {
  type    = string
  default = "No"
}

# ---------------------------------------------------------------------------
# PUBLIC ACCESS — same lever and same warning as infra/terraform's public_access
# (see docs/deploy-azure.md and ADR-0020). true = Postgres Flexible Server allows
# 0.0.0.0-255.255.255.255 via firewall rule. Container Apps' external ingress is always
# public regardless of this flag — there is no private-ingress mode wired up here, same
# admitted gap AWS's public_access=false has (see ADR-0020's "Revisit when").
# ---------------------------------------------------------------------------
variable "public_access" {
  description = "Allow any IP to reach Postgres directly (debug convenience; unsafe for real data)."
  type        = bool
  default     = true
}

variable "db_name" {
  description = "Portal Postgres database name."
  type        = string
  default     = "portal"
}

variable "db_username" {
  description = "Portal Postgres admin username."
  type        = string
  default     = "portal"
}

variable "db_password" {
  description = "Portal Postgres admin password. Supply via TF_VAR_db_password (never commit it)."
  type        = string
  sensitive   = true
  default     = ""
}

variable "postgres_sku_name" {
  description = "Flexible Server SKU — Burstable is the closest match to Aurora Serverless v2's \"pay for what you use\"."
  type        = string
  default     = "B_Standard_B1ms"
}

variable "postgres_storage_mb" {
  description = "Initial storage (MB). Autoscale grows it; it never shrinks."
  type        = number
  default     = 32768
}

variable "api_image" {
  description = "Full ACR image ref for the api (repo:tag). CD sets this to the commit SHA tag."
  type        = string
  default     = ""
}

variable "worker_image" {
  description = "Full ACR image ref for the worker (repo:tag). CD sets this to the commit SHA tag."
  type        = string
  default     = ""
}

variable "api_min_replicas" {
  type    = number
  default = 1
}

variable "api_max_replicas" {
  type    = number
  default = 1
}

variable "worker_min_replicas" {
  type    = number
  default = 1
}

variable "worker_max_replicas" {
  type    = number
  default = 1
}

variable "container_cpu" {
  description = "vCPU per container (Container Apps billing unit, e.g. 0.5)."
  type        = number
  default     = 0.5
}

variable "container_memory" {
  description = "Memory per container, e.g. \"1Gi\"."
  type        = string
  default     = "1Gi"
}

variable "odoo_image" {
  description = "Full ACR image ref for Odoo (repo:tag). Empty uses a public placeholder until the first push (see modules/odoo)."
  type        = string
  default     = ""
}

variable "odoo_db_password" {
  description = "Password for the Odoo Postgres server. Supply via TF_VAR_odoo_db_password. Not the portal's db_password."
  type        = string
  sensitive   = true
  default     = ""
}

variable "odoo_secret_value" {
  description = "Initial Odoo connection secret JSON stored in Key Vault. Supply via TF_VAR_odoo_secret_value; empty = placeholder."
  type        = string
  sensitive   = true
  default     = ""
}

variable "erp_adapter_mode" {
  description = "ERP dispatch mode: 'real' (adapter registry) or 'stub' (StubErpAdapter for every ERP)."
  type        = string
  default     = "stub"
}

variable "cors_allowed_origins" {
  description = "Comma-separated UI origins allowed by the api."
  type        = string
  default     = "*"
}

variable "github_oidc_repo" {
  description = "GitHub repo (owner/name) allowed to assume the CI deploy identity via OIDC. Empty = skip creating it."
  type        = string
  default     = ""
}

variable "create_entra_app" {
  description = "Create the operator-login SPA app registration. False until the signed-in principal has Entra permission to create App Registrations (Authorization_RequestDenied otherwise). composition._resolve_identity_provider already falls back to the header stub when this is off."
  type        = bool
  default     = false
}

variable "mock_netsuite_image" {
  description = "Full ACR image ref for the mock NetSuite dev/test aid (repo:tag). Empty uses a bootstrap placeholder until the first push."
  type        = string
  default     = ""
}

variable "mock_reseller_image" {
  description = "Full ACR image ref for the mock reseller webhook receiver dev/test aid (repo:tag). Empty uses a bootstrap placeholder until the first push."
  type        = string
  default     = ""
}

variable "anthropic_api_key" {
  description = "Anthropic API key for the field-mapping proposer's direct LLM adapter (replaces Bedrock — see ADR-0023). Supply via TF_VAR_anthropic_api_key; stored in Key Vault, never in state after the first apply."
  type        = string
  sensitive   = true
  default     = ""
}
