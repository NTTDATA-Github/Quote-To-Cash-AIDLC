variable "prefix" {
  type = string
}

variable "resource_group_name" {
  type = string
}

variable "container_app_environment_id" {
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

variable "mock_netsuite_image" {
  type = string
}

variable "mock_reseller_image" {
  type = string
}

# A throwaway dev/test HMAC secret for verifying mock webhook deliveries — not a real
# credential, never used against production. Passed as a plain container command arg
# (visible in the Container App's revision config), same as running the script locally
# with --secret on the command line; marked sensitive only to keep it out of CLI/log
# output here, not as a claim that it's handled as a real secret end to end.
variable "mock_reseller_secret" {
  type      = string
  sensitive = true
  default   = "whsec_mock_dev"
}
