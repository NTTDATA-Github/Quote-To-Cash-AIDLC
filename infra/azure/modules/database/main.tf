# Postgres Flexible Server — replaces Aurora Serverless v2. No serverless-v2-exact
# equivalent on Azure; Burstable SKU + storage autoscale is the closest "pay for what you
# use" match (see ADR-0023).
#
# Network mode is fixed at creation (public vs. VNet-integrated) — unlike the
# `publicly_accessible`, this is not a flag you flip later without recreating the server.
# `public_access` here only controls the firewall rule, same lever semantics as the public_access flag in variables.tf.

resource "azurerm_postgresql_flexible_server" "main" {
  name                   = "${var.prefix}-pg"
  resource_group_name    = var.resource_group_name
  location               = var.location
  version                = "16"
  sku_name               = var.sku_name
  storage_mb             = var.storage_mb
  auto_grow_enabled      = true
  administrator_login    = var.db_username
  administrator_password = var.db_password
  zone                   = "1"

  lifecycle {
    ignore_changes = [administrator_password, zone]
  }
}

resource "azurerm_postgresql_flexible_server_database" "main" {
  name      = var.db_name
  server_id = azurerm_postgresql_flexible_server.main.id
  collation = "en_US.utf8"
  charset   = "UTF8"
}

# Debug convenience (public_access=true, see variables.tf): any IP can
# reach the server. Unsafe for real data — credentials are still required.
resource "azurerm_postgresql_flexible_server_firewall_rule" "allow_all" {
  count            = var.public_access ? 1 : 0
  name             = "allow-all"
  server_id        = azurerm_postgresql_flexible_server.main.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "255.255.255.255"
}
