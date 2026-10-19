# ERP agent service — code generation via Claude Code CLI (ADR-0022 follow-up).
#
# Headless service that takes approved mappings and generates adapter code,
# runs tests, and opens PRs. Uses the locally-installed `claude` CLI (shelled out),
# not the Python SDK, so env vars control auth (ANTHROPIC_API_KEY or AWS_BEARER_TOKEN_BEDROCK).
#
# Internal-only Container App — never publicly reachable. The API calls it
# via HttpAdapterRunLauncher (composition.py) when an operator approves a mapping.
#
# Note: agent_runs.db and worktrees/ live on ephemeral container storage —
# state is lost on restart. For a POC that's acceptable; production would need
# Azure Files mount (out of scope here).

resource "azurerm_container_app" "agent" {
  name                         = "${var.prefix}-agent"
  container_app_environment_id = var.container_app_environment_id
  resource_group_name          = var.resource_group_name
  revision_mode                = "Single"

  registry {
    server               = var.registry_login_server
    username             = var.registry_admin_username
    password_secret_name = "acr-password"
  }

  secret {
    name  = "acr-password"
    value = var.registry_admin_password
  }

  # Anthropic API key and the Bedrock bearer token are each optional (Container Apps
  # rejects a secret with an empty value and no keyVaultUrl, so an unused one must be
  # left out entirely, not just set to "") -- exactly one of the two is expected, picked
  # by whichever var is actually non-empty.
  dynamic "secret" {
    for_each = var.anthropic_api_key != "" ? [var.anthropic_api_key] : []
    content {
      name  = "anthropic-api-key"
      value = secret.value
    }
  }

  dynamic "secret" {
    for_each = var.aws_bearer_token != "" ? [var.aws_bearer_token] : []
    content {
      name  = "aws-bearer-token"
      value = secret.value
    }
  }

  # GitHub PAT for repo access + PR creation.
  secret {
    name  = "github-token"
    value = var.github_token
  }

  template {
    min_replicas = 1
    max_replicas = 1

    container {
      name   = "agent"
      image  = var.image
      cpu    = 2
      memory = "4Gi"

      env {
        name  = "DATABASE_URL"
        value = "sqlite:///./agent_runs.db"
      }
      env {
        name  = "POLL_SECONDS"
        value = "5"
      }
      env {
        name  = "AGENT_TIMEOUT_SECONDS"
        value = "1800"
      }
      env {
        name  = "TARGET_REPO_URL"
        value = var.target_repo_url
      }
      env {
        name  = "REPO_CACHE_DIR"
        value = "/app/repo-cache"
      }
      env {
        name  = "WORKTREES_DIR"
        value = "/app/worktrees"
      }
      env {
        name  = "GITHUB_TOKEN"
        secret_name = "github-token"
      }
      env {
        name  = "CODING_AGENT_MODEL"
        value = var.coding_agent_model
      }

      dynamic "env" {
        for_each = var.anthropic_api_key != "" ? [1] : []
        content {
          name        = "ANTHROPIC_API_KEY"
          secret_name = "anthropic-api-key"
        }
      }

      dynamic "env" {
        for_each = var.aws_bearer_token != "" ? [1] : []
        content {
          name  = "CLAUDE_CODE_USE_BEDROCK"
          value = "1"
        }
      }
      dynamic "env" {
        for_each = var.aws_bearer_token != "" ? [1] : []
        content {
          name  = "AWS_REGION"
          value = var.aws_region
        }
      }
      dynamic "env" {
        for_each = var.aws_bearer_token != "" ? [1] : []
        content {
          name        = "AWS_BEARER_TOKEN_BEDROCK"
          secret_name = "aws-bearer-token"
        }
      }
    }
  }

  ingress {
    allow_insecure_connections = false
    external_enabled           = false  # Internal-only; never public
    target_port                = 8002
    transport                  = "http"

    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }
}
