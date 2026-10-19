# Staging environment for the Azure stack.
# same deliberate public_access default — see ADR-0023 and docs/deploy-azure.md.

subscription_id = "8f7d862b-5995-401f-a514-7f9f1f9ebae5" # mikecarsdevtest subscription

# TEMPORARY stand-in: no dedicated Entra External ID tenant has been created yet (Phase 1
# of docs/deploy-azure.md is still a manual step). This is the regular AAD tenant behind
# the subscription above (`az account show`), reused here only so the azuread provider +
# identity module have something to authenticate against for this first apply. The SPA
# app registration created under it is NOT yet a real customer-facing External ID login —
# swap this for the real External ID tenant id once Phase 1 is done, and recreate the app
# registration there instead.
entra_tenant_id = "a2760153-5887-4d08-9fa2-78013c75bd2c"

location            = "eastus"
environment         = "staging"
resource_group_name = "rg-o2c-staging"

# PUBLIC-everything, as requested: Postgres allows any IP via firewall rule. Convenient
# for debugging, NOT safe for real data.
public_access = true

# Sizing
postgres_sku_name   = "B_Standard_B1ms"
postgres_storage_mb = 32768
api_min_replicas    = 1
api_max_replicas    = 1
worker_min_replicas = 1
worker_max_replicas = 1
container_cpu       = 0.5
container_memory    = "1Gi"

# ERP dispatch: "stub" until Odoo is up and the connection points at it.
erp_adapter_mode = "stub"

# UI origin(s). Set to the Front Door URL once known; "*" is permissive for early debugging.
cors_allowed_origins = "*"

# Left empty for now: creating this needs Entra permission to register an App
# (Authorization_RequestDenied for the current signed-in principal on this sandbox — see
# docs/deploy-azure.md). We're applying by hand right now anyway, not from CI, so this
# isn't needed yet. Set to "owner/repo" once that access is sorted and Phase 4 (CI
# rewrite) is actually being done.
github_oidc_repo = ""

# Same permission gap, same reason — see modules/identity/main.tf. The app falls back to
# the header stub (not real auth) until this is turned on; fine for this debug/staging
# environment, not for one with real operator accounts.
create_entra_app = false

# Supply these at apply time via environment, NEVER in this file:
#   export TF_VAR_db_password=...            (portal Postgres admin password)
#   export TF_VAR_odoo_db_password=...       (Odoo Postgres password, different from above)
#   export TF_VAR_odoo_secret_value='{...}'  (optional; placeholder used if unset)
#   export TF_VAR_anthropic_api_key=...      (field-mapping proposer's direct LLM adapter)
# api_image / worker_image / odoo_image are set by the deploy workflow to the ACR tag.
