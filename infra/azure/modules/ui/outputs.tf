output "storage_account_name" {
  value = azurerm_storage_account.ui.name
}

output "frontdoor_hostname" {
  value = azurerm_cdn_frontdoor_endpoint.ui.host_name
}
