output "fqdn" {
  # Stable app-level ingress hostname — must stay stable across redeploys, since it's
  # also the `iss` Keycloak stamps into every issued token; a revision-suffixed value
  # here would break token validation on every redeploy (see
  # KeycloakIdentityProvider).
  value = azurerm_container_app.keycloak.ingress[0].fqdn
}

output "realm_url" {
  value = "https://${azurerm_container_app.keycloak.ingress[0].fqdn}/realms/o2c"
}
