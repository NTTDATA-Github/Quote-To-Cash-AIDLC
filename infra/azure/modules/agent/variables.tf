variable "prefix" {
  type = string
}

variable "resource_group_name" {
  type = string
}

variable "container_app_environment_id" {
  type        = string
  description = "Container App Environment resource ID"
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

variable "image" {
  type        = string
  description = "Full ACR image ref for the agent (repo:tag)."
}

variable "target_repo_url" {
  type        = string
  description = "Git repo URL the agent clones and opens PRs against (e.g., https://github.com/.../...)"
}

variable "github_token" {
  type        = string
  sensitive   = true
  description = "GitHub PAT (Contents + Pull Requests scopes) for git + PR creation"
}

variable "anthropic_api_key" {
  type        = string
  sensitive   = true
  description = "Anthropic API key for the claude CLI (or leave empty if using CLAUDE_CODE_USE_BEDROCK=1)"
  default     = ""
}

variable "coding_agent_model" {
  type        = string
  default     = "claude-sonnet-5-5"
  description = "Model the agent uses for coding (via claude CLI)"
}

# Optional: for Bedrock-based agent
variable "aws_region" {
  type        = string
  default     = ""
  description = "AWS region (for Bedrock-based agent only)"
}

variable "aws_bearer_token" {
  type        = string
  sensitive   = true
  default     = ""
  description = "AWS bearer token for Bedrock (if using CLAUDE_CODE_USE_BEDROCK=1)"
}
