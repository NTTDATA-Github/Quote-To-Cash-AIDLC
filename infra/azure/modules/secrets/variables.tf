variable "prefix_alnum" {
  type = string
}

variable "suffix" {
  type = string
}

variable "resource_group_name" {
  type = string
}

variable "location" {
  type = string
}

variable "tenant_id" {
  type = string
}

variable "api_principal_id" {
  type = string
}

variable "worker_principal_id" {
  type = string
}

variable "odoo_principal_id" {
  type = string
}

variable "odoo_secret_value" {
  type      = string
  sensitive = true
  default   = ""
}

variable "anthropic_api_key" {
  type      = string
  sensitive = true
  default   = ""
}
