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

# Same demo-credential convention as mock_reseller_secret above: these match whatever
# was typed into registerConnection's auth.params/secret for the NetSuite connection
# (scripts/setup_erp_flow.py). Passing them here turns the mock's OAuth 1.0a check ON
# (mock_netsuite.py: verify = consumer_secret is not None and token_secret is not None),
# so it actually re-verifies the platform's signature instead of accepting any header.
variable "netsuite_account_id" {
  type    = string
  default = "TSTDRV123"
}

variable "netsuite_consumer_key" {
  type    = string
  default = "ck_demo"
}

variable "netsuite_token_id" {
  type    = string
  default = "ti_demo"
}

variable "netsuite_consumer_secret" {
  type      = string
  sensitive = true
  default   = "cs_demo"
}

variable "netsuite_token_secret" {
  type      = string
  sensitive = true
  default   = "ts_demo"
}

# The live api Container App's hostname, for building the mock's outbound webhook URL.
variable "api_fqdn" {
  type = string
}

# Connection id the mock's webhooks target (`POST /erp/webhook/{connection_id}`) — the
# id `registerConnection` returned when the NetSuite connection was created (it's
# generated at runtime, not something Terraform can know). Blank skips passing
# --webhook-url at all (mock_netsuite.py falls back to its unreachable 127.0.0.1
# default, so webhooks just silently fail — fine until a connection exists to point at).
variable "netsuite_connection_id" {
  type    = string
  default = ""
}

# Must equal the "netsuite-webhook-secret" value in Key Vault (connections.service's
# webhook_secret_ref is resolved from there, never from this container's own config) —
# mock_netsuite.py's built-in default, so leaving this unset on both sides still matches.
variable "netsuite_webhook_secret" {
  type      = string
  sensitive = true
  default   = "ns-webhook-demo"
}
