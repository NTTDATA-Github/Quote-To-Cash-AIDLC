# Log Analytics workspace — replaces the CloudWatch log groups. Container Apps' built-in
# logging ships stdout/stderr here; no per-app log-group resource needed (unlike
# one log group per service).

resource "azurerm_log_analytics_workspace" "main" {
  name                = "${var.prefix}-logs"
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
}
