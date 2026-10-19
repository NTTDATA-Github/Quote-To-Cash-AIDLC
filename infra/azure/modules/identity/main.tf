# Entra External ID app registration — the SPA client for Keycloak/Entra sign-in.
#
# The tenant itself is NOT created here (manual Phase 1 step, docs/deploy-azure.md — the
# provider needs a tenant to authenticate against before it can create anything in it,
# same reason it is human-run). This module only registers the app
# inside that already-existing tenant.
#
# `custom:tenant_id` (a per-user custom attribute) has no equivalent Terraform
# resource today — Entra External ID custom attributes are portal/user-flow config. See
# ADR-0023's "Revisit when". Role (OPERATOR) maps cleanly to an Entra app role instead.

resource "azuread_application" "spa" {
  count        = var.create_app ? 1 : 0
  display_name = "${var.prefix}-spa"

  single_page_application {
    redirect_uris = var.callback_urls
  }

  app_role {
    id                   = "7f1a6b1a-0000-4000-8000-000000000001"
    allowed_member_types = ["User"]
    display_name         = "Operator"
    description          = "Operator / admin users"
    value                = "OPERATOR"
    enabled              = true
  }
}

resource "azuread_service_principal" "spa" {
  count     = var.create_app ? 1 : 0
  client_id = azuread_application.spa[0].client_id
}
