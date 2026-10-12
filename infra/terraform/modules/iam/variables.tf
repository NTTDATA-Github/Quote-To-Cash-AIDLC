variable "prefix" {
  type = string
}

variable "topic_arn" {
  type = string
}

variable "work_queue_arns" {
  type = list(string)
}

variable "dlq_arns" {
  type = list(string)
}

variable "secret_arn_glob" {
  description = "ARN pattern for all project secrets the app may read/create."
  type        = string
}

variable "github_oidc_repo" {
  description = "owner/name allowed to assume the deploy role via OIDC. Empty = no role."
  type        = string
  default     = ""
}
