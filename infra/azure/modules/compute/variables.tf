variable "prefix" {
  type = string
}

variable "resource_group_name" {
  type = string
}

variable "location" {
  type = string
}

variable "log_analytics_workspace_id" {
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

variable "servicebus_connection_string" {
  type      = string
  sensitive = true
}

variable "api_identity_id" {
  type = string
}

variable "api_identity_client_id" {
  type = string
}

variable "worker_identity_id" {
  type = string
}

variable "worker_identity_client_id" {
  type = string
}

variable "api_image" {
  type = string
}

variable "worker_image" {
  type = string
}

variable "api_min_replicas" {
  type = number
}

variable "api_max_replicas" {
  type = number
}

variable "worker_min_replicas" {
  type = number
}

variable "worker_max_replicas" {
  type = number
}

variable "container_cpu" {
  type = number
}

variable "container_memory" {
  type = string
}

variable "app_env" {
  type = list(object({
    name  = string
    value = string
  }))
}
