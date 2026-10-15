variable "prefix" {
  type = string
}

variable "resource_group_name" {
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

variable "keycloak_image" {
  type = string
}

variable "db_server_id" {
  type = string
}

variable "db_fqdn" {
  type = string
}

variable "db_admin_username" {
  type = string
}

variable "db_admin_password" {
  type      = string
  sensitive = true
}

variable "vault_id" {
  type = string
}

variable "admin_password" {
  description = "Keycloak realm admin password. Empty = generate one (see terraform output)."
  type        = string
  sensitive   = true
  default     = ""
}
