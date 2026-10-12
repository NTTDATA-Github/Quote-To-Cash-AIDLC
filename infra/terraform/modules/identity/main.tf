# Cognito. A single user pool; role via cognito:groups (OPERATOR), tenant via
# custom:tenant_id — matches the app's single COGNITO_USER_POOL_ID and
# src/shared/identity/cognito.py. (The infra design envisioned two pools; the running code
# uses one. See ADR-0020.)

resource "aws_cognito_user_pool" "main" {
  name = var.prefix

  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  schema {
    name                     = "tenant_id"
    attribute_data_type      = "String"
    mutable                  = true
    developer_only_attribute = false
    string_attribute_constraints {
      min_length = 1
      max_length = 64
    }
  }

  password_policy {
    minimum_length    = 12
    require_lowercase = true
    require_uppercase = true
    require_numbers   = true
    require_symbols   = false
  }
}

resource "aws_cognito_user_pool_client" "spa" {
  name         = "${var.prefix}-spa"
  user_pool_id = aws_cognito_user_pool.main.id

  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["COGNITO"]

  explicit_auth_flows = [
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]

  callback_urls = var.callback_urls
  logout_urls   = var.callback_urls
}

resource "aws_cognito_user_group" "operator" {
  name         = "OPERATOR"
  user_pool_id = aws_cognito_user_pool.main.id
  description  = "Operator / admin users"
}
