# Mock NetSuite + mock reseller webhook receiver (scripts/mock_netsuite.py,
# scripts/dev_webhook_receiver.py) — dev/test aids, not the shipped application. They're
# deployed as Container Apps here only so the Azure-deployed api/worker (and a human
# testing against them) have a reachable URL, the same role `scripts/local.sh` gives them
# locally. Same image (Dockerfile.mocks); CMD picks which script runs.
#
# Neither needs Key Vault or Service Bus access, or a managed identity at all — ACR
# pull is via the registry's admin credentials (modules/registry), and nothing else
# they touch needs authenticating to Azure.

resource "azurerm_container_app" "mock_netsuite" {
  name                         = "${var.prefix}-mock-netsuite"
  container_app_environment_id = var.container_app_environment_id
  resource_group_name          = var.resource_group_name
  revision_mode                = "Single"

  secret {
    name  = "acr-password"
    value = var.registry_admin_password
  }

  registry {
    server               = var.registry_login_server
    username             = var.registry_admin_username
    password_secret_name = "acr-password"
  }

  template {
    min_replicas = 1
    max_replicas = 1

    container {
      name    = "mock-netsuite"
      image   = var.mock_netsuite_image
      cpu     = 0.25
      memory  = "0.5Gi"
      command = ["python", "-m", "scripts.mock_netsuite", "--port", "8075"]
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8075
    transport        = "auto"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }
}

resource "azurerm_container_app" "mock_reseller" {
  name                         = "${var.prefix}-mock-reseller"
  container_app_environment_id = var.container_app_environment_id
  resource_group_name          = var.resource_group_name
  revision_mode                = "Single"

  secret {
    name  = "acr-password"
    value = var.registry_admin_password
  }

  registry {
    server               = var.registry_login_server
    username             = var.registry_admin_username
    password_secret_name = "acr-password"
  }

  template {
    min_replicas = 1
    max_replicas = 1

    container {
      name    = "mock-reseller"
      image   = var.mock_reseller_image
      cpu     = 0.25
      memory  = "0.5Gi"
      command = ["python", "-m", "scripts.dev_webhook_receiver", "--port", "8090", "--secret", var.mock_reseller_secret]
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8090
    transport        = "auto"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }
}
