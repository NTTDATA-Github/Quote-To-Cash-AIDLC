output "client_id" {
  value = one(azuread_application.spa[*].client_id)
}

output "application_id" {
  value = one(azuread_application.spa[*].id)
}
