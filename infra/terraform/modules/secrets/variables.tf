variable "prefix" {
  type = string
}

variable "odoo_secret_value" {
  type      = string
  sensitive = true
  default   = ""
}
