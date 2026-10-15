# Odoo 17 on Container Apps, with its own Postgres Flexible Server. This database is not
# the portal's — do not point Odoo at modules/database's server. Reuses the shared Key
# Vault (var.vault_id) for its db password instead of a second vault, same "one secret
# store, many secrets" shape as AWS's single Secrets Manager account.

resource "azurerm_postgresql_flexible_server" "odoo" {
  name                   = "${var.prefix}-odoo-pg"
  resource_group_name    = var.resource_group_name
  location               = var.location
  version                = "15"
  sku_name               = "B_Standard_B1ms"
  storage_mb             = 32768
  administrator_login    = "odoo"
  administrator_password = var.odoo_db_password

  lifecycle {
    # zone: Azure auto-assigns one since none is set here. Without ignoring it,
    # Terraform tries to "correct" the drift back to unset on every apply, which the API
    # rejects unless paired with a high_availability.standby_availability_zone swap —
    # the same fix already applied to modules/database/main.tf's server.
    ignore_changes = [administrator_password, zone]
  }
}

resource "azurerm_postgresql_flexible_server_database" "odoo" {
  name      = "odoo"
  server_id = azurerm_postgresql_flexible_server.odoo.id
  collation = "en_US.utf8"
  charset   = "UTF8"
}

# No VNet integration here (same scope as AWS's odoo module — Fargate task also got a
# public IP). This firewall rule is Azure's "allow trusted Azure services" exception,
# the practical equivalent of reachability from the Odoo task without standing up
# private networking. NOT a real private-networking boundary — same admitted gap as
# AWS's public_access=false (ADR-0020's "Revisit when").
resource "azurerm_postgresql_flexible_server_firewall_rule" "allow_azure_services" {
  name             = "allow-azure-services"
  server_id        = azurerm_postgresql_flexible_server.odoo.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

resource "azurerm_key_vault_secret" "db_password" {
  name         = "odoo-db-password"
  key_vault_id = var.vault_id
  value        = var.odoo_db_password

  lifecycle {
    ignore_changes = [value]
  }
}

resource "azurerm_container_app" "odoo" {
  name                         = "${var.prefix}-odoo"
  container_app_environment_id = var.container_app_environment_id
  resource_group_name          = var.resource_group_name
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [var.odoo_identity_id]
  }

  registry {
    server               = var.registry_login_server
    username             = var.registry_admin_username
    password_secret_name = "acr-password"
  }

  secret {
    name  = "acr-password"
    value = var.registry_admin_password
  }

  secret {
    name                = "db-password"
    identity            = var.odoo_identity_id
    key_vault_secret_id = azurerm_key_vault_secret.db_password.versionless_id
  }

  template {
    min_replicas = 1
    max_replicas = 1

    container {
      name   = "odoo"
      image  = var.odoo_image != "" ? var.odoo_image : "docker.io/library/odoo:17" # public placeholder for the first apply, before any image is pushed (mirrors AWS's ":bootstrap" fallback)
      cpu    = 1
      memory = "2Gi"

      env {
        name  = "HOST"
        value = azurerm_postgresql_flexible_server.odoo.fqdn
      }
      env {
        name  = "PORT"
        value = "5432"
      }
      env {
        name  = "USER"
        value = "odoo"
      }
      env {
        name        = "PASSWORD"
        secret_name = "db-password"
      }
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8069
    transport        = "auto"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }
}
