# Container Apps environment + api/worker apps. Replaces ECS Fargate cluster + services +
# ALB/listeners/target groups/ACM — Container Apps' built-in ingress gives free TLS on
# *.azurecontainerapps.io, so there is no ALB-equivalent resource here at all.

resource "azurerm_container_app_environment" "main" {
  name                       = var.prefix
  resource_group_name        = var.resource_group_name
  location                   = var.location
  log_analytics_workspace_id = var.log_analytics_workspace_id
}

resource "azurerm_container_app" "api" {
  name                         = "${var.prefix}-api"
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = var.resource_group_name
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [var.api_identity_id]
  }

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
    min_replicas = var.api_min_replicas
    max_replicas = var.api_max_replicas

    container {
      name   = "api"
      image  = var.api_image
      cpu    = var.container_cpu
      memory = var.container_memory

      dynamic "env" {
        for_each = var.app_env
        content {
          name  = env.value.name
          value = env.value.value
        }
      }

      liveness_probe {
        transport = "HTTP"
        path      = "/livez"
        port      = 8000
      }

      readiness_probe {
        transport = "HTTP"
        path      = "/readyz"
        port      = 8000
      }
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    transport        = "auto"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }
}

resource "azurerm_container_app" "worker" {
  name                         = "${var.prefix}-worker"
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = var.resource_group_name
  revision_mode                = "Single"

  identity {
    type         = "UserAssigned"
    identity_ids = [var.worker_identity_id]
  }

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
    min_replicas = var.worker_min_replicas
    max_replicas = var.worker_max_replicas

    container {
      name   = "worker"
      image  = var.worker_image
      cpu    = var.container_cpu
      memory = var.container_memory

      dynamic "env" {
        for_each = concat(var.app_env, [{ name = "WORKER_ROLE", value = "all" }])
        content {
          name  = env.value.name
          value = env.value.value
        }
      }
    }
  }
}
