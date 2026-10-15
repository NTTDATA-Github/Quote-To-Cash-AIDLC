variable "prefix" {
  type = string
}

variable "location" {
  type = string
}

variable "resource_group_name" {
  type = string
}

variable "vault_id" {
  type        = string
  description = "Key Vault resource ID where secrets are stored"
}

variable "sku_name" {
  type        = string
  default     = "S0"
  description = "Azure Foundry SKU (S0, S1, etc.)"
}

variable "model_name" {
  type        = string
  default     = "claude-haiku-5-5"
  description = "Claude model name to deploy (e.g., claude-haiku-5-5, claude-opus-5-5)"
}

variable "model_version" {
  type        = string
  default     = "latest"
  description = "Model version (e.g., '2024-12-19' or 'latest')"
}

variable "foundry_api_key" {
  type        = string
  default     = ""
  sensitive   = true
  description = "Foundry API key (optional; will be rotated post-apply via Azure portal)"
}
