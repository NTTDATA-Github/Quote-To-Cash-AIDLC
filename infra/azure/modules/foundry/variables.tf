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
  default     = "gpt-4o"
  description = "OpenAI-format model to deploy; also used as the deployment name"
}

variable "model_version" {
  type        = string
  default     = "2024-11-20"
  description = "Model version (gpt-4o: 2024-11-20)"
}

variable "foundry_api_key" {
  type        = string
  default     = ""
  sensitive   = true
  description = "Foundry API key (optional; will be rotated post-apply via Azure portal)"
}
