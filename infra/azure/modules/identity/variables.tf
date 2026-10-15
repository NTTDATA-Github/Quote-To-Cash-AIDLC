variable "prefix" {
  type = string
}

# Off by default until the signed-in principal has Entra permission to create App
# Registrations (Authorization_RequestDenied otherwise — see docs/deploy-azure.md).
# `composition._resolve_identity_provider` already falls back to the header stub when
# ENTRA_CLIENT_ID is unset, so this is a real opt-out, not a broken state.
variable "create_app" {
  type    = bool
  default = false
}

variable "callback_urls" {
  description = "SPA redirect URIs. Empty by default — set once the UI's Front Door URL is known (same chicken-and-egg as Cognito's callback_urls)."
  type        = list(string)
  default     = []
}
