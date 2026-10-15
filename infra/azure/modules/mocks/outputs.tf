output "netsuite_fqdn" {
  value = azurerm_container_app.mock_netsuite.latest_revision_fqdn
}

output "reseller_fqdn" {
  value = azurerm_container_app.mock_reseller.latest_revision_fqdn
}
