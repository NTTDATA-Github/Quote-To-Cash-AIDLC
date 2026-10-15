variable "prefix" {
  type = string
}

variable "resource_group_name" {
  type = string
}

variable "location" {
  type = string
}

variable "container_app_environment_id" {
  type = string
}

variable "registry_login_server" {
  type = string
}

variable "registry_admin_username" {
  type = string
}

variable "registry_admin_password" {
  type      = string
  sensitive = true
}

variable "odoo_identity_id" {
  type = string
}

variable "odoo_identity_client_id" {
  type = string
}

variable "odoo_image" {
  type    = string
  default = ""
}

variable "odoo_db_password" {
  type      = string
  sensitive = true
  default   = ""
}

variable "vault_id" {
  type = string
}

variable "vault_uri" {
  type = string
}
