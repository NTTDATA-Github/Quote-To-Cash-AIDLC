output "netsuite_fqdn" {
  value = azurerm_container_app.mock_netsuite.ingress[0].fqdn
}

output "reseller_fqdn" {
  value = azurerm_container_app.mock_reseller.ingress[0].fqdn
}
