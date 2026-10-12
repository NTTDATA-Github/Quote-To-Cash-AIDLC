variable "prefix" {
  type = string
}

variable "subnet_ids" {
  type = list(string)
}

variable "db_sg_id" {
  type = string
}

variable "db_name" {
  type = string
}

variable "db_username" {
  type = string
}

variable "db_password" {
  type      = string
  sensitive = true
}

variable "min_acu" {
  type = number
}

variable "max_acu" {
  type = number
}

variable "public_access" {
  type = bool
}
