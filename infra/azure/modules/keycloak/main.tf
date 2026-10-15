# Self-hosted Keycloak (ADR-0023 follow-up) — the operator-login identity provider,
# replacing the Entra External ID path. We administer our own realm, so there's no
# tenant-admin dependency at all (Authorization_RequestDenied is a non-issue — nothing
# here needs Microsoft.Authorization/roleAssignments/write or any Entra directory role).
#
# Database: a second database on the EXISTING Odoo Postgres server (var.db_server_id),
# not a third server — same "share the server, separate the database" pattern noted in
# docs/deploy-azure.md. Reuses that server's admin login/password for the connection
# string, same security posture already accepted for Odoo's own DATABASE_URL.
#
# No managed identity: both secrets below are passed as plain Container App secret
# values (not Key Vault references), so this module needs no identity + access-policy
# dance — matches modules/mocks' reasoning exactly.

resource "azurerm_postgresql_flexible_server_database" "keycloak" {
  name      = "keycloak"
  server_id = var.db_server_id
  collation = "en_US.utf8"
  charset   = "UTF8"
}

resource "random_password" "admin" {
  count   = var.admin_password == "" ? 1 : 0
  length  = 24
  special = false
}

locals {
  admin_password = var.admin_password != "" ? var.admin_password : random_password.admin[0].result
}

# Mirrors the odoo-db-password pattern (modules/secrets) — stored for ops reference,
# not read by Keycloak itself at runtime (it gets the value directly as a container
# secret below).
resource "azurerm_key_vault_secret" "admin_password" {
  name         = "keycloak-admin-password"
  key_vault_id = var.vault_id
  value        = local.admin_password

  lifecycle {
    ignore_changes = [value]
  }
}

resource "azurerm_container_app" "keycloak" {
  name                         = "${var.prefix}-keycloak"
  container_app_environment_id = var.container_app_environment_id
  resource_group_name          = var.resource_group_name
  revision_mode                = "Single"

  secret {
    name  = "acr-password"
    value = var.registry_admin_password
  }

  registry {
    server               = var.registry_login_server
    username             = var.registry_admin_username
    password_secret_name = "acr-password"
  }

  secret {
    name  = "db-password"
    value = var.db_admin_password
  }

  secret {
    name  = "admin-password"
    value = local.admin_password
  }

  template {
    min_replicas = 1
    max_replicas = 1

    container {
      name   = "keycloak"
      image  = var.keycloak_image
      cpu    = 1
      memory = "2Gi"

      env {
        name  = "KC_DB"
        value = "postgres"
      }
      env {
        name  = "KC_DB_URL"
        value = "jdbc:postgresql://${var.db_fqdn}:5432/keycloak"
      }
      env {
        name  = "KC_DB_USERNAME"
        value = var.db_admin_username
      }
      env {
        name        = "KC_DB_PASSWORD"
        secret_name = "db-password"
      }
      env {
        name  = "KC_BOOTSTRAP_ADMIN_USERNAME"
        value = "admin"
      }
      env {
        name        = "KC_BOOTSTRAP_ADMIN_PASSWORD"
        secret_name = "admin-password"
      }
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8080
    transport        = "auto"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }
}
