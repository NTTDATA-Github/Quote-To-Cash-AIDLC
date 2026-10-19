# Storage static website + Front Door Standard. 
#
# Front Door's two origin groups + path-based routes reproduce the
# `ordered_cache_behavior` trick for routing `/graphql*` to the api as a second,
# same-origin destination — same reason: the UI is HTTPS-only and can't call an
# HTTP(-only) origin directly without mixed-content errors, and same-origin avoids CORS.
#
# SPA fallback is narrower here: Storage's `error_404_document` only applies
# to the storage origin (unknown React Router paths), not distribution-wide — unlike
# the known gap (see docs/deploy-azure.md) where a real API 403/404 also got rewritten
# to index.html, because `/graphql*` here is routed to an entirely different origin group
# that this fallback never touches.

resource "azurerm_storage_account" "ui" {
  # Storage Account names: lowercase alphanumeric only, 3-24 chars, globally unique.
  name                     = substr("${var.prefix_alnum}ui${var.suffix}", 0, 24)
  resource_group_name      = var.resource_group_name
  location                 = var.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  account_kind             = "StorageV2"
  min_tls_version          = "TLS1_2"
}

# Separate resource, not an inline `static_website` block — azurerm deprecated the
# inline block in favor of this in v4, ahead of removing it in v5.
resource "azurerm_storage_account_static_website" "ui" {
  storage_account_id = azurerm_storage_account.ui.id
  index_document     = "index.html"
  error_404_document = "index.html"
}

resource "azurerm_cdn_frontdoor_profile" "ui" {
  name                = "${var.prefix}-ui"
  resource_group_name = var.resource_group_name
  sku_name            = "Standard_AzureFrontDoor"
}

resource "azurerm_cdn_frontdoor_endpoint" "ui" {
  name                     = "${var.prefix}-ui"
  cdn_frontdoor_profile_id = azurerm_cdn_frontdoor_profile.ui.id
}

# --- UI (storage static website) origin -------------------------------------
resource "azurerm_cdn_frontdoor_origin_group" "ui" {
  name                     = "ui-storage"
  cdn_frontdoor_profile_id = azurerm_cdn_frontdoor_profile.ui.id

  load_balancing {}

  health_probe {
    path                = "/"
    protocol            = "Https"
    request_type        = "HEAD"
    interval_in_seconds = 100
  }
}

resource "azurerm_cdn_frontdoor_origin" "ui" {
  name                           = "ui-storage"
  cdn_frontdoor_origin_group_id  = azurerm_cdn_frontdoor_origin_group.ui.id
  host_name                      = azurerm_storage_account.ui.primary_web_host
  origin_host_header             = azurerm_storage_account.ui.primary_web_host
  http_port                      = 80
  https_port                     = 443
  certificate_name_check_enabled = true

  # primary_web_host is only populated once the static website feature is enabled —
  # not implied by the attribute reference above, since that resource doesn't set it.
  depends_on = [azurerm_storage_account_static_website.ui]
}

# --- api (Container App) origin ----------------------------------------------
resource "azurerm_cdn_frontdoor_origin_group" "api" {
  name                     = "api-container-app"
  cdn_frontdoor_profile_id = azurerm_cdn_frontdoor_profile.ui.id

  load_balancing {}

  health_probe {
    path                = "/readyz"
    protocol            = "Https"
    request_type        = "GET"
    interval_in_seconds = 100
  }
}

resource "azurerm_cdn_frontdoor_origin" "api" {
  name                           = "api-container-app"
  cdn_frontdoor_origin_group_id  = azurerm_cdn_frontdoor_origin_group.api.id
  host_name                      = var.api_fqdn
  origin_host_header             = var.api_fqdn
  http_port                      = 80
  https_port                     = 443
  certificate_name_check_enabled = true
}

resource "azurerm_cdn_frontdoor_route" "ui" {
  name                          = "ui-default"
  cdn_frontdoor_endpoint_id     = azurerm_cdn_frontdoor_endpoint.ui.id
  cdn_frontdoor_origin_group_id = azurerm_cdn_frontdoor_origin_group.ui.id
  cdn_frontdoor_origin_ids      = [azurerm_cdn_frontdoor_origin.ui.id]

  supported_protocols    = ["Http", "Https"]
  patterns_to_match      = ["/*"]
  forwarding_protocol    = "HttpsOnly"
  https_redirect_enabled = true
  link_to_default_domain = true
}

# --- Build upload (Terraform-managed, not `az storage blob sync`) ------------
# `az storage blob sync`/`az storage blob upload-batch` are Python-CLI calls — the same
# SSL stack this corporate network's TLS-intercepting proxy breaks for *.blob.core
# .windows.net (see docs/deploy-azure.md). `azurerm_storage_blob` goes through the Go-based
# Terraform provider instead, which this network doesn't break (same reasoning as using
# `docker push` instead of `az acr build`).
locals {
  ui_dist_dir = "${path.module}/../../../../ui/dist"
  ui_files    = fileset(local.ui_dist_dir, "**")
  content_types = {
    html  = "text/html"
    js    = "application/javascript"
    css   = "text/css"
    json  = "application/json"
    svg   = "image/svg+xml"
    png   = "image/png"
    ico   = "image/x-icon"
    woff  = "font/woff"
    woff2 = "font/woff2"
    txt   = "text/plain"
  }
}

resource "azurerm_storage_blob" "ui_assets" {
  for_each               = local.ui_files
  name                   = each.value
  storage_account_name   = azurerm_storage_account.ui.name
  storage_container_name = "$web"
  type                   = "Block"
  source                 = "${local.ui_dist_dir}/${each.value}"
  content_md5            = filemd5("${local.ui_dist_dir}/${each.value}")
  content_type           = lookup(local.content_types, lower(reverse(split(".", each.value))[0]), "application/octet-stream")

  depends_on = [azurerm_storage_account_static_website.ui]
}

# GraphQL is a POST API, not cacheable: forward everything straight through, uncached.
resource "azurerm_cdn_frontdoor_route" "graphql" {
  name                          = "graphql"
  cdn_frontdoor_endpoint_id     = azurerm_cdn_frontdoor_endpoint.ui.id
  cdn_frontdoor_origin_group_id = azurerm_cdn_frontdoor_origin_group.api.id
  cdn_frontdoor_origin_ids      = [azurerm_cdn_frontdoor_origin.api.id]

  supported_protocols    = ["Http", "Https"]
  patterns_to_match      = ["/graphql", "/graphql/*"]
  forwarding_protocol    = "HttpsOnly"
  https_redirect_enabled = true
  link_to_default_domain = true
  # No `cache` block: caching is off by default, matching the route's
  # "CachingDisabled" managed policy — GraphQL responses are never cacheable.
}
