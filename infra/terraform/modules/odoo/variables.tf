variable "prefix" {
  type = string
}

variable "region" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  type = list(string)
}

variable "execution_role_arn" {
  type = string
}

variable "execution_role_name" {
  type = string
}

variable "odoo_image" {
  type = string
}

variable "odoo_db_password" {
  type      = string
  sensitive = true
}
