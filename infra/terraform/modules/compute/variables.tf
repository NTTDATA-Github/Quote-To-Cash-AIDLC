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

variable "app_sg_id" {
  type = string
}

variable "alb_sg_id" {
  type = string
}

variable "api_image" {
  type = string
}

variable "worker_image" {
  type = string
}

variable "api_desired_count" {
  type = number
}

variable "worker_desired_count" {
  type = number
}

variable "task_cpu" {
  type = number
}

variable "task_memory" {
  type = number
}

variable "execution_role_arn" {
  type = string
}

variable "api_task_role_arn" {
  type = string
}

variable "worker_task_role_arn" {
  type = string
}

variable "api_log_group" {
  type = string
}

variable "worker_log_group" {
  type = string
}

variable "app_env" {
  description = "Shared container environment (list of {name,value})."
  type        = list(object({ name = string, value = string }))
}

variable "acm_certificate_arn" {
  type    = string
  default = ""
}
